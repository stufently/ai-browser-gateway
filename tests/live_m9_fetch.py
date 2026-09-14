#!/usr/bin/env python3
"""Host orchestrator for one isolated M9 live fetch; product checks run in Docker."""
from __future__ import annotations

import grp
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_IMAGE = 'sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'
SERVER = r'''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys, time
HOST, PORT, SENTINEL, MARKER = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
PAGE = (
    "<html><head><title>M9 live</title></head><body>"
    f"<p>{SENTINEL}</p><p id='m'>{MARKER}</p>"
    "<script>window.__secret='script-only'</script>"
    "<style>.x{color:red}</style>"
    "</body></html>"
)
class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return
    def _send(self, status):
        body = PAGE.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/slow':
            time.sleep(30)
            self._send(200)
        elif path == '/forbidden':
            self._send(403)
        else:
            self._send(200)
ThreadingHTTPServer((HOST, PORT), H).serve_forever()
'''


def _run(argv, **kwargs):
    return subprocess.run(argv, check=False, capture_output=True, text=True, **kwargs)


def _docker(*args, check=True):
    completed = _run(['docker', *args])
    if check and completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or 'docker failed')
    return completed


def _labeled_ids(run_id: str) -> list[str]:
    return _docker('ps', '-aq', '--filter', f'label=abg-m9-run={run_id}', check=False).stdout.split()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_port(port, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError('stand did not accept connections')


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def inner_main() -> int:
    sys.path.insert(0, str(ROOT))
    from bench.models import FailureReason
    from gateway.engine import run as gateway_run
    from gateway.fetch import BenchFetcher
    from gateway.models import GatewayRequest, PlanStep

    base = os.environ['ABG_M9_BASE']
    sentinel = os.environ['ABG_M9_SENTINEL']
    marker = os.environ['ABG_M9_MARKER']

    def fetch(provider, path, budget_ms):
        fetcher = BenchFetcher(f'{base}{path}', sentinel, network='host')
        return fetcher(PlanStep(provider, 'direct', 'http'), budget_ms)

    for provider, budget in (('curl', 15_000), ('patchright', 60_000), ('scrapling', 60_000)):
        reply = fetch(provider, '/ok', budget)
        result = reply.result
        _assert(result.error_type is FailureReason.none, f'{provider} error={result.error_type}')
        _assert(sentinel in result.html, f'{provider} html missing sentinel')
        _assert(marker in result.html, f'{provider} html missing unique marker')
        _assert(marker in result.text, f'{provider} text missing unique marker')
        _assert(sentinel in result.text, f'{provider} text missing sentinel')
        _assert('script-only' not in result.text, f'{provider} leaked script text')
        _assert('<' not in result.text, f'{provider} text still has tags')
        print(f'{provider}: status={result.status} bytes={result.bytes_received} '
              f'elapsed_ms={result.elapsed_ms}', flush=True)

    forbidden = fetch('curl', '/forbidden', 15_000)
    _assert(forbidden.result.status == 403, f'403 status={forbidden.result.status}')
    _assert(marker in forbidden.result.html, '403 html missing marker')
    _assert(forbidden.result.error_type is FailureReason.none, '403 transport should succeed')
    outcome = gateway_run(
        GatewayRequest(url=f'{base}/forbidden', sentinel=sentinel, budget_ms=20_000),
        BenchFetcher(f'{base}/forbidden', sentinel, network='host'),
    )
    _assert(not outcome.ok, '403 with sentinel must not be success')
    _assert(outcome.error_type is FailureReason.http_403, f'expected http_403 got {outcome.error_type}')

    ok_outcome = gateway_run(
        GatewayRequest(url=f'{base}/ok', sentinel=sentinel, budget_ms=20_000),
        BenchFetcher(f'{base}/ok', sentinel, network='host'),
    )
    _assert(ok_outcome.ok, f'gateway HTTP path failed: {ok_outcome.error_type}')
    _assert(marker in ok_outcome.html, 'gateway html missing unique marker')
    _assert(marker in ok_outcome.text, 'gateway text missing unique marker')

    timed = fetch('curl', '/slow', 800)
    _assert(timed.result.error_type is FailureReason.timeout, f'slow got {timed.result.error_type}')
    _assert(timed.result.html == '' and timed.result.text == '', 'timeout must not keep a page')
    print(f'timeout: error_type={timed.result.error_type}', flush=True)
    print('live_m9_fetch: ok', flush=True)
    return 0


def main() -> int:
    if os.environ.get('ABG_M9_INNER') == '1':
        return inner_main()

    os.chdir(ROOT)
    run_id = 'abg-m9-' + secrets.token_hex(6)
    sentinel = 'M9LIVE_' + secrets.token_hex(4)
    marker = 'uniq_' + secrets.token_hex(8)
    port = _free_port()
    stand = run_id + '-stand'
    docker_gid = grp.getgrnam('docker').gr_gid
    workdir = tempfile.mkdtemp(prefix=run_id + '-')
    server_path = Path(workdir) / 'server.py'
    server_path.write_text(SERVER, encoding='utf-8')
    os.chmod(server_path, 0o644)
    try:
        started = _docker(
            'run', '-d', '--rm', '--user', '1002:1002', '--network', 'host',
            '--name', stand, '--label', f'abg-m9-run={run_id}',
            '-v', f'{server_path}:/server.py:ro',
            PYTHON_IMAGE, 'python3', '/server.py', '127.0.0.1', str(port), sentinel, marker,
        )
        _ = started.stdout.strip()
        try:
            _wait_port(port)
        except TimeoutError:
            logs = _docker('logs', stand, check=False)
            raise TimeoutError((logs.stdout or '') + (logs.stderr or '')) from None
        base = f'http://127.0.0.1:{port}'
        inner = _docker(
            'run', '--rm', '--user', '1002:1002', '--group-add', str(docker_gid),
            '--network', 'host', '--label', f'abg-m9-run={run_id}',
            '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
            '-e', 'ABG_M9_INNER=1', '-e', f'ABG_M9_BASE={base}',
            '-e', f'ABG_M9_SENTINEL={sentinel}', '-e', f'ABG_M9_MARKER={marker}',
            '-v', f'{ROOT}:{ROOT}:ro', '-w', str(ROOT),
            '-v', '/var/run/docker.sock:/var/run/docker.sock',
            '-v', '/usr/bin/docker:/usr/bin/docker:ro',
            PYTHON_IMAGE, 'python3', 'tests/live_m9_fetch.py',
        )
        sys.stdout.write(inner.stdout)
        sys.stdout.flush()
        if inner.returncode:
            sys.stderr.write(inner.stderr)
            raise RuntimeError(inner.stderr.strip() or f'inner checks failed rc={inner.returncode}')
        return 0
    finally:
        _docker('rm', '--force', stand, check=False)
        for ident in _labeled_ids(run_id):
            _docker('rm', '--force', ident, check=False)
        leftover = _labeled_ids(run_id)
        if leftover:
            raise AssertionError('run containers remain')
        try:
            server_path.unlink()
            Path(workdir).rmdir()
        except OSError:
            pass


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'live_m9_fetch failed: {type(exc).__name__}', file=sys.stderr)
        raise
