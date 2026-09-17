"""Docker-only live assertions, shared by the committed release runner."""
import json
import os
from pathlib import Path
import secrets
import time

from tests.live_m12_service import PY, LABEL, docker, cli_checks


def stand():
    """Explicit release barrier for observing real curl/browser containers."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Event, Lock
    from urllib.parse import urlsplit
    hits, entered, gates, lock = [], set(), {}, Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            body, status, content_type = b'ok', 200, 'text/html; charset=utf-8'
            if path == '/__state':
                with lock:
                    body = json.dumps({'hits': hits, 'entered': sorted(entered)}).encode()
            elif path.startswith('/__release/'):
                with lock:
                    gates.setdefault(path.rsplit('/', 1)[-1], Event()).set()
            else:
                marker = path.rsplit('/', 1)[-1]
                with lock:
                    hits.append(path)
                if path.startswith(('/barrier/', '/curlbarrier/')):
                    with lock:
                        gate = gates.setdefault(marker, Event())
                        entered.add(marker)
                    if not gate.wait(90):
                        status = 504
                    body = ("document.body.textContent=" + json.dumps(marker)).encode()
                    content_type = 'application/javascript'
                    if path.startswith('/curlbarrier/'):
                        body = ('<html><body><p>' + marker + '</p></body></html>').encode()
                        content_type = 'text/html'
                elif path.startswith('/hold/'):
                    body = ('<html><body><script src="/barrier/' + marker + '"></script></body></html>').encode()
                elif path.startswith('/js/'):
                    parts = json.dumps([marker[:8], marker[8:]])
                    body = ('<html><body><script>document.body.textContent=' + parts + '.join("");</script></body></html>').encode()
                elif path.startswith('/forbidden/'):
                    status, body = 403, b'<html><body>Forbidden</body></html>'
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


def inner(config_path):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.request import Request, urlopen
    config = json.loads(Path(config_path).read_text())
    assert os.getuid() == os.getgid() == 1002
    token = Path(config['token_file']).read_text()
    ping_secret = Path(config['ping_file']).read_text().strip()
    secrets_to_hide = [token, ping_secret, 'm12-live-secret', 'live:live']
    endpoint = 'http://127.0.0.1:' + config['port']
    stand = 'http://127.0.0.1:' + config['stand_port']
    target = 'http://' + config['run'] + '-stand:8080'
    api, monitor = config['api'], config['monitor']
    release = config['release']

    def read(url):
        with urlopen(url, timeout=2) as response:
            return json.load(response)

    def wait_for(check, message, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = check()
                if value:
                    return value
            except OSError:
                pass
            time.sleep(.1)
        raise AssertionError(message)

    def inspect(ident):
        return json.loads(docker('inspect', ident).stdout)[0]

    def safe_text(text):
        assert all(value not in text for value in secrets_to_hide), 'secret exposed'

    def mounts(data, expected):
        actual = {m['Destination']: (m['Source'], m['RW']) for m in data['Mounts']
                  if m['Type'] != 'tmpfs'}
        assert actual == expected, 'unexpected or writable container bind mount'

    def identity(data, ident, groups):
        assert data['Config']['User'] == '1002:1002', 'container UID/GID'
        assert set(data['HostConfig'].get('GroupAdd') or []) == set(groups), 'supplementary groups'
        status = docker('exec', ident, 'python3', '-c',
                        'print(open("/proc/1/status").read())').stdout
        values = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
        assert values['Uid'].split() == ['1002'] * 4, 'effective UID'
        assert values['Gid'].split() == ['1002'] * 4, 'effective GID'
        actual = set(values['Groups'].split())
        assert set(groups) <= actual <= {'1002', *groups}, 'effective supplementary groups'

    for ident, role in [(api, 'api'), (monitor, 'monitor')]:
        data = inspect(ident)
        identity(data, ident, [config['gid']] if role == 'api' else [])
        assert data['HostConfig']['ReadonlyRootfs'], role + ' root must be read-only'
        assert '/tmp' in data['HostConfig']['Tmpfs'], role + ' writable tmpfs missing'
        assert data['HostConfig']['NetworkMode'] != 'host', role + ' host networking'
        assert data['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
        assert data['Config']['WorkingDir'] == release
        safe_text(json.dumps(data['Config']))
        expected = {release: (release, False)}
        if role == 'api':
            expected.update({'/var/run/docker.sock': ('/var/run/docker.sock', True),
                             '/run/abg/token': (config['token_file'], False),
                             '/run/abg/proxies.toml': (config['profiles_file'], False)})
            ports = data['NetworkSettings']['Ports']
            assert ports == {'8765/tcp': [{'HostIp': '127.0.0.1', 'HostPort': config['port']}]}, 'API loopback publication'
        else:
            expected['/run/abg/ping'] = (config['ping_file'], False)
            assert not any(data['NetworkSettings']['Ports'].values()), 'monitor published port'
            names = {entry.split('=', 1)[0] for entry in data['Config']['Env']}
            assert not names.intersection({'ABG_TOKEN', 'ABG_TOKEN_FILE', 'ABG_PROFILES_FILE', 'ABG_PROXY'}), 'monitor secret env'
        mounts(data, expected)
    assert '29.' in docker('exec', api, 'docker', '--version').stdout
    receiver_ip = next(iter(inspect(monitor)['NetworkSettings']['Networks'].values()))['IPAddress']
    receiver = 'http://' + receiver_ip + ':' + config['recv_port'] + '/hits'
    wait_for(lambda: read(endpoint + '/health') == {'ok': True}, 'API health readiness')
    # This receiver is shared only with the real Compose sidecar. No check_once,
    # manual ping, or secondary monitor can satisfy the automatic loop evidence.
    wait_for(lambda: read(receiver).count('/m12-live-secret') >= 2,
             'Compose monitor automatic success pings missing', 20)
    os.environ['ABG_TOKEN'] = token
    env, headers = cli_checks(config['run'], config['port'], config['stand_port'], safe_text)

    def fetch(url, browser=True):
        body = json.dumps({'url': url, 'format': 'html', 'allow_browser': browser,
                           'budget_ms': 120000 if browser else 20000}).encode()
        with urlopen(Request(env['ABG_URL'], data=body, headers=headers), timeout=150) as response:
            value = json.load(response)
        safe_text(json.dumps(value))
        return value

    request_ids = set()
    for kind, browser in [('curlbarrier', False), ('hold', True)]:
        marker = kind + secrets.token_hex(8)
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(fetch, target + '/' + kind + '/' + marker, browser)
            try:
                wait_for(lambda: marker in read(stand + '/__state')['entered'],
                         kind + ' provider barrier was not reached', 50)
                assert not pending.done(), 'provider did not remain at barrier'
                providers = docker('ps', '-q', '--filter', 'label=abg.owner=ai-browser-gateway',
                                   '--filter', 'label=abg.instance=' + config['instance'],
                                   '--filter', 'label=abg.role=provider').stdout.split()
                assert len(providers) == 1, 'expected one held provider'
                data = inspect(providers[0])
                identity(data, providers[0], [])
                mounts(data, {'/opt/abg/probe.py':
                              (release + '/bench/providers/docker/probe.py', False)})
                assert not any(data['NetworkSettings']['Ports'].values()), 'provider published port'
                assert data['HostConfig']['NetworkMode'] == config['network']
                assert not data['HostConfig']['Privileged'], 'privileged provider'
                # Established transport uses writable roots; its probe bind is RO.
                assert data['HostConfig']['ReadonlyRootfs'] is False, 'provider root mode changed'
                if browser:
                    assert data['HostConfig']['ShmSize'] == 1024 ** 3
                labels = data['Config']['Labels']
                assert labels['abg.request'] and labels['abg.request'] not in request_ids
                request_ids.add(labels['abg.request'])
                safe_text(json.dumps(data['Config']))
                assert not any(entry.startswith(('ABG_TOKEN=', 'ABG_TOKEN_FILE=', 'ABG_HC_PING_FILE=',
                                                  'ABG_PROFILES_FILE=')) for entry in data['Config']['Env'])
                # Browser is inside the external-script handler, which cannot
                # return until explicitly released after this health response.
                assert read(endpoint + '/health') == {'ok': True}, 'health blocked by occupied slot'
                assert not pending.done(), 'barrier released before health evidence'
            finally:
                with urlopen(stand + '/__release/' + marker, timeout=2) as response:
                    response.read()
            assert pending.result()['ok'], kind + ' request failed after barrier release'

    counters = {name: 'http://127.0.0.1:' + port + '/__counts'
                for name, port in config['proxy_ports'].items()}
    names = []
    for _ in range(2):
        path = '/forbidden/' + secrets.token_hex(12)
        before = {name: read(url).count(path) for name, url in counters.items()}
        value = fetch(target + path, False)
        egress = [attempt['egress_profile'] for attempt in value['attempts']
                  if attempt.get('egress_profile') not in (None, 'direct')]
        assert len(egress) == 1, 'must have exactly one egress attempt'
        selected = egress[0]
        assert selected in counters, 'unknown egress profile'
        after = {name: read(url).count(path) for name, url in counters.items()}
        assert {name: after[name] - before[name] for name in counters} == {
            name: int(name == selected) for name in counters}, 'each request must use its selected real proxy exactly once'
        names.append(selected)
    assert set(names) == {'alpha', 'beta'}, 'rotation did not change real proxy'

    success_before = read(receiver).count('/m12-live-secret')
    fail_before = read(receiver).count('/m12-live-secret/fail')
    docker('stop', api)
    wait_for(lambda: read(receiver).count('/m12-live-secret/fail') > fail_before,
             'Compose monitor automatic failure ping missing', 20)
    docker('start', api)
    wait_for(lambda: read(endpoint + '/health') == {'ok': True}, 'API restart health')
    wait_for(lambda: read(receiver).count('/m12-live-secret') > success_before,
             'Compose monitor recovery ping missing', 20)
    docker('restart', api)
    wait_for(lambda: read(endpoint + '/health') == {'ok': True}, 'API second restart health')
    docker('run', '-d', '--name', config['run'] + '-owned', '--user', '1002:1002',
           '--label', LABEL + '=' + config['run'], '--label', 'abg.owner=ai-browser-gateway',
           '--label', 'abg.instance=' + config['instance'], '--label', 'abg.role=provider',
           PY, 'sleep', '3600')
    docker('stop', api)
    leftovers = docker('ps', '-aq', '--filter', 'label=abg.owner=ai-browser-gateway',
                       '--filter', 'label=abg.instance=' + config['instance'],
                       '--filter', 'label=abg.role=provider').stdout.strip()
    assert not leftovers, 'owned provider survives shutdown'
    assert inspect(config['run'] + '-foreign')['State']['Running'], 'foreign provider removed'
    for ident in (api, monitor):
        logs = docker('logs', ident)
        safe_text(logs.stdout + logs.stderr)
    print(json.dumps({'live_m12': True, 'egress': names, 'automatic_monitor': True,
                      'provider_barriers': ['curl', 'patchright']}), flush=True)


