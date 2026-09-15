"""Charge shared browser queue time to the caller's remaining budget."""
import time
from bench.models import FetchResult, FailureReason as F, ChallengeType as C
from bench.providers.registry import by_name
from gateway.models import ProviderReply


def clock_ms():
    return time.monotonic_ns() / 1_000_000


def limit_fetcher(fetcher, semaphore, *, url, clock=clock_ms):
    def limited(step, budget_ms):
        if by_name(step.provider).kind != 'browser':
            return fetcher(step, budget_ms)
        start = clock()
        acquired = False
        try:
            acquired = budget_ms > 0 and semaphore.acquire(timeout=budget_ms / 1000)
            elapsed = max(0, clock() - start)
            remaining = int(budget_ms - elapsed)
            if acquired and remaining > 0:
                return fetcher(step, remaining)
            return ProviderReply(FetchResult(
                provider=step.provider, provider_version='unknown', requested_url=url,
                final_url=url, status=None, html='', text='', elapsed_ms=int(elapsed),
                startup_ms=0, cpu_ms=0, peak_rss_mb=0, bytes_received=0, redirects=0,
                error_type=F.timeout, challenge=C.none))
        finally:
            if acquired:
                semaphore.release()
    return limited
