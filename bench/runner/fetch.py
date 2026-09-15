"""One real provider request. Isolated from execute_plan's shared environ."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from bench.models import ChallengeType, FailureReason, FetchResult
from bench.providers.registry import build_argv, by_name, parse_output

PROBE_FILE = Path(__file__).resolve().parents[1] / 'providers' / 'docker' / 'probe.py'


def _failed(provider: str, url: str, reason: FailureReason) -> tuple[FetchResult, None]:
    return FetchResult(
        provider=provider, provider_version='unknown', requested_url=url, final_url=url,
        status=None, html='', text='', elapsed_ms=0, startup_ms=0, cpu_ms=0,
        peak_rss_mb=0.0, bytes_received=0, redirects=0, error_type=reason,
        challenge=ChallengeType.none,
    ), None


def fetch_page(provider, *, url, sentinel, budget_ms, launcher=None,
               egress=None, entrance_url=None, network=None):
    return _fetch(provider, url=url, sentinel=sentinel, budget_ms=budget_ms,
                  launcher=launcher, egress=egress, entrance_url=entrance_url,
                  network=network)


def validate_url(url):
    """Reject ambiguous URLs before IO, without echoing caller data."""
    try:
        if (not isinstance(url, str) or not url or url != url.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in url)):
            raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port == 0):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('invalid URL') from None


def fetch_content(provider, *, url, budget_ms, launcher=None,
                  egress=None, entrance_url=None, network=None):
    return _fetch(provider, url=url, sentinel=None, budget_ms=budget_ms,
                  launcher=launcher, egress=egress, entrance_url=entrance_url,
                  network=network, content_only=True)


def _fetch(provider, *, url, sentinel, budget_ms, launcher=None,
           egress=None, entrance_url=None, network=None, content_only=False):
    from bench.runner.execute import DockerLauncher, _validated

    if (type(budget_ms) is not int or budget_ms <= 0
            or (content_only and budget_ms > 180_000)):
        raise ValueError('invalid budget')
    if not content_only and (not isinstance(sentinel, str) or not sentinel):
        raise ValueError('invalid sentinel')
    validate_url(url)
    try:
        selected = by_name(provider)
    except (KeyError, TypeError, ValueError):
        raise ValueError('invalid request') from None

    if (provider == 'rss' and not entrance_url) or (egress is not None and not egress[1]):
        return _failed(provider, url, FailureReason.not_measured)

    proxy = None if egress is None else egress[1]
    child_env = {key: value for key, value in os.environ.items() if key != 'ABG_PROXY'}
    if proxy:
        child_env['ABG_PROXY'] = proxy
    target = (entrance_url or url) if selected.kind == 'entrance' else url
    argv = build_argv(
        selected, url=target, sentinel=sentinel, network=network,
        proxy_env='ABG_PROXY' if proxy else None,
        probe_bind=PROBE_FILE, include_content=True, budget_ms=budget_ms,
        **({'content_only': True} if content_only else {}),
    )
    argv.extend(['--mode', 'cold'])
    runner = DockerLauncher() if launcher is None else launcher
    try:
        rc, stdout, _stderr = runner.run(argv, budget_ms / 1000, env=child_env)
        if rc:
            return _failed(
                provider, url,
                FailureReason.environment_error if rc in (125, 126, 127)
                else FailureReason.provider_error,
            )
        payload = _validated(parse_output(selected, stdout))
        if not isinstance(payload.get('html'), str) or not isinstance(payload.get('text'), str):
            return _failed(provider, url, FailureReason.provider_error)
        if payload['err']:
            try:
                reason = FailureReason(payload['err'])
            except ValueError:
                reason = FailureReason.provider_error
            if reason is not FailureReason.none:
                return _failed(provider, url, reason)
        result = FetchResult(
            provider=provider,
            provider_version=payload.get('provider_version') or 'unknown',
            requested_url=url,
            final_url=payload['final_url'],
            status=payload['status'],
            html=payload['html'],
            text=payload['text'],
            elapsed_ms=int(payload['elapsed_ms']),
            startup_ms=int(payload['startup_ms']),
            cpu_ms=int(payload['cpu_ms']),
            peak_rss_mb=payload['peak_rss_mb'],
            bytes_received=payload['bytes'],
            redirects=payload.get('redirects', 0),
            error_type=FailureReason.none,
            challenge=ChallengeType(payload['challenge']),
        )
        return result, payload.get('entrance_age_hours')
    except (subprocess.TimeoutExpired, TimeoutError):
        return _failed(provider, url, FailureReason.timeout)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return _failed(provider, url, FailureReason.provider_error)
