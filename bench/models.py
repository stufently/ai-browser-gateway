"""Normalized fetch result and the single success rule."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureReason(StrEnum):
    none = "none"
    dns_error = "dns_error"
    timeout = "timeout"
    connection_error = "connection_error"
    tls_error = "tls_error"
    http_403 = "http_403"
    http_429 = "http_429"
    http_5xx = "http_5xx"
    javascript_required = "javascript_required"
    challenge_suspected = "challenge_suspected"
    interactive_challenge = "interactive_challenge"
    content_missing = "content_missing"
    content_mismatch = "content_mismatch"
    provider_error = "provider_error"


class ChallengeType(StrEnum):
    none = "none"
    suspected = "suspected"
    javascript_required = "javascript_required"
    interactive = "interactive"
    captcha = "captcha"
    rate_limited = "rate_limited"
    access_denied = "access_denied"


@dataclass(frozen=True, slots=True)
class FetchResult:
    provider: str
    provider_version: str
    requested_url: str
    final_url: str
    status: int | None
    html: str
    text: str
    elapsed_ms: int
    startup_ms: int
    cpu_ms: int
    peak_rss_mb: float
    bytes_received: int
    redirects: int
    error_type: FailureReason
    challenge: ChallengeType


def evaluate(result: FetchResult, sentinel: str) -> tuple[bool, FailureReason]:
    """Success is a found sentinel on a response that is not a failure."""
    if sentinel == "":
        raise ValueError(
            "empty sentinel: a check without expectation is a call defect, not success"
        )
    if result.error_type is not FailureReason.none:
        return (False, result.error_type)
    if result.status == 403:
        return (False, FailureReason.http_403)
    if result.status == 429:
        return (False, FailureReason.http_429)
    if result.status is not None and 500 <= result.status <= 599:
        return (False, FailureReason.http_5xx)
    if result.status is not None and 400 <= result.status <= 499:
        return (False, FailureReason.content_mismatch)
    if sentinel in result.html or sentinel in result.text:
        return (True, FailureReason.none)
    if result.status == 200:
        return (False, FailureReason.content_missing)
    return (False, FailureReason.content_mismatch)
