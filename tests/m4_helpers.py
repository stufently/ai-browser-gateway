"""Synthetic M4 contract records; these are not network measurements."""

from bench.models import ChallengeType, FailureReason
from bench.runner.record import RunRecord


def record(provider, cell, **changes):
    kind, _, ident = cell.partition(':')
    success = changes.get('success', True)
    values = dict(
        provider=provider, provider_version='test',
        scenario=ident if kind == 'scenario' else None,
        target=ident if kind == 'target' else None,
        run_id=f'{provider}:{cell}:cold:0', mode='cold', success=success,
        sentinel_found=success, status=200, final_url='https://example.invalid/',
        challenge_type=ChallengeType.none, elapsed_ms=0, startup_ms=0,
        cpu_ms=0, peak_rss_mb=0.0, bytes=0, redirects=0,
        error_type=FailureReason.none if success else FailureReason.content_missing,
        date='2026-09-07T02:00:00+00:00', kernel='test', docker_version='test',
        image_version='test', egress_ip='unknown', asn='unknown', cell=cell,
    )
    values.update(changes)
    return RunRecord(**values)
