"""Build the price-ordered menu; the engine chooses which steps to execute."""

from gateway.models import GatewayRequest, PlanStep


def plan_steps(request: GatewayRequest) -> tuple[PlanStep, ...]:
    steps = []
    if request.max_age_hours > 0:
        steps.extend(PlanStep(name, "direct", "entrance") for name in ("rss", "wayback"))
    steps.append(PlanStep("curl", "direct", "http"))
    if request.allow_browser:
        steps.append(PlanStep("patchright", "direct", "browser"))
    steps.extend(PlanStep("curl", profile, "egress") for profile in request.egress_profiles)
    return tuple(steps)
