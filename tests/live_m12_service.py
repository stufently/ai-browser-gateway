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
from tests.live_m10_product import ROOT, docker, server as stand

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
    hits, lock = [], Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/__counts':
                with lock:
                    body = json.dumps(hits).encode()
                status = 200
            else:
                with lock:
                    hits.append(path)
                try:
                    with urlopen(Request(self.path), timeout=20) as resp:
                        body, status = resp.read(), resp.status
                except Exception:
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

    _http(Handler, ('127.0.0.1', int(port)))


def inner(run, api_port, stand_port, recv_port, proxy_port):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.request import Request, urlopen
    token = os.environ['ABG_TOKEN']
    endpoint = 'http://127.0.0.1:' + api_port
    deadline = time.monotonic() + 40
    while True:
        try:
            with urlopen(endpoint + '/health', timeout=1) as resp:
                assert json.load(resp) == {'ok': True}
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    marker = 'm12_' + secrets.token_hex(12)
    path = '/js/' + marker
    url = 'http://' + run + '-stand:8080' + path
    with urlopen('http://127.0.0.1:' + stand_port + path, timeout=2) as resp:
        assert marker not in resp.read().decode(), 'marker present before JS'
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
    env.update(ABG_TOKEN=token, ABG_URL=endpoint + '/v1/fetch', ABG_BUDGET_MS='120000')
    proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), url, 'text'], env=env,
                          capture_output=True, text=True, timeout=150)
    assert proc.returncode == 0 and marker in proc.stdout, (proc.returncode, proc.stderr)
    body = json.dumps({'url': url, 'format': 'html', 'budget_ms': 120000}).encode()
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    with urlopen(Request(env['ABG_URL'], data=body, headers=headers), timeout=150) as resp:
        result = json.load(resp)
    assert result['ok'] and marker in result['content']
    assert result['provider'] == 'patchright'
    proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), url],
                          env=env | {'ABG_TOKEN': 'wrong-test-token'},
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0 and proc.stdout == '' and token not in proc.stderr
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(urlopen, Request(env['ABG_URL'], data=body, headers=headers),
                              timeout=150)
        time.sleep(.5)
        with urlopen(endpoint + '/health', timeout=2) as resp:
            assert json.load(resp) == {'ok': True}
        pending.result().close()
    forbidden = 'http://' + run + '-stand:8080/forbidden/' + marker
    names = []
    for _ in range(2):
        payload = json.dumps({'url': forbidden, 'allow_browser': False, 'budget_ms': 20000}).encode()
        with urlopen(Request(env['ABG_URL'], data=payload, headers=headers), timeout=40) as resp:
            value = json.load(resp)
        egress = [a['egress_profile'] for a in value['attempts']
                  if a.get('egress_profile') not in (None, 'direct')]
        assert len(egress) == 1, value['attempts']
        names.append(egress[0])
    assert names[0] != names[1] and set(names) <= {'alpha', 'beta'}
    with urlopen('http://127.0.0.1:' + proxy_port + '/__counts', timeout=2) as resp:
        seen = json.load(resp)
    assert any('/forbidden/' in item for item in seen), seen
    mon = subprocess.Popen(
        [sys.executable, '-m', 'gateway.health_monitor'], cwd=str(ROOT),
        env={**env, 'ABG_HEALTH_URL': endpoint + '/health',
             'ABG_HC_PING_FILE': os.environ['ABG_PING_FILE'],
             'ABG_HEALTH_INTERVAL_SECONDS': '.05', 'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1',
             'PYTHONPATH': str(ROOT), 'HOME': '/tmp', 'PYTHONDONTWRITEBYTECODE': '1'},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        hits = []
        while time.monotonic() < deadline:
            with urlopen('http://127.0.0.1:' + recv_port + '/hits', timeout=2) as resp:
                hits = json.load(resp)
            if hits.count('/m12-live-secret') >= 2:
                break
            time.sleep(.05)
        else:
            raise AssertionError('monitor success ping missing: ' + str(hits))
        docker('stop', os.environ['ABG_API_CONTAINER'])
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with urlopen('http://127.0.0.1:' + recv_port + '/hits', timeout=2) as resp:
                hits = json.load(resp)
            if any(item.endswith('/fail') for item in hits):
                break
            time.sleep(.05)
        else:
            raise AssertionError('monitor fail ping missing: ' + str(hits))
        docker('start', os.environ['ABG_API_CONTAINER'])
    finally:
        mon.terminate()
        out, err = mon.communicate(timeout=3)
    assert 'm12-live-secret' not in out + err
    assert token not in out + err
    print(json.dumps({'live_m12_inner': True, 'egress': names}), flush=True)


def main():
    if len(sys.argv) > 1:
        return {'--stand': lambda: stand(), '--proxy': lambda: proxy(),
                '--receiver': lambda: receiver(sys.argv[2]),
                '--inner': lambda: inner(*sys.argv[2:])}[sys.argv[1]]()
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
    proxy_url = 'http://live:live@' + run + '-proxy:8126'
    profiles_file = private(
        root / 'proxies.toml',
        '[profile.alpha]\nurl = "%s"\n[profile.beta]\nurl = "%s"\n' % (proxy_url, proxy_url))
    host_port = free_port()
    recv_port = free_port()
    ping_live = private(root / 'ping-live', 'http://127.0.0.1:%s/m12-live-secret\n' % recv_port)
    ping_side = private(root / 'ping', 'https://example.invalid/m12-ping\n')
    sha = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    labeled = ['--label', f'{LABEL}={run}']
    common = ['--user', '1002:1002', *labeled, '-e', 'HOME=/tmp',
              '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{ROOT}:{ROOT}:ro', '-w', str(ROOT)]
    daemon = ['--group-add', gid, '-v', '/var/run/docker.sock:/var/run/docker.sock',
              '-v', '/usr/bin/docker:/usr/bin/docker:ro']
    compose = ['docker', 'compose', '-f', str(ROOT / 'deploy/compose.yaml'), '-p', project]
    env = dict(os.environ)
    try:
        docker('build', '-t', image, '-f', str(ROOT / 'deploy/Dockerfile'), str(ROOT))
        ver = docker('run', '--rm', *common, image, 'docker', '--version')
        assert '29.' in ver.stdout, ver.stdout + ver.stderr
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/abg-release'), 'prepare',
             '--repo', str(ROOT), '--sha', sha, '--root', str(root)],
            check=True, capture_output=True, text=True)
        release = root / 'releases' / sha
        env.update(
            ABG_RELEASE=str(release), ABG_TOKEN_FILE=str(token_file),
            ABG_PROFILES_FILE=str(profiles_file), ABG_PING_FILE=str(ping_side),
            ABG_INSTANCE=instance, ABG_DOCKER_GID=gid, ABG_HOST_PORT=host_port,
            ABG_COMPOSE_PROJECT=project, ABG_RUNTIME_IMAGE=image,
            ABG_PROVIDER_NETWORK=project + '_default')
        docker('run', '-d', '--name', run + '-foreign', *labeled,
               '--label', 'abg.owner=other', '--label', 'abg.instance=foreign',
               '--label', 'abg.role=provider', PY, 'sleep', '3600')
        up = subprocess.run(compose + ['up', '-d'], env=env, capture_output=True, text=True)
        if up.returncode:
            raise RuntimeError(up.stderr or up.stdout)
        network = project + '_default'
        docker('run', '-d', '--name', run + '-stand', '--network', network,
               '-p', '127.0.0.1::8080', *common, PY,
               'python3', 'tests/live_m12_service.py', '--stand')
        docker('run', '-d', '--name', run + '-proxy', '--network', network,
               '-p', '127.0.0.1::8126', *common, PY,
               'python3', 'tests/live_m12_service.py', '--proxy')
        docker('run', '-d', '--name', run + '-receiver', '--network', 'host', *common, PY,
               'python3', 'tests/live_m12_service.py', '--receiver', recv_port)
        stand_port = docker('port', run + '-stand', '8080/tcp').stdout.strip().rsplit(':', 1)[-1]
        proxy_port = docker('port', run + '-proxy', '8126/tcp').stdout.strip().rsplit(':', 1)[-1]
        api = subprocess.check_output(
            compose + ['ps', '-q', 'api'], env=env, text=True).strip()
        monitor = subprocess.check_output(
            compose + ['ps', '-q', 'monitor'], env=env, text=True).strip()
        docker('exec', monitor, 'python3', '-c',
               'from gateway.health_monitor import check_once; import sys; '
               'sys.exit(0 if check_once("http://api:8765/health",'
               '"https://example.invalid/m12-ping", timeout=3) else 1)')
        data = json.loads(docker('inspect', api).stdout)[0]
        assert data['Config']['User'] == '1002:1002'
        binds = ' '.join(data['HostConfig'].get('Binds') or [])
        assert str(release) in binds and '/var/run/docker.sock' in binds
        assert token not in json.dumps(data['Config'].get('Env'))
        logs = subprocess.run(compose + ['logs'], env=env, capture_output=True, text=True)
        assert token not in logs.stdout + logs.stderr and 'live:live' not in logs.stdout
        os.environ['ABG_PING_FILE'] = str(ping_live)
        os.environ['ABG_API_CONTAINER'] = api
        proc = docker(
            'run', '--name', run + '-assertions', '--network', 'host', *common, *daemon,
            '-v', f'{ping_live}:{ping_live}:ro',
            '-e', 'ABG_PING_FILE', '-e', 'ABG_API_CONTAINER', '-e', 'ABG_TOKEN',
            image, 'python3', 'tests/live_m12_service.py',
            '--inner', run, host_port, stand_port, recv_port, proxy_port, check=False)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode:
            raise RuntimeError('live assertions failed rc=' + str(proc.returncode))
        subprocess.run(compose + ['restart', 'api'], env=env, check=True,
                       capture_output=True, text=True)
        docker('run', '-d', '--name', run + '-owned', *labeled,
               '--label', 'abg.owner=ai-browser-gateway',
               '--label', 'abg.instance=' + instance,
               '--label', 'abg.role=provider', PY, 'sleep', '3600')
        subprocess.run(compose + ['stop', 'api'], env=env, capture_output=True, text=True)
        time.sleep(1)
        leftover = docker(
            'ps', '-aq', '--filter', 'label=abg.owner=ai-browser-gateway',
            '--filter', 'label=abg.instance=' + instance,
            '--filter', 'label=abg.role=provider').stdout.split()
        assert not leftover, leftover
        assert docker('ps', '-aq', '--filter', 'name=' + run + '-foreign').stdout.strip()
        print('live_m12_service: ok', flush=True)
    finally:
        subprocess.run(compose + ['down', '--remove-orphans'], env=env,
                       capture_output=True, text=True)
        for ident in ids(run):
            docker('rm', '--force', ident, check=False)
        docker('rmi', image, check=False)
        docker('network', 'rm', project + '_default', check=False)
        subprocess.run(['rm', '-rf', str(root)], check=False)


if __name__ == '__main__':
    main()
