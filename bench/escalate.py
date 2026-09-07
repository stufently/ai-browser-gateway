"""Where to go next after one fetch. Imports only bench.models."""

from __future__ import annotations

from enum import StrEnum

from bench.models import ChallengeType, FailureReason


class Step(StrEnum):
    stop = "stop"
    browser = "browser"
    change_egress = "change_egress"
    retry_later = "retry_later"
    give_up = "give_up"
    human = "human"
    investigate = "investigate"


def next_step(error_type, challenge, *, egress_changed: bool) -> Step:
    reason = FailureReason(error_type)
    kind = ChallengeType(challenge)
    if reason is FailureReason.none:
        step = Step.stop
    elif reason is FailureReason.content_missing:
        if kind is ChallengeType.none:
            step = Step.browser
        else:
            step = Step.change_egress
    elif reason is FailureReason.javascript_required:
        if kind is ChallengeType.none:
            step = Step.browser
        else:
            step = Step.change_egress
    elif reason is FailureReason.http_403 or reason is FailureReason.http_429:
        step = Step.change_egress
    elif reason in (
        FailureReason.timeout,
        FailureReason.connection_error,
        FailureReason.dns_error,
        FailureReason.tls_error,
        FailureReason.http_5xx,
    ):
        step = Step.retry_later
    elif reason is FailureReason.content_mismatch:
        step = Step.give_up
    elif reason is FailureReason.interactive_challenge:
        step = Step.human
    elif reason is FailureReason.provider_error:
        step = Step.investigate
    elif reason is FailureReason.environment_error:
        step = Step.investigate
    elif reason is FailureReason.challenge_suspected:
        step = Step.change_egress
    else:
        raise ValueError(f"unlisted error_type: {reason}")
    if egress_changed and step is Step.change_egress:
        return Step.human
    return step
