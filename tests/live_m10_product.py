#!/usr/bin/env python3
"""Local live M10 checks. Host only orchestrates Docker; assertions run inside."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'
LABEL = 'abg-m10-run'


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result


def ids(run_id, role=None):
    filters = ['--filter', f'label={LABEL}={run_id}']
    if role:
        filters += ['--filter', f'label=abg-m10-role={role}']
    return docker('ps', '-aq', *filters).stdout.split()


def server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Lock
    counts, lock = {}, Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/counts':
                with lock:
                    body = json.dumps(counts).encode()
                status = 200
            elif path == '/ready':
                body, status = b'ready', 200
            else:
                with lock:
                    counts[path] = counts.get(path, 0) + 1
                    count = counts[path]
                kind, marker = path.strip('/').split('/', 1) if '/' in path.strip('/') else ('other', '')
                status = 403 if kind == 'forbidden' else 200
                if kind == 'slow':
                    time.sleep(30)
                if kind == 'ladder' and count < 3:
                    html = '<html><body></body></html>'
                elif kind in ('js', 'ladder'):
                    # The contiguous marker is absent in source and appears only in the DOM.
                    parts = json.dumps([marker[:8], marker[8:]])
                    html = '<html><body><script>document.body.appendChild(document.createElement("p")).textContent=' + parts + '.join("");</script></body></html>'
                else:
                    html = '<html><body><p>' + marker + '</p></body></html>'
                body = html.encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


def inner(run_id):
    sys.path.insert(0, str(ROOT))
    from urllib.request import urlopen
    from bench.escalate import Step
    from bench.models import FailureReason as F
    from bench.runner.execute import DockerLauncher
    from gateway.fetch import ProductFetcher
    from gateway.product import ProductRequest, run_product

    base = 'http://' + run_id + '-stand:8080'
    deadline = time.monotonic() + 20
    while True:
        try:
            with urlopen(base + '/ready', timeout=1) as response:
                assert response.status == 200
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)

    class Launcher:
        def run(self, argv, timeout, *, env=None):
            argv = argv[:2] + ['--label', f'{LABEL}={run_id}',
                              '--label', 'abg-m10-role=provider'] + argv[2:]
            return DockerLauncher().run(argv, timeout, env=env)

    for kind, providers, budget in [('direct', ['curl'], 20000),
                                     ('js', ['curl', 'patchright'], 120000),
                                     ('ladder', ['curl', 'patchright', 'scrapling'], 180000),
                                     ('forbidden', ['curl'], 20000),
                                     ('slow', ['curl'], 800)]:
        marker = kind + '_' + secrets.token_hex(12)
        path = '/' + kind + '/' + marker
        url = base + path
        request = ProductRequest(url, allow_browser=kind not in ('forbidden', 'slow'), budget_ms=budget)
        started = time.monotonic()
        outcome = run_product(request, ProductFetcher(url, launcher=Launcher(), network=run_id))
        wall_ms = (time.monotonic() - started) * 1000
        assert [a.provider for a in outcome.attempts] == providers, outcome
        assert all(a.egress_profile == 'direct' for a in outcome.attempts), outcome
        if kind in ('direct', 'js', 'ladder'):
            assert outcome.ok and outcome.step == Step.stop, outcome
            assert marker in outcome.html and marker in outcome.text, outcome
            assert outcome.final_url == url and outcome.provider == providers[-1], outcome
            assert [a.success for a in outcome.attempts] == [False] * (len(providers) - 1) + [True], outcome
            assert [a.error_type for a in outcome.attempts] == [F.content_missing] * (len(providers) - 1) + [F.none], outcome
            assert [a.next_step for a in outcome.attempts] == [Step.browser] * (len(providers) - 1) + [Step.stop], outcome
            assert all(a.status == 200 for a in outcome.attempts), outcome
        else:
            assert not outcome.ok and outcome.html == '' and outcome.text == '', outcome
            if kind == 'forbidden':
                assert outcome.error_type == F.http_403 and outcome.step == Step.human, outcome
                assert outcome.attempts[0].status == 403, outcome
            else:
                assert outcome.error_type == F.timeout and outcome.step == Step.retry_later, outcome
                assert wall_ms < budget + 20000, wall_ms
        with urlopen(base + '/counts', timeout=2) as response:
            counts = json.load(response)
        if kind != 'slow':
            assert counts.get(path) == len(providers), (path, counts, outcome)
        assert not ids(run_id, 'provider'), 'provider containers remain after request'
        print(json.dumps(dict(scenario=kind, providers=providers, count=counts.get(path, 0),
                              ok=outcome.ok, reason=outcome.error_type, wall_ms=round(wall_ms))), flush=True)
    print('live_m10_product: ok', flush=True)


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--server':
            server()
        elif sys.argv[1] == '--inner':
            inner(sys.argv[2])
        return
    run_id = 'abg-m10-' + secrets.token_hex(8)
    socket_gid = os.stat('/var/run/docker.sock').st_gid
    common = ['--rm', '--user', '1002:1002', '--network', run_id,
              '--label', f'{LABEL}={run_id}', '-e', 'HOME=/tmp',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONHASHSEED=0',
              '-v', f'{ROOT}:{ROOT}:ro', '-w', str(ROOT)]
    docker('network', 'create', '--label', f'{LABEL}={run_id}', run_id)
    try:
        docker('run', '-d', '--name', run_id + '-stand', *common,
               IMAGE, 'python3', 'tests/live_m10_product.py', '--server')
        result = docker('run', '--name', run_id + '-orchestrator', *common,
                        '--group-add', str(socket_gid),
                        '-v', '/var/run/docker.sock:/var/run/docker.sock',
                        '-v', '/usr/bin/docker:/usr/bin/docker:ro', IMAGE,
                        'python3', 'tests/live_m10_product.py', '--inner', run_id, check=False)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        if result.returncode:
            raise RuntimeError(f'container assertions failed rc={result.returncode}')
    finally:
        for ident in ids(run_id):
            docker('rm', '--force', ident)
        docker('network', 'rm', run_id)
        # Verify cleanup in a UID1002 container as well.
        cleanup = 'import json,subprocess,sys; r=sys.argv[1]; assert not subprocess.check_output(["docker","ps","-aq","--filter","label=abg-m10-run="+r]).strip(); assert not subprocess.check_output(["docker","network","ls","-q","--filter","label=abg-m10-run="+r]).strip(); print("scoped cleanup: ok")'
        result = docker('run', '--rm', '--user', '1002:1002', '--group-add', str(socket_gid),
                        '-v', '/var/run/docker.sock:/var/run/docker.sock',
                        '-v', '/usr/bin/docker:/usr/bin/docker:ro', IMAGE,
                        'python3', '-c', cleanup, run_id)
        sys.stdout.write(result.stdout)


if __name__ == '__main__':
    main()
