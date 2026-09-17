#!/usr/bin/env python3
"""Scoped live CLI/API/browser stand. Host only orchestrates Docker subprocesses."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

# Reuse M10's stdlib Docker orchestration and JS fixture, without running its inner().
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.live_m10_product import ROOT, IMAGE, docker, server as stand

LABEL = 'abg-m11-run'


def ids(run):
    return docker('ps', '-aq', '--filter', f'label={LABEL}={run}').stdout.split()


def api(run):
    from bench.runner.execute import DockerLauncher
    from gateway.fetch import ProductFetcher
    from gateway.httpapi import make_server
    class Launcher:
        def run(self, argv, timeout, *, env=None):
            argv = argv[:2] + ['--label', f'{LABEL}={run}', '--label', 'abg-m11-role=provider'] + argv[2:]
            return DockerLauncher().run(argv, timeout, env=env)
    def factory(url, **kwargs):
        return ProductFetcher(url, network=run, launcher=Launcher(), **kwargs)
    server = make_server(('0.0.0.0', 8765), token=os.environ['ABG_TOKEN'], fetcher_factory=factory)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def inner(run, api_port, stand_port):
    from urllib.request import Request, urlopen
    endpoint = 'http://127.0.0.1:' + api_port
    deadline = time.monotonic() + 20
    while True:
        try:
            with urlopen(endpoint + '/health', timeout=1) as response:
                assert json.load(response) == {'ok': True}
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    marker = 'm11_' + secrets.token_hex(12)
    path = '/js/' + marker
    url = 'http://' + run + '-stand:8080' + path
    with urlopen('http://127.0.0.1:' + stand_port + path, timeout=2) as response:
        assert marker not in response.read().decode(), 'marker exists before JavaScript'
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
    env.update(ABG_TOKEN=os.environ['ABG_TOKEN'], ABG_URL=endpoint + '/v1/fetch', ABG_BUDGET_MS='120000')
    for mode in ('text', 'html'):
        proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), url, mode], env=env,
                              capture_output=True, text=True, timeout=150)
        assert proc.returncode == 0 and not proc.stderr, (proc.returncode, proc.stderr)
        assert marker in proc.stdout, 'JS content missing from CLI'
        if mode == 'html':
            assert '<p>' + marker + '</p>' in proc.stdout
        else:
            assert proc.stdout.strip() == marker, 'CLI printed an envelope or wrong content'
        print(json.dumps({'scenario': 'CLI-JS-' + mode, 'ok': True}), flush=True)
    body = json.dumps({'url': url, 'format': 'html', 'budget_ms': 120000}).encode()
    req = Request(env['ABG_URL'], data=body, headers={'Authorization': 'Bearer ' + env['ABG_TOKEN'],
                                                   'Content-Type': 'application/json'})
    with urlopen(req, timeout=150) as response:
        result = json.load(response)
    assert result['ok'] and marker in result['content']
    assert [a['provider'] for a in result['attempts']] == ['curl_cffi', 'patchright'], result['attempts']
    assert result['provider'] == 'patchright'
    for scenario, extra, target in [('wrong-token', {'ABG_TOKEN': 'wrong-test-token'}, url),
            ('okfalse', {'ABG_ALLOW_BROWSER': '0'}, url.replace('/js/', '/forbidden/'))]:
        proc = subprocess.run([str(ROOT / 'scripts/abg-fetch'), target], env=env | extra,
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode != 0 and proc.stdout == ''
        assert isinstance(json.loads(proc.stderr)['error'], str)
        assert env['ABG_TOKEN'] not in proc.stderr
        print(json.dumps({'scenario': scenario, 'failure_handled': True}), flush=True)
    assert not docker('ps', '-aq', '--filter', f'label={LABEL}={run}',
                      '--filter', 'label=abg-m11-role=provider').stdout.strip()
    print('live_m11_api: ok; real ProductFetcher curl_cffi -> patchright', flush=True)


def main():
    if len(sys.argv) > 1:
        return {'--stand': stand, '--api': api, '--inner': inner}[sys.argv[1]](*sys.argv[2:])
    run = 'abg-m11-' + secrets.token_hex(8)
    gid = str(os.stat('/var/run/docker.sock').st_gid)
    # Ephemeral test token only; docker receives its name, never its value in argv.
    os.environ['ABG_TOKEN'] = secrets.token_hex(24)
    common = ['--rm', '--user', '1002:1002', '--label', f'{LABEL}={run}',
              '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONHASHSEED=0',
              '-v', f'{ROOT}:{ROOT}:ro', '-w', str(ROOT)]
    daemon = ['--group-add', gid, '-v', '/var/run/docker.sock:/var/run/docker.sock',
              '-v', '/usr/bin/docker:/usr/bin/docker:ro']
    docker('network', 'create', '--label', f'{LABEL}={run}', run)
    try:
        for role, port, more in [('stand', '8080', []), ('api', '8765', daemon + ['-e', 'ABG_TOKEN'])]:
            docker('run', '-d', '--name', run + '-' + role, '--network', run, '-p', '127.0.0.1::' + port,
                   *common, *more, IMAGE, 'python3', 'tests/live_m11_api.py', '--' + role,
                   *([run] if role == 'api' else []))
        ports = [docker('port', run + '-' + role, port + '/tcp').stdout.strip().rsplit(':', 1)[-1]
                 for role, port in [('api', '8765'), ('stand', '8080')]]
        proc = docker('run', '--name', run + '-assertions', '--network', 'host', *common, *daemon,
                      '-e', 'ABG_TOKEN', IMAGE, 'python3', 'tests/live_m11_api.py', '--inner', run, *ports, check=False)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode:
            raise RuntimeError('Docker live assertions failed rc=' + str(proc.returncode))
    finally:
        for ident in ids(run):
            docker('rm', '--force', ident)
        docker('network', 'rm', run)
        cleanup = ('import subprocess,sys; r=sys.argv[1]; '
                   'assert not subprocess.check_output(["docker","ps","-aq","--filter","label=abg-m11-run="+r]).strip(); '
                   'assert not subprocess.check_output(["docker","network","ls","-q","--filter","label=abg-m11-run="+r]).strip(); '
                   'print("scoped cleanup: ok")')
        proc = docker('run', '--rm', '--user', '1002:1002', *daemon, IMAGE, 'python3', '-c', cleanup, run)
        sys.stdout.write(proc.stdout)


if __name__ == '__main__':
    main()
