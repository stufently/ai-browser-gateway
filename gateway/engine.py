"""Execute the existing escalation rule without owning any network or process IO."""

from collections.abc import Callable
import time

from bench.escalate import Step, next_step
from bench.models import FailureReason, evaluate
from bench.providers import registry
from gateway.models import Attempt, GatewayOutcome, GatewayRequest, PlanStep, ProviderReply
from gateway.plan import plan_steps


def _clock_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def run(
    request: GatewayRequest,
    fetcher: Callable[[PlanStep, int], ProviderReply],
    *,
    clock: Callable[[], int] = _clock_ms,
) -> GatewayOutcome:
    """Run a forward-only ladder, passing the remaining budget to each fetch.

    The fetcher owns deadline enforcement during its call and returns normalized
    failures in ProviderReply. Adapter exceptions propagate to the caller.
    Failed outcomes carry no page payload; diagnostics live in attempts.
    """
    if request.sentinel == "":
        raise ValueError("empty sentinel: a check requires an expectation")
    if request.url == "":
        raise ValueError("empty url")
    if request.budget_ms <= 0:
        raise ValueError("budget_ms must be positive")

    start = clock()
    plan = plan_steps(request)
    attempts: list[Attempt] = []
    used: set[tuple[str, str]] = set()
    egress_changed = False

    def finish(reason: FailureReason, decision: Step,
               accepted: ProviderReply | None = None) -> GatewayOutcome:
        result = accepted.result if accepted is not None else None
        return GatewayOutcome(
            ok=result is not None,
            url=request.url,
            final_url=result.final_url if result is not None else request.url,
            html=result.html if result is not None else "",
            text=result.text if result is not None else "",
            provider=result.provider if result is not None else None,
            age_hours=accepted.age_hours if accepted is not None else None,
            error_type=reason,
            step=decision,
            attempts=tuple(attempts),
            elapsed_ms=clock() - start,
        )

    cursor = 0
    while cursor < len(plan):
        step = plan[cursor]
        remaining = request.budget_ms - (clock() - start)
        if remaining <= 0:
            return finish(FailureReason.timeout, Step.retry_later)

        reply = fetcher(step, remaining)
        used.add((step.provider, step.egress_profile))
        egress_changed = egress_changed or step.purpose == "egress"
        ok, reason = evaluate(reply.result, request.sentinel)
        entrance = registry.by_name(step.provider).kind == "entrance"
        if entrance:
            fresh = (reply.age_hours is not None
                     and reply.age_hours <= request.max_age_hours)
            if ok and not fresh:
                ok, reason = False, FailureReason.content_mismatch
            decision = None
        else:
            decision = next_step(reason, reply.result.challenge,
                                 egress_changed=egress_changed)

        attempts.append(Attempt(
            provider=step.provider,
            egress_profile=step.egress_profile,
            success=ok,
            error_type=reason,
            challenge=reply.result.challenge,
            status=reply.result.status,
            elapsed_ms=reply.result.elapsed_ms,
            age_hours=reply.age_hours,
            next_step=decision,
        ))
        if ok:
            return finish(FailureReason.none, Step.stop, reply)
        if entrance:
            cursor += 1
            continue

        if decision is Step.browser:
            purpose = "browser"
        elif decision is Step.change_egress:
            purpose = "egress"
        elif decision is Step.stop:
            raise AssertionError("next_step returned stop for an unsuccessful response")
        else:
            return finish(reason, decision)

        # Skipped menu entries stay skipped. Curl on a new egress is a new
        # route, but duplicate profiles must never retry the same route.
        following = next((index for index in range(cursor + 1, len(plan))
                          if plan[index].purpose == purpose
                          and (plan[index].provider, plan[index].egress_profile) not in used),
                         None)
        if following is None:
            return finish(reason, decision)
        cursor = following

    # plan_steps always includes direct HTTP, so entrances cannot exhaust it.
    raise AssertionError("gateway plan ended without a direct HTTP step")
