"""Execute a sequential plan; provider failures are observations, not exceptions."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from bench.models import ChallengeType, FailureReason, FetchResult, evaluate
from bench.providers.registry import build_argv, by_name, parse_output
from bench.runner.environment import FIELDS
from bench.runner.record import RunRecord


class Launcher(Protocol):
    def run(self, argv: list[str], timeout: float, *, env: dict[str, str] | None = None
            ) -> tuple[int, str, str]: ...


class DockerLauncher:
    """The host-side external-command boundary. No shell and no inherited stdin."""

    def run(self, argv: list[str], timeout: float, *, env=None) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory(prefix='abg-run-') as directory:
            cidfile = Path(directory) / 'container.id'
            is_container = argv[:2] == ['docker', 'run']
            identity = 'abg.launch=' + uuid4().hex if is_container else None
            command = (argv[:2] + ['--cidfile', str(cidfile), '--label', identity] + argv[2:]
                       if is_container else argv)
            kwargs = dict(timeout=timeout, capture_output=True, text=True, errors='replace',
                          stdin=subprocess.DEVNULL)
            if env is not None:
                kwargs['env'] = env
            try:
                result = subprocess.run(command, **kwargs)
                return result.returncode, result.stdout, result.stderr
            except subprocess.TimeoutExpired:
                # Killing the Docker client alone does not stop its daemon's container.
                if is_container:
                    self._cleanup(cidfile, identity, env=env)
                raise

    @staticmethod
    def _cleanup(cidfile, identity, *, env):
        # Create can finish after the client dies, without ever writing cidfile.
        # All discovery/removal attempts share the existing 30-second budget.
        deadline = time.monotonic() + 30
        try:
            cid = cidfile.read_text().strip()
        except OSError:
            cid = ''
        seen = bool(cid)
        pause_before_removal = False
        kwargs = dict(capture_output=True, text=True, errors='replace',
                      stdin=subprocess.DEVNULL)
        if env is not None:
            kwargs['env'] = env
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                ids = [cid] if cid else []
                # Use cidfile only once; after any failed removal rediscover by label.
                cid = ''
                if not ids:
                    found = subprocess.run(
                        ['docker', 'ps', '--all', '--quiet', '--filter', 'label=' + identity],
                        timeout=remaining, **kwargs)
                    if found.returncode == 0:
                        ids = found.stdout.split()
                        if not ids and seen:
                            return
                        seen = seen or bool(ids)
                remaining = deadline - time.monotonic()
                if ids and remaining > 0:
                    if pause_before_removal:
                        time.sleep(min(0.1, remaining))
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return
                    removed = subprocess.run(['docker', 'rm', '--force', *ids],
                                             timeout=remaining, **kwargs)
                    if removed.returncode == 0:
                        return
                    # It may already be gone (--rm or a concurrent sweep).
                    # Check the label immediately before waiting or retrying rm.
                    pause_before_removal = True
                    continue
            except (OSError, subprocess.SubprocessError):
                # Cleanup failure must not replace the original TimeoutExpired.
                pass
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.1, remaining))
                pause_before_removal = False


def _number(value, field, *, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'invalid {field}: expected a finite nonnegative number')
    if integer and type(value) is not int:
        raise ValueError(f'invalid {field}: expected an integer')
    return value


def _validated(payload):
    for key in ('ok', 'sentinel'):
        if type(payload[key]) is not bool:
            raise ValueError(f'invalid {key}: expected a boolean')
    if payload['status'] is not None and (
        type(payload['status']) is not int or not 100 <= payload['status'] <= 599
    ):
        raise ValueError('invalid HTTP status')
    for key in ('final_url', 'title'):
        if not isinstance(payload[key], str):
            raise ValueError(f'invalid {key}')
    if payload['err'] is not None and not isinstance(payload['err'], str):
        raise ValueError('invalid err')
    for key in ('elapsed_ms', 'startup_ms', 'cpu_ms', 'peak_rss_mb'):
        _number(payload[key], key)
    _number(payload['bytes'], 'bytes', integer=True)
    _number(payload.get('redirects', 0), 'redirects', integer=True)
    if payload.get('entrance_age_hours') is not None:
        _number(payload['entrance_age_hours'], 'entrance_age_hours')
    ChallengeType(payload['challenge'])
    return payload


def _record(item, provider, cell, env, payload, failure):
    if payload is None:
        # M1 requires numeric fields. Zero means unavailable on a launch/protocol
        # failure, never an estimated latency. The report omits these failures
        # from metric summaries while keeping them in the coverage denominator.
        payload = dict(ok=False, sentinel=False, status=None, final_url=cell['url'],
                       elapsed_ms=0, startup_ms=0, cpu_ms=0, peak_rss_mb=0.0,
                       bytes=0, challenge='none', err=None)
    error = failure or FailureReason.none
    if not failure and payload['err']:
        try:
            error = FailureReason(payload['err'])
        except ValueError:
            error = FailureReason.provider_error
    found = payload['sentinel']
    result = FetchResult(
        provider=provider.name, provider_version=payload.get('provider_version') or 'unknown',
        requested_url=cell['url'], final_url=payload['final_url'], status=payload['status'],
        html='', text=cell['sentinel'] if found else '',
        elapsed_ms=int(payload['elapsed_ms']), startup_ms=int(payload['startup_ms']),
        cpu_ms=int(payload['cpu_ms']), peak_rss_mb=payload['peak_rss_mb'],
        bytes_received=payload['bytes'], redirects=payload.get('redirects', 0),
        error_type=error, challenge=ChallengeType(payload['challenge']),
    )
    success, error = evaluate(result, cell['sentinel'])
    if success and not payload['ok']:
        success, error = False, FailureReason.provider_error
    kind, _, ident = item.cell.partition(':')
    metadata = {key: env.get(key) or 'unknown' for key in FIELDS}
    return RunRecord(
        provider=provider.name, provider_version=result.provider_version,
        scenario=ident if kind == 'scenario' else None,
        target=ident if kind == 'target' else None,
        run_id=item.run_id, mode=item.mode, success=success, sentinel_found=found,
        status=result.status, final_url=result.final_url, challenge_type=result.challenge,
        elapsed_ms=result.elapsed_ms, startup_ms=result.startup_ms, cpu_ms=result.cpu_ms,
        peak_rss_mb=result.peak_rss_mb, bytes=result.bytes_received, redirects=result.redirects,
        error_type=error, image_version=provider.image, cell=item.cell, **metadata,
        entrance_age_hours=payload.get('entrance_age_hours'),
        egress_profile=env.get('egress_profile') or 'direct',
    )


def execute_plan(plan, *, launcher, cells, env, timeout=180, pause_s=0.0, sleep=None,
                 egress=None, skip_reason=None) -> list[RunRecord]:
    if not math.isfinite(pause_s) or pause_s < 0 or timeout <= 0:
        raise ValueError('pause_s must be nonnegative and timeout must be positive')
    plan = tuple(plan)
    if len({item.run_id for item in plan}) != len(plan):
        raise ValueError('duplicate run IDs')
    for item in plan:
        by_name(item.provider)
        cell = cells[item.cell]
        if not isinstance(cell['sentinel'], str) or not cell['sentinel']:
            raise ValueError(f'{item.cell}: empty or invalid sentinel')
        if item.mode not in ('cold', 'warm'):
            raise ValueError(f'invalid mode: {item.mode}')
    sleep = time.sleep if sleep is None else sleep
    profile_name, proxy_url = ('direct', None) if egress is None else egress
    env = {**env, 'egress_profile': profile_name}
    if egress is not None and not proxy_url:
        if skip_reason is FailureReason.environment_error:
            return [
                _record(item, by_name(item.provider), cells[item.cell], env, None,
                        FailureReason.environment_error)
                for item in plan
            ]
        return [
            _record(item, by_name(item.provider), cells[item.cell], env, None,
                    FailureReason.not_measured)
            for item in plan
        ]
    proxy_env = 'ABG_PROXY' if proxy_url else None
    previous_proxy = os.environ.get('ABG_PROXY')
    had_proxy = 'ABG_PROXY' in os.environ
    if proxy_url:
        os.environ['ABG_PROXY'] = proxy_url
    try:
        seen_hosts = set()
        records = []
        for item in plan:
            provider, cell = by_name(item.provider), cells[item.cell]
            url = cell['url']
            if provider.kind == 'entrance':
                entrance_url = cell.get('entrances', {}).get(provider.name)
                if item.cell.startswith('scenario:') or (provider.name != 'wayback' and not entrance_url):
                    records.append(_record(item, provider, cell, env, None, FailureReason.not_measured))
                    continue
                url = entrance_url or url
            host = urlsplit(url).hostname or url
            if host in seen_hosts and pause_s:
                # A full pause after prior completion is conservative even when
                # other hosts intervened, and does not depend on wall-clock changes.
                sleep(pause_s)
            network = 'host' if item.cell.startswith('scenario:') else None
            argv = build_argv(provider, url=url, sentinel=cell['sentinel'], network=network,
                              proxy_env=proxy_env)
            argv.extend(['--mode', item.mode])
            payload, failure = None, None
            try:
                rc, stdout, stderr = launcher.run(argv, timeout)
                if rc != 0:
                    failure = FailureReason.provider_error
                else:
                    payload = _validated(parse_output(provider, stdout))
                if rc in (125, 126, 127):
                    failure = FailureReason.environment_error
            except (subprocess.TimeoutExpired, TimeoutError):
                failure = FailureReason.timeout
            except (OSError, ValueError, KeyError, TypeError, OverflowError):
                failure = FailureReason.provider_error
                payload = None
            seen_hosts.add(host)
            records.append(_record(item, provider, cell, env, payload, failure))
        return records
    finally:
        if proxy_url:
            if had_proxy:
                os.environ['ABG_PROXY'] = previous_proxy
            else:
                os.environ.pop('ABG_PROXY', None)


def fetch_page(provider, *, url, sentinel, budget_ms, launcher=None,
               egress=None, entrance_url=None, network=None):
    from bench.runner.fetch import fetch_page as _fetch_page
    return _fetch_page(provider, url=url, sentinel=sentinel, budget_ms=budget_ms,
                       launcher=launcher, egress=egress, entrance_url=entrance_url,
                       network=network)


def fetch_content(provider, *, url, budget_ms, launcher=None,
                  egress=None, entrance_url=None, network=None):
    from bench.runner.fetch import fetch_content as _fetch_content
    return _fetch_content(provider, url=url, budget_ms=budget_ms, launcher=launcher,
                          egress=egress, entrance_url=entrance_url, network=network)
