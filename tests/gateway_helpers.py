"""Network-free replies and a clock advanced independently of result metrics."""

from bench.models import ChallengeType, FailureReason, FetchResult
from gateway.models import ProviderReply

URL = "https://example.invalid/page"
SENTINEL = "GATEWAY_OK"


def reply(provider="curl", *, status=200, html=SENTINEL, text="", age=None,
          reason=FailureReason.none, challenge=ChallengeType.none, elapsed_ms=7):
    return ProviderReply(FetchResult(
        provider=provider, provider_version="fake", requested_url=URL,
        final_url=URL + "/final", status=status, html=html, text=text,
        elapsed_ms=elapsed_ms, startup_ms=0, cpu_ms=0, peak_rss_mb=0.0,
        bytes_received=len(html.encode()), redirects=1,
        error_type=reason, challenge=challenge,
    ), age_hours=age)


class FakeFetcher:
    """Consume scripted replies; unexpected extra calls fail immediately."""

    def __init__(self, *replies, costs=None):
        self.replies = replies
        self.costs = costs if costs is not None else [10] * len(replies)
        self.calls = []
        self.now = 1000

    def clock(self):
        return self.now

    def __call__(self, step, budget_ms):
        index = len(self.calls)
        self.calls.append((step, budget_ms))
        if index >= len(self.replies):
            raise AssertionError(f"unexpected fetch: {step}")
        self.now += self.costs[index]
        return self.replies[index]

    @property
    def routes(self):
        return [(step.provider, step.egress_profile) for step, _ in self.calls]
