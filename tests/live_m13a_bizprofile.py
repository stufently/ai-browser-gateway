#!/usr/bin/env python3
"""M13a live check: host orchestrates; product and assertions run in Docker."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'
LABEL = 'abg-m13a-run'
SCENARIOS = (
    ('https://bizprofile.net/', 'Comprehensive Directory of Registered Businesses'),
    ('https://www.bizprofile.net/ny/albany/elevate-electric-llc', 'Elevate Electric LLC'),
)


def docker(*args, check=True, timeout=60):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Docker/provider diagnostics can contain content: report only a safe class.
        raise RuntimeError('docker_command_failed')
    return result


def ids(run_id, role=None):
    filters = ['--filter', f'label={LABEL}={run_id}']
    if role:
        filters += ['--filter', f'label=abg-m13a-role={role}']
    return docker('ps', '-aq', *filters).stdout.split()


def inner(run_id):
    from dataclasses import asdict
    from datetime import datetime, timezone

    sys.path.insert(0, str(ROOT))
    from bench.runner.execute import DockerLauncher
    from gateway.fetch import ProductFetcher
    from gateway.product import ProductRequest, run_product

    class Launcher:
        calls = 0

        def run(self, argv, timeout, *, env=None):
            self.calls += 1
            assert self.calls <= 6, 'request_limit_exceeded'
            argv = argv[:2] + ['--pull=never', '--label', f'{LABEL}={run_id}',
                              '--label', 'abg-m13a-role=provider'] + argv[2:]
            return DockerLauncher().run(argv, timeout, env=env)

    launcher = Launcher()
    results = []
    for index, (url, marker) in enumerate(SCENARIOS):
        if index:
            time.sleep(30)
        started_at = datetime.now(timezone.utc).isoformat()
        request = ProductRequest(url, allow_browser=True, budget_ms=120000)
        assert request.expected_text is None and request.egress_profiles == ()
        outcome = run_product(request, ProductFetcher(url, launcher=launcher, network=run_id))
        content_matches = marker in outcome.html or marker in outcome.text
        summary = dict(
            url=url, started_at=started_at, ok=outcome.ok, provider=outcome.provider,
            error_type=outcome.error_type, elapsed_ms=outcome.elapsed_ms,
            content_matches=content_matches,
            attempts=[asdict(attempt) for attempt in outcome.attempts],
        )
        results.append(summary)
        try:
            assert outcome.ok, outcome.error_type.value
            assert outcome.provider == 'scrapling', 'unexpected_provider'
            assert [a.provider for a in outcome.attempts] == ['curl', 'patchright', 'scrapling'], 'unexpected_ladder'
            assert all(a.egress_profile == 'direct' for a in outcome.attempts), 'unexpected_egress'
            assert outcome.attempts[-1].success, 'missing_successful_attempt'
            assert outcome.attempts[-1].challenge.value == 'none', 'challenge_not_cleared'
            assert content_matches, 'content_mismatch'
            assert not ids(run_id, 'provider'), 'provider_container_remains'
        except AssertionError as exc:
            print(json.dumps(dict(ok=False, failure_class=str(exc), results=results,
                                  provider_requests=launcher.calls)), flush=True)
            return 1
    print(json.dumps(dict(ok=True, results=results, provider_requests=launcher.calls)), flush=True)
    return 0


def main():
    if len(sys.argv) > 1:
        if len(sys.argv) == 3 and sys.argv[1] == '--inner':
            return inner(sys.argv[2])
        return 2
    run_id = 'abg-m13a-' + secrets.token_hex(8)
    socket_gid = os.stat('/var/run/docker.sock').st_gid
    common = ['--rm', '--pull=never', '--user', '1002:1002', '--network', run_id,
              '--label', f'{LABEL}={run_id}', '-e', 'HOME=/tmp',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONHASHSEED=0',
              '-v', f'{ROOT}:{ROOT}:ro', '-w', str(ROOT)]
    docker('network', 'create', '--label', f'{LABEL}={run_id}', run_id)
    try:
        result = docker('run', '--name', run_id + '-orchestrator', *common,
                        '--group-add', str(socket_gid),
                        '-v', '/var/run/docker.sock:/var/run/docker.sock',
                        '-v', '/usr/bin/docker:/usr/bin/docker:ro', IMAGE,
                        'python3', 'tests/live_m13a_bizprofile.py', '--inner', run_id,
                        check=False, timeout=330)
        sys.stdout.write(result.stdout)
        if result.returncode and not result.stdout.strip():
            print(json.dumps(dict(ok=False, failure_class='orchestrator_failed',
                                  rc=result.returncode)))
        return result.returncode
    finally:
        for ident in ids(run_id):
            docker('rm', '--force', ident)
        docker('network', 'rm', run_id)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps(dict(ok=False, failure_class='environment_error',
                              exception_type=type(exc).__name__)), flush=True)
        sys.exit(1)
