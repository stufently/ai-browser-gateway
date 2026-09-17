#!/usr/bin/env python3
"""Scoped live M12a: host orchestrates Docker, assertions run inside."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.live_m10_product import ROOT, docker

LABEL = 'abg-m12-run'
PY = 'sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'


def ids(run):
    return docker('ps', '-aq', '--filter', f'label={LABEL}={run}').stdout.split()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return str(sock.getsockname()[1])


def private(path, data):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(data)
    os.chmod(path, 0o600)
    return path


def _http(handler, addr):
    from http.server import ThreadingHTTPServer
    ThreadingHTTPServer(addr, handler).serve_forever()


def proxy():
    from http.server import BaseHTTPRequestHandler
    from threading import Lock
    from urllib.request import Request, urlopen
    from urllib.parse import urlsplit
    from urllib.error import HTTPError
    hits, lock = [], Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/__counts':
                with lock:
                    body = json.dumps(hits).encode()
                status = 200
            else:
                with lock:
                    hits.append(path)
                if urlsplit(self.path).hostname != os.environ['STAND_HOST']:
                    self.send_error(502)
                    return
                try:
                    with urlopen(Request(self.path), timeout=20) as resp:
                        body, status = resp.read(), resp.status
                except HTTPError as exc:
                    body, status = exc.read(), exc.code
                    exc.close()
                except OSError:
                    body, status = b'', 502
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    _http(Handler, ('0.0.0.0', 8126))


def receiver(port):
    from http.server import BaseHTTPRequestHandler
    from threading import Lock
    hits, lock = [], Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            with lock:
                if path == '/hits':
                    body = json.dumps(hits).encode()
                else:
                    hits.append(path)
                    body = b'ok'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    _http(Handler, ('0.0.0.0', int(port)))


def cli_checks(run, api_port, stand_port, safe_text):
    from urllib.request import Request, urlopen
    token = os.environ['ABG_TOKEN']
    endpoint = 'http://127.0.0.1:' + api_port
    marker = 'm12_' + secrets.token_hex(12)
    path = '/js/' + marker
    url = 'http://' + run + '-stand:8080' + path
    with urlopen('http://127.0.0.1:' + stand_port + path, timeout=2) as resp:
        assert marker not in resp.read().decode(), 'marker present before JS'
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
    env.update(ABG_TOKEN=token, ABG_URL=endpoint + '/v1/fetch', ABG_BUDGET_MS='120000')
    proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), url, 'text'], env=env,
                          capture_output=True, text=True, timeout=150)
    safe_text(proc.stdout + proc.stderr)
    assert proc.returncode == 0 and marker in proc.stdout, 'CLI JS fetch failed'
    body = json.dumps({'url': url, 'format': 'html', 'budget_ms': 120000}).encode()
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    with urlopen(Request(env['ABG_URL'], data=body, headers=headers), timeout=150) as resp:
        result = json.load(resp)
    safe_text(json.dumps(result))
    assert result['ok'] and marker in result['content']
    assert result['provider'] == 'patchright'
    proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), url],
                          env=env | {'ABG_TOKEN': 'wrong-test-token'},
                          capture_output=True, text=True, timeout=30)
    safe_text(proc.stdout + proc.stderr)
    assert proc.returncode != 0 and proc.stdout == '' and token not in proc.stderr
    return env, headers


def main():
    if len(sys.argv) > 1:
        from tests.m12_live_checks import inner, stand
        return {'--stand': lambda: stand(), '--proxy': lambda: proxy(),
                '--receiver': lambda: receiver(sys.argv[2]),
                '--inner': lambda: inner(sys.argv[2])}[sys.argv[1]]()
    run = 'abgm12' + secrets.token_hex(6)
    gid = str(os.stat('/var/run/docker.sock').st_gid)
    token = secrets.token_hex(24)
    os.environ['ABG_TOKEN'] = token
    root = Path(os.environ.get('TMPDIR', '/tmp')) / ('abg-m12-' + run)
    root.mkdir(mode=0o700)
    image = 'abg-runtime:m12a-' + run
    project = 'abg-m12a-' + run
    instance = 'm12a-' + run
    token_file = private(root / 'token', token)
    proxies = ['http://live:live@' + run + '-proxy-' + name + ':8126'
               for name in ('alpha', 'beta')]
    profiles_file = private(
        root / 'proxies.toml',
        '[profile.alpha]\nurl = "%s"\n[profile.beta]\nurl = "%s"\n' % tuple(proxies))
    host_port = free_port()
    recv_port = free_port()
    ping_live = private(root / 'ping-live', 'http://127.0.0.1:%s/m12-live-secret\n' % recv_port)
    ping_side = ping_live
    override = root / 'live-compose.json'
    # Keep the real monitor Cmd: passive substitutions must fail the live proof.
    override.write_text(json.dumps({'services': {'monitor': {'environment': {
        'ABG_HEALTH_INTERVAL_SECONDS': '.2', 'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1'}}}}))
    sha = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    release = root / 'releases' / sha
    labeled = ['--label', f'{LABEL}={run}']
    common = ['--user', '1002:1002', *labeled, '-e', 'HOME=/tmp',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{release}:{release}:ro', '-w', str(release)]
    daemon = ['--group-add', gid, '-v', '/var/run/docker.sock:/var/run/docker.sock']
    compose = ['docker', 'compose', '-f', str(release / 'deploy/compose.yaml'),
               '-f', str(override), '-p', project]
    env = dict(os.environ)
    try:
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/abg-release'), 'prepare',
             '--repo', str(ROOT), '--sha', sha, '--root', str(root)],
            check=True, capture_output=True, text=True)
        docker('build', '-t', image, '-f', str(release / 'deploy/Dockerfile'), str(release))
        env.update(
            ABG_RELEASE=str(release), ABG_TOKEN_FILE=str(token_file),
            ABG_PROFILES_FILE=str(profiles_file), ABG_PING_FILE=str(ping_side),
            ABG_INSTANCE=instance, ABG_DOCKER_GID=gid, ABG_HOST_PORT=host_port,
            ABG_COMPOSE_PROJECT=project, ABG_RUNTIME_IMAGE=image,
            ABG_PROVIDER_NETWORK=project + '_default')
        docker('run', '-d', '--name', run + '-foreign', '--user', '1002:1002', *labeled,
               '--label', 'abg.owner=other', '--label', 'abg.instance=foreign',
               '--label', 'abg.role=provider', PY, 'sleep', '3600')
        up = subprocess.run(compose + ['up', '-d'], env=env, capture_output=True, text=True)
        if up.returncode:
            raise RuntimeError(up.stderr or up.stdout)
        network = project + '_default'
        docker('run', '-d', '--name', run + '-stand', '--network', network,
               '-p', '127.0.0.1::8080', *common, PY,
               'python3', 'tests/live_m12_service.py', '--stand')
        proxy_ports = {}
        for name in ('alpha', 'beta'):
            ident = run + '-proxy-' + name
            docker('run', '-d', '--name', ident, '--network', network,
                   '-p', '127.0.0.1::8126', '-e', 'STAND_HOST=' + run + '-stand',
                   *common, PY, 'python3', 'tests/live_m12_service.py', '--proxy')
            proxy_ports[name] = docker('port', ident, '8126/tcp').stdout.strip().rsplit(':', 1)[-1]
        stand_port = docker('port', run + '-stand', '8080/tcp').stdout.strip().rsplit(':', 1)[-1]
        api = subprocess.check_output(
            compose + ['ps', '-q', 'api'], env=env, text=True).strip()
        monitor = subprocess.check_output(
            compose + ['ps', '-q', 'monitor'], env=env, text=True).strip()
        docker('run', '-d', '--name', run + '-receiver', '--network', 'container:' + monitor,
               *common, PY, 'python3', 'tests/live_m12_service.py', '--receiver', recv_port)
        config = private(root / 'live.json', json.dumps({
            'run': run, 'api': api, 'monitor': monitor, 'port': host_port,
            'stand_port': stand_port, 'recv_port': recv_port, 'proxy_ports': proxy_ports,
            'release': str(release), 'gid': gid, 'token_file': str(token_file),
            'ping_file': str(ping_live), 'profiles_file': str(profiles_file),
            'instance': instance, 'network': network}))
        proc = docker(
            'run', '--name', run + '-assertions', '--network', 'host', *common, *daemon,
            '-v', f'{ping_live}:{ping_live}:ro', '-v', f'{token_file}:{token_file}:ro',
            '-v', f'{config}:{config}:ro',
            image, 'python3', 'tests/live_m12_service.py',
            '--inner', str(config), check=False)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode:
            raise RuntimeError('live assertions failed rc=' + str(proc.returncode))
    finally:
        docker('rm', '--force', run + '-receiver', check=False)
        subprocess.run(compose + ['down', '--remove-orphans'], env=env,
                       capture_output=True, text=True)
        providers = docker('ps', '-aq', '--filter', 'label=abg.owner=ai-browser-gateway',
                           '--filter', 'label=abg.instance=' + instance,
                           '--filter', 'label=abg.role=provider', check=False).stdout.split()
        for ident in ids(run) + providers:
            docker('rm', '--force', ident, check=False)
        docker('rmi', image, check=False)
        docker('network', 'rm', project + '_default', check=False)
        subprocess.run(['rm', '-rf', str(root)], check=False)


if __name__ == '__main__':
    main()
