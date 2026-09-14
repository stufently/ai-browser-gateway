"""Immutable public contracts for the gateway and its transport adapter."""

from dataclasses import dataclass

from bench.escalate import Step
from bench.models import ChallengeType, FailureReason, FetchResult


@dataclass(frozen=True, slots=True)
class GatewayRequest:
    url: str
    sentinel: str
    max_age_hours: float = 0.0
    allow_browser: bool = True
    egress_profiles: tuple[str, ...] = ()
    budget_ms: int = 30_000


@dataclass(frozen=True, slots=True)
class PlanStep:
    provider: str
    egress_profile: str
    purpose: str


@dataclass(frozen=True, slots=True)
class ProviderReply:
    result: FetchResult
    age_hours: float | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    egress_profile: str
    success: bool
    error_type: FailureReason
    challenge: ChallengeType
    status: int | None
    elapsed_ms: int
    age_hours: float | None
    next_step: Step | None


@dataclass(frozen=True, slots=True)
class GatewayOutcome:
    ok: bool
    url: str
    final_url: str
    html: str
    text: str
    provider: str | None
    age_hours: float | None
    error_type: FailureReason
    step: Step
    attempts: tuple[Attempt, ...]
    elapsed_ms: int
