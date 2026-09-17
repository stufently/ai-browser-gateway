"""URL-only delivery policy, independent of the benchmark's sentinel policy."""
from dataclasses import dataclass
import math
import time

from bench.escalate import Step
from bench.models import ChallengeType as C, FailureReason as F, FetchResult
from bench.runner.fetch import validate_url
from gateway.models import Attempt, GatewayOutcome, PlanStep


@dataclass(frozen=True)
class ProductRequest:
    url: str
    max_age_hours: float = 0.0
    allow_browser: bool = True
    egress_profiles: tuple[str, ...] = ()
    budget_ms: int = 30_000
    expected_text: str | None = None


def _finite_nonnegative(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _validate_expected(expected_text):
    if expected_text is not None and (
        not isinstance(expected_text, str) or not expected_text.strip()
    ):
        raise ValueError('invalid expected_text')


def _validate(request):
    validate_url(request.url)
    if type(request.budget_ms) is not int or not 1 <= request.budget_ms <= 180_000:
        raise ValueError('invalid budget')
    if not _finite_nonnegative(request.max_age_hours):
        raise ValueError('invalid max_age_hours')
    if type(request.allow_browser) is not bool:
        raise ValueError('invalid allow_browser')
    if not isinstance(request.egress_profiles, tuple) or any(
        not isinstance(name, str) or not name or name == 'direct'
        for name in request.egress_profiles
    ):
        raise ValueError('invalid egress_profiles')
    _validate_expected(request.expected_text)


def accept_page(result: FetchResult, expected_text=None) -> tuple[bool, F]:
    """Check real content in protocol/status/challenge/expectation order."""
    _validate_expected(expected_text)
    if result.error_type != F.none:
        return False, result.error_type
    status = result.status
    if type(status) is not int:
        return False, F.provider_error
    if status == 403:
        return False, F.http_403
    if status == 429:
        return False, F.http_429
    if 500 <= status <= 599:
        return False, F.http_5xx
    if not 200 <= status <= 299:
        return False, F.content_mismatch
    challenge_reason = {
        C.interactive: F.interactive_challenge, C.rate_limited: F.http_429,
        C.access_denied: F.http_403, C.javascript_required: F.javascript_required,
    }.get(result.challenge)
    if challenge_reason is not None:
        return False, challenge_reason
    if expected_text is not None:
        if expected_text not in result.html and expected_text not in result.text:
            return False, F.content_missing
    elif result.challenge == C.suspected:
        return False, F.challenge_suspected
    elif result.challenge == C.captcha:
        return False, F.interactive_challenge
    if not result.text.strip():
        return False, F.content_missing
    return True, F.none


def plan_product(request) -> tuple[PlanStep, ...]:
    _validate(request)
    steps = []
    if request.max_age_hours > 0:
        steps.extend(PlanStep(name, 'direct', 'entrance') for name in ('rss', 'wayback'))
    steps.append(PlanStep('curl_cffi', 'direct', 'http'))
    if request.allow_browser:
        steps.extend(PlanStep(name, 'direct', 'browser') for name in ('patchright', 'scrapling'))
    steps.extend(PlanStep('curl_cffi', name, 'egress') for name in dict.fromkeys(request.egress_profiles))
    return tuple(steps)


def _clock_ms():
    return time.monotonic_ns() // 1_000_000


def run_product(request, fetcher, *, clock=_clock_ms) -> GatewayOutcome:
    """Run a finite ladder, charging every measured call to one deadline."""
    plan = plan_product(request)  # Validation precedes the first clock read.
    start = clock()
    attempts = []
    cursor = 0

    def finish(reason, decision, reply=None):
        result = reply.result if reply is not None else None
        return GatewayOutcome(
            ok=result is not None, url=request.url,
            final_url=result.final_url if result is not None else request.url,
            html=result.html if result is not None else '',
            text=result.text if result is not None else '',
            provider=result.provider if result is not None else None,
            age_hours=reply.age_hours if reply is not None else None,
            error_type=reason, step=decision, attempts=tuple(attempts),
            elapsed_ms=clock() - start,
        )

    while cursor < len(plan):
        step = plan[cursor]
        remaining = request.budget_ms - (clock() - start)
        if remaining <= 0:
            return finish(F.timeout, Step.retry_later)
        reply = fetcher(step, remaining)
        late = clock() - start >= request.budget_ms
        ok, reason = accept_page(reply.result, request.expected_text)
        entrance = step.purpose == 'entrance'
        if entrance and ok and not (
            _finite_nonnegative(reply.age_hours) and reply.age_hours <= request.max_age_hours
        ):
            ok, reason = False, F.content_mismatch
        following = None
        if late:
            ok, reason, decision = False, F.timeout, Step.retry_later
        elif entrance:
            decision = None
            following = cursor + 1
        elif ok:
            decision = Step.stop
        elif reason == F.not_measured:
            decision = None
            following = cursor + 1
        elif reason in (F.timeout, F.connection_error, F.dns_error, F.tls_error, F.http_5xx):
            decision = Step.retry_later
        elif reason in (F.provider_error, F.environment_error):
            decision = Step.investigate
        elif reason == F.content_mismatch:
            decision = Step.give_up
        elif reason == F.interactive_challenge or step.purpose == 'egress':
            decision = Step.human
        elif reason in (F.http_403, F.challenge_suspected, F.content_missing,
                        F.javascript_required, F.http_429):
            # A 429 bypasses browsers; other delivery failures exhaust them first.
            purposes = ('egress',) if reason == F.http_429 else ('browser', 'egress')
            following = next((i for i in range(cursor + 1, len(plan))
                              if plan[i].purpose in purposes), None)
            decision = (Step.human if following is None else
                        Step.browser if plan[following].purpose == 'browser' else Step.change_egress)
        else:
            raise ValueError('invalid failure reason')
        attempts.append(Attempt(
            provider=step.provider, egress_profile=step.egress_profile,
            success=ok, error_type=reason, challenge=reply.result.challenge,
            status=reply.result.status, elapsed_ms=reply.result.elapsed_ms,
            age_hours=reply.age_hours, next_step=decision,
        ))
        if ok:
            return finish(F.none, Step.stop, reply)
        if following is None:
            return finish(reason, decision)
        cursor = following
    return finish(F.not_measured, Step.human)
