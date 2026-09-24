"""Frozen M12a public-contract oracle; stdlib, synthetic secrets, Docker only.

Run: python3 -m unittest -v tests.probe_m12_service
No production Docker/provider calls. Release tests replace only the git CLI
boundary with committed archive bytes; live acceptance exercises actual git.
"""
import collections
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import inspect
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import unittest
from unittest.mock import patch
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'probe-only-token-7Q!'
URL = 'https://example.invalid/probe'
PROFILES = {k: 'http://fake-user:fake-password@' + k + '.invalid:8126'
            for k in ('a', 'b', 'c')}

def private(path, data):
    path = Path(path)
    with path.open('wb') as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(data.encode() if isinstance(data, str) else data)
    return path

def clean_env(**values):
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    env.update(values)
    return env

@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)

def request(addr, data=None, *, token=TOKEN, method='POST', path='/v1/fetch'):
    conn = HTTPConnection(*addr, timeout=12)
    try:
        conn.request(method, path, json.dumps({'url': URL} if data is None else data),
            {'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'})
        res = conn.getresponse()
        return res.status, json.loads(res.read())
    finally:
        conn.close()

def reply(step, status=200):
    from bench.models import FetchResult, FailureReason, ChallengeType
    from gateway.models import ProviderReply
    return ProviderReply(FetchResult(
        step.provider, 'probe', URL, URL, status, '<p>page</p>', 'page',
        0, 0, 0, 0, 0, 0, FailureReason.none, ChallengeType.none))

class ProbeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='m12-probe-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def api(self, module, name):
        self.assertIsNotNone(importlib.util.find_spec(module),
            'missing M12 public module: ' + module)
        value = getattr(importlib.import_module(module), name, None)
        self.assertTrue(callable(value), 'missing M12 public callable: ' + name)
        return value

    def module(self, name, env, timeout=5):
        return subprocess.run([sys.executable, '-m', name], cwd=ROOT,
            env=clean_env(**env), capture_output=True, text=True, timeout=timeout)

    def script(self, name, args, *, env=None):
        path = ROOT / 'scripts' / name
        self.assertTrue(path.is_file(), 'missing M12 public script: ' + name)
        return subprocess.run([sys.executable, str(path), *map(str, args)],
            cwd=ROOT, env=env or clean_env(), capture_output=True,
            text=True, timeout=12)

    def config(self, **extra):
        token = private(self.base / 'token', TOKEN + '\r\n')
        profiles = private(self.base / 'profiles', self.toml(PROFILES))
        env = dict(ABG_TOKEN_FILE=str(token), ABG_PROFILES_FILE=str(profiles),
            ABG_INSTANCE='probe-m12', ABG_BIND='127.0.0.1', ABG_PORT='0')
        env.update(extra)
        return env

    @staticmethod
    def toml(profiles):
        return ''.join('[profile.' + json.dumps(k) + ']\nurl = ' + json.dumps(v) + '\n'
            for k, v in profiles.items())

    def redacted(self, text, secrets):
        for secret in secrets:
            self.assertNotIn(secret, text)

class ServiceProbe(ProbeCase):
    def test_service_config_and_rotation(self):
        make = self.api('gateway.service', 'make_service')
        calls = []
        def factory(url, *, profiles, entrances):
            calls.append(profiles)
            return lambda s, b: reply(s, 429 if s.egress_profile == 'direct' else 200)
        env = self.config()
        with patch.dict(os.environ, clean_env(ABG_TOKEN='ambient-must-not-win'), clear=True):
            server = make(env, fetcher_factory=factory)
        with serving(server) as addr:
            orders = []
            for _ in range(4):
                status, value = request(addr, {'url': URL, 'allow_browser': False})
                self.assertEqual(status, 200)
                self.assertIs(value['ok'], True)
                orders.append(value['attempts'][-1]['egress_profile'])
                self.redacted(json.dumps(value), [TOKEN, *PROFILES.values()])
            self.assertEqual(orders, ['a', 'b', 'c', 'a'])
        self.assertEqual(calls, [PROFILES] * 4)
        self.assertEqual(len({id(p) for p in calls}), 4)
        with patch.dict(os.environ, clean_env(**env), clear=True):
            server = make(fetcher_factory=factory)
        server.server_close()

    def test_config_fails_before_bind(self):
        make = self.api('gateway.service', 'make_service')
        env = self.config()
        # Simulate uid before imports, including implementations caching getuid.
        code = """import os
uid = os.getuid() + 1
os.getuid = os.geteuid = lambda: uid
from gateway.service import make_service
try:
    server = make_service()
except Exception:
    raise SystemExit(0)
server.server_close()
raise SystemExit(1)
"""
        proc = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            env=clean_env(**env), capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0)
        cases = []
        for key in ('ABG_TOKEN_FILE', 'ABG_PROFILES_FILE', 'ABG_INSTANCE'):
            cases += [(key, None), (key, '')]
        cases += [('ABG_TOKEN', 'forbidden-secret'), ('ABG_PORT', '-1'),
            ('ABG_PORT', '65536'), ('ABG_PORT', 'nan'),
            ('ABG_BROWSER_LIMIT', '0'), ('ABG_BROWSER_LIMIT', '-1'),
            ('ABG_BROWSER_LIMIT', '1.5'), ('ABG_INSTANCE', 'X'),
            ('ABG_INSTANCE', '../unsafe'), ('ABG_INSTANCE', 'a' * 64),
            ('ABG_BIND', '')]
        for key, value in cases:
            candidate = dict(env)
            if value is None:
                candidate.pop(key)
            else:
                candidate[key] = value
            with self.subTest(key=key, value=value):
                self.reject(make, candidate)
        for key in ('ABG_TOKEN_FILE', 'ABG_PROFILES_FILE'):
            path = Path(env[key])
            original = path.read_bytes()
            for mode in (0o640, 0o604, 0o660, 0o000):
                path.chmod(mode)
                try:
                    self.reject(make, env)
                finally:
                    path.chmod(0o600)
            private(path, '')
            self.reject(make, env)
            path.unlink()
            self.reject(make, env)
            path.mkdir()
            self.reject(make, env)
            path.rmdir()
            private(path, original)
        for token in ('a b', 'a\tb', 'a\nb', '\n', 'é', 'x\x7f'):
            private(env['ABG_TOKEN_FILE'], token)
            self.reject(make, env)

    def reject(self, make, env):
        binds, fetches = [], []
        output = io.StringIO()
        def bind(*a, **kw):
            binds.append(1)
            raise OSError('probe-bind-must-not-happen')
        with patch.object(socket.socket, 'bind', bind), redirect_stderr(output):
            rejected = False
            try:
                server = make(env, fetcher_factory=lambda *a, **k: fetches.append(1))
            except (Exception, SystemExit):
                rejected = True
            else:
                server.server_close()
        self.assertTrue(rejected)
        self.assertEqual(binds, [])
        self.assertEqual(fetches, [])
        self.redacted(output.getvalue(), [TOKEN, str(self.base), *PROFILES.values()])

    def test_strict_profiles(self):
        make = self.api('gateway.service', 'make_service')
        env = self.config()
        invalid = ['not TOML', '', '[profile]\n', '[profile.a]\n',
            'profile = []', '[profile.a]\nurl = 17']
        for name, value in [('', 'http://h.invalid:80'), ('direct', 'http://h.invalid'),
            ('a', ''), ('a', 'socks5://h.invalid:80'),
            ('a', 'http:///no-host'), ('a', 'http://h.invalid:bad'),
            ('a', 'http://h.invalid:65536'), ('a', 'http://h.invalid:-1'),
            ('a', 'http://h.invalid/white space'),
            ('a', 'http://h.invalid/\ncontrol')]:
            invalid.append(self.toml({'valid': 'http://v.invalid:80', name: value}))
        for body in invalid:
            private(env['ABG_PROFILES_FILE'], body)
            with self.subTest(body=body):
                self.reject(make, env)
        for profiles in ({'single': 'https://u:p@h.invalid:443'}, PROFILES):
            private(env['ABG_PROFILES_FILE'], self.toml(profiles))
            server = make(env, fetcher_factory=lambda *a, **k: None)
            server.server_close()

    def test_service_entrypoint(self):
        self.api('gateway.service', 'make_service')
        env = self.config(ABG_TOKEN='forbidden-entrypoint-secret')
        proc = self.module('gateway.service', env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('invalid_configuration', proc.stderr)
        self.redacted(proc.stdout + proc.stderr,
            [str(self.base), TOKEN, 'forbidden-entrypoint-secret'])

class RotationProbe(ProbeCase):
    def server(self, factory, **kw):
        make = self.api('gateway.httpapi', 'make_server')
        self.assertIn('rotate_profiles', inspect.signature(make).parameters,
            'missing M12 rotate_profiles public keyword')
        return make(('127.0.0.1', 0), token=TOKEN, profiles=PROFILES,
            fetcher_factory=factory, **kw)

    def test_position_consumption(self):
        calls = []
        def factory(url, **kw):
            calls.append(kw['profiles'])
            return lambda s, b: reply(s, 429 if s.egress_profile == 'direct' else 403)
        with serving(self.server(factory, rotate_profiles=True)) as addr:
            observed = []
            for _ in range(4):
                self.assertEqual(request(addr, method='GET', path='/health'), (200, {'ok': True}))
                self.assertEqual(request(addr, token='wrong')[0], 401)
                for data in ({}, {'url': URL, 'budget_ms': True},
            {'url': URL, 'format': 'unknown'}, {'url': URL, 'extra': 1}):
                    self.assertEqual(request(addr, data)[0], 400)
                status, value = request(addr, {'url': URL, 'allow_browser': False})
                self.assertEqual(status, 200)
                self.assertEqual(len(value['attempts']), 2)
                observed.append(value['attempts'][-1]['egress_profile'])
            self.assertEqual(observed, ['a', 'b', 'c', 'a'])
        self.assertEqual(len(calls), 4)

    def test_defaults_and_copies(self):
        for options in ({}, {'rotate_profiles': False}, {'rotate_profiles': True}):
            calls, routes = [], []
            def factory(url, **kw):
                profiles = kw['profiles']
                calls.append(profiles)
                self.assertEqual(profiles, PROFILES)
                profiles.clear()  # a factory cannot corrupt the next request
                def fetch(step, budget):
                    routes.append(step.egress_profile)
                    return reply(step)
                return fetch
            with serving(self.server(factory, **options)) as addr:
                for _ in range(3):
                    status, value = request(addr)
                    self.assertEqual(status, 200)
                    self.assertIs(value['ok'], True)
            self.assertEqual(routes, ['direct'] * 3)
            self.assertEqual(len({id(p) for p in calls}), 3)
        for options in ({}, {'rotate_profiles': False}):
            factory = lambda *a, **k: lambda s, b: reply(s, 429 if s.egress_profile == 'direct' else 200)
            with serving(self.server(factory, **options)) as addr:
                for _ in range(3):
                    self.assertEqual(request(addr)[1]['attempts'][-1]['egress_profile'], 'a')

    def test_concurrent_rotation(self):
        from gateway.product import ProductRequest
        entered, release = threading.Event(), threading.Event()
        copies, objects, lock = [], [], threading.Lock()
        original = ProductRequest.__init__
        def record(obj, *args, **kw):
            original(obj, *args, **kw)
            with lock:
                objects.append((obj, tuple(obj.egress_profiles)))
        def factory(url, **kw):
            with lock:
                copies.append(kw['profiles'])
            def fetch(step, budget):
                if url.endswith('/held') and step.egress_profile == 'direct':
                    entered.set()
                    if not release.wait(8):
                        raise RuntimeError('probe gate timeout')
                return reply(step, 429 if step.egress_profile == 'direct' else 200)
            return fetch
        with patch.object(ProductRequest, '__init__', record):
            with serving(self.server(factory, rotate_profiles=True)) as addr:
                with ThreadPoolExecutor(6) as pool:
                    held = pool.submit(request, addr, {'url': URL + '/held'})
                    try:
                        self.assertTrue(entered.wait(3))
                        self.assertEqual(request(addr, method='GET', path='/health')[0], 200)
                        futures = [pool.submit(request, addr, {'url': URL + '/' + str(i)}) for i in range(11)]
                        results = [f.result(10) for f in futures]
                    finally:
                        release.set()
                    first = held.result(3)
                self.assertEqual(first[0], 200)
                self.assertEqual(first[1]['attempts'][-1]['egress_profile'], 'a')
        results.append(first)
        for status, value in results:
            self.assertEqual(status, 200)
            self.assertIs(value['ok'], True)
        self.assertEqual(collections.Counter(v['attempts'][-1]['egress_profile'] for _, v in results),
            {'a': 4, 'b': 4, 'c': 4})
        self.assertEqual(copies, [PROFILES] * 12)
        self.assertEqual(len({id(p) for p in copies}), 12)
        self.assertTrue(objects)
        for obj, snapshot in objects:
            self.assertIsInstance(obj.egress_profiles, tuple)
            self.assertEqual(obj.egress_profiles, snapshot)
            self.assertIn(snapshot, [('a', 'b', 'c'), ('b', 'c', 'a'), ('c', 'a', 'b')])

@contextmanager
def receiver():
    hits, routes = [], {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            hits.append(self.path)
            status, body, headers, delay = routes.get(self.path, (200, b'{}', {}, 0))
            if delay:
                time.sleep(delay)
            try:
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    with serving(server) as addr:
        yield 'http://127.0.0.1:' + str(addr[1]), hits, routes

class MonitorProbe(ProbeCase):
    def test_health_results(self):
        check = self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes), patch.dict(os.environ, {'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1'}):
            ping = base + '/synthetic-ping-secret'
            cases = [(200, b'{"ok":true}', True), (200, b'{"ok":true,"extra":1}', True),
            (200, b'{"ok":1}', False), (200, b'{"ok":"true"}', False),
            (200, b'{"ok":false}', False), (200, b'[]', False),
            (200, b'{}', False), (200, b'not-json', False),
            (503, b'{"ok":true}', False), (204, b'', False)]
            for status, body, expected in cases:
                hits.clear()
                routes['/health'] = (status, body, {}, 0)
                with self.subTest(status=status, body=body):
                    self.assertIs(check(base + '/health', ping, timeout=.4), expected)
                    self.assertEqual(hits, ['/health', '/synthetic-ping-secret' + ('' if expected else '/fail')])

    def test_redirect_receivers(self):
        check = self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes), receiver() as (other, stolen, unused):
            with patch.dict(os.environ, {'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1'}):
                for status in (301, 302, 303, 307, 308):
                    routes['/health'] = (status, b'', {'Location': other + '/stolen-health'}, 0)
                    routes['/ping/fail'] = (status, b'', {'Location': other + '/stolen-ping-secret'}, 0)
                    self.assertIs(check(base + '/health', base + '/ping', timeout=.3), False)
                    routes['/health'] = (200, b'{"ok":true}', {}, 0)
                    routes['/ping'] = (status, b'', {'Location': other + '/stolen-ping-secret'}, 0)
                    self.assertIs(check(base + '/health', base + '/ping', timeout=.3), True)
                self.assertEqual(stolen, [])

    def test_failures_and_redaction(self):
        check = self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes), patch.dict(os.environ, {'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1'}):
            secret = '/synthetic-monitor-secret-Q7'
            routes['/health'] = (200, b'{"ok":true}', {}, .35)
            output = io.StringIO()
            with redirect_stderr(output), redirect_stdout(output):
                start = time.monotonic()
                self.assertIs(check(base + '/health', base + secret, timeout=.07), False)
                self.assertLess(time.monotonic() - start, 1.5)
                routes['/health'] = (200, b'{"ok":true}', {}, 0)
                routes[secret] = (500, b'private-body-secret', {}, 0)
                self.assertIs(check(base + '/health', base + secret, timeout=.2), True)
                # A bound non-listening local socket provides deterministic refusal.
                with socket.socket() as closed:
                    closed.bind(('127.0.0.1', 0))
                    dead = 'http://127.0.0.1:' + str(closed.getsockname()[1])
                    self.assertIs(check(dead + secret, base + secret, timeout=.2), False)
                    self.assertIs(check(base + '/health', dead + secret, timeout=.2), True)
            self.assertIn(secret + '/fail', hits)
            self.redacted(output.getvalue(), [base, secret, 'private-body-secret', dead])

    def test_timeout_cap(self):
        check = self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes), patch.dict(os.environ, {'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1'}):
            routes['/health'] = (200, b'{"ok":true}', {}, 6.5)
            start = time.monotonic()
            self.assertIs(check(base + '/health', base + '/ping', timeout=30), False)
            self.assertLess(time.monotonic() - start, 6.2)
            self.assertIn('/ping/fail', hits)

    def test_entrypoint_config(self):
        self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes):
            pingfile = private(self.base / 'ping', base + '/entry-secret')
            good = dict(ABG_HEALTH_URL=base + '/health', ABG_HC_PING_FILE=str(pingfile),
            ABG_MONITOR_ALLOW_LOCAL_HTTP='1', ABG_HEALTH_INTERVAL_SECONDS='.05')
            changes = [('ABG_HEALTH_INTERVAL_SECONDS', v) for v in ('0', '-1', 'nan', 'inf', 'oops')]
            changes += [('ABG_HC_PING_FILE', ''), ('ABG_HC_PING_FILE', str(self.base / 'missing')),
            ('ABG_HEALTH_URL', ''), ('ABG_MONITOR_ALLOW_LOCAL_HTTP', '0')]
            for key, value in changes:
                env = dict(good, **{key: value})
                self.reject_monitor(env, hits)
            for content in ('', 'http://remote.invalid/secret', 'https://u:p@host.invalid/secret',
            'https://host.invalid/p?q=secret', 'https://host.invalid/p#secret',
            'https://host.invalid', 'not-a-url'):
                private(pingfile, content)
                self.reject_monitor(good, hits)
            private(pingfile, base + '/entry-secret')
            for mode in (0o644, 0o640, 0o000):
                pingfile.chmod(mode)
                try:
                    self.reject_monitor(good, hits)
                finally:
                    pingfile.chmod(0o600)

    def reject_monitor(self, env, hits):
        proc = self.module('gateway.health_monitor', env, timeout=4)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(proc.stderr.strip())
        self.assertEqual(hits, [])
        self.redacted(proc.stdout + proc.stderr, [str(self.base), 'entry-secret', 'host.invalid', 'remote.invalid'])

    def test_loop(self):
        self.api('gateway.health_monitor', 'check_once')
        with receiver() as (base, hits, routes):
            routes['/health'] = (200, b'{"ok":true}', {}, 0)
            routes['/loop-secret'] = (503, b'', {}, 0)
            ping = private(self.base / 'ping', base + '/loop-secret\n')
            env = clean_env(ABG_HEALTH_URL=base + '/health', ABG_HC_PING_FILE=str(ping),
            ABG_HEALTH_INTERVAL_SECONDS='.05', ABG_MONITOR_ALLOW_LOCAL_HTTP='1')
            proc = subprocess.Popen([sys.executable, '-m', 'gateway.health_monitor'], cwd=ROOT,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 4
                while hits.count('/loop-secret') < 2 and time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(.02)
                self.assertGreaterEqual(hits.count('/loop-secret'), 2)
                routes['/health'] = (503, b'{"ok":true}', {}, 0)
                deadline = time.monotonic() + 4
                while hits.count('/loop-secret/fail') < 2 and time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(.02)
                self.assertGreaterEqual(hits.count('/loop-secret/fail'), 2)
                self.assertIsNone(proc.poll())
            finally:
                proc.terminate()  # our Docker child only
                try:
                    out, err = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, err = proc.communicate(timeout=3)
            self.assertEqual(hits[0], '/health')
            for index, path in enumerate(hits):
                if path.startswith('/loop-secret'):
                    self.assertGreater(index, 0)
                    self.assertEqual(hits[index - 1], '/health')
            self.redacted(out + err, [base, 'loop-secret', str(ping)])

class ProvisionProbe(ProbeCase):
    def provision(self, source, target):
        return self.script('abg-provision', ['--source', source, '--output', target,
                                              '--domain', 'example.net'])

    def test_fifteen_encoded_profiles(self):
        login, password = 'u@:/?#%é', 'p@:/?#%é$HOME'
        source = private(self.base / 'source',
            'IGNORED=anything\n PROXY_LOGIN = "' + login + '"\n'
            "PROXY_PASSWORD = '" + password + "'\n")
        target = self.base / 'profiles.toml'
        proc = self.provision(source, target)
        self.assertEqual(proc.returncode, 0, 'valid provision failed: ' + proc.stderr)
        self.assertTrue(target.is_file())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.stat().st_uid, os.getuid())
        profiles = tomllib.loads(target.read_text())['profile']
        self.assertEqual(set(profiles), {'ms' + str(i) for i in range(1, 16)})
        for i in range(1, 16):
            value = profiles['ms' + str(i)]['url']
            parts = urlsplit(value)
            self.assertEqual(parts.scheme, 'http')
            self.assertEqual(parts.hostname, 'ms' + str(i) + '.example.net')
            self.assertEqual(parts.port, 8126)
            self.assertEqual(unquote(parts.username), login)
            self.assertEqual(unquote(parts.password), password)
            self.assertEqual(parts.path, '')
            self.assertFalse(parts.query or parts.fragment)
            self.assertNotIn('@:/', value)
        self.assertIn('15', proc.stdout)
        self.redacted(proc.stdout + proc.stderr,
            [login, password, quote(login, safe=''), quote(password, safe='')])
        self.assertEqual({p.name for p in self.base.iterdir()}, {'source', 'profiles.toml'})

    def test_invalid_sources(self):
        target = self.base / 'out'
        source = self.base / 'source'
        cases = ['', 'PROXY_LOGIN=x', 'PROXY_PASSWORD=y',
            'PROXY_LOGIN=\nPROXY_PASSWORD=y', 'PROXY_LOGIN=""\nPROXY_PASSWORD=y',
            'PROXY_LOGIN=x\nPROXY_PASSWORD=x\nPROXY_LOGIN=y',
            'PROXY_LOGIN=x\nPROXY_PASSWORD=x\nPROXY_PASSWORD=y']
        for data in cases:
            private(source, data)
            proc = self.provision(source, target)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(target.exists())
            self.assertEqual({p.name for p in self.base.iterdir()}, {'source'})
        source.unlink()
        self.assertNotEqual(self.provision(source, target).returncode, 0)
        self.assertFalse(target.exists())

    def test_no_expansion_or_overwrite(self):
        marker = self.base / 'must-not-exist'
        secret = '$(touch ' + str(marker) + ')'
        source = private(self.base / 'source', 'PROXY_LOGIN=user\nPROXY_PASSWORD="' + secret + '"\n')
        target = self.base / 'target'
        proc = self.provision(source, target)
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(marker.exists())
        data = tomllib.loads(target.read_text())
        self.assertEqual(unquote(urlsplit(data['profile']['ms1']['url']).password), secret)
        before = (target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns)
        proc = self.provision(source, target)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual((target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns), before)
        target.unlink()
        victim = private(self.base / 'victim', 'preserve-existing-secret')
        target.symlink_to(victim)
        self.assertNotEqual(self.provision(source, target).returncode, 0)
        self.assertTrue(target.is_symlink())
        self.assertEqual(victim.read_text(), 'preserve-existing-secret')
        target.unlink()
        target.symlink_to(self.base / 'absent')
        self.assertNotEqual(self.provision(source, target).returncode, 0)
        self.assertFalse((self.base / 'absent').exists())
        self.assertTrue(target.is_symlink())
        self.redacted(proc.stdout + proc.stderr, [secret, str(marker)])

    def test_atomic_creation(self):
        sources = [private(self.base / ('s' + str(i)), 'PROXY_LOGIN=user\nPROXY_PASSWORD=p' + str(i) + '\n')
            for i in range(2)]
        target = self.base / 'out'
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.provision, s, target) for s in sources]
            results = [f.result(12) for f in futures]
        self.assertEqual(sum(p.returncode == 0 for p in results), 1)
        profiles = tomllib.loads(target.read_text())['profile']
        self.assertEqual(len(profiles), 15)
        self.assertEqual(len({urlsplit(p['url']).password for p in profiles.values()}), 1)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual({p.name for p in self.base.iterdir()}, {'s0', 's1', 'out'})
        self.assertNotEqual(Path('/tmp').stat().st_uid, os.getuid())
        forbidden = Path('/tmp') / (self.base.name + '-foreign-parent')
        try:
            proc = self.provision(sources[0], forbidden)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(forbidden.exists())
        finally:
            if forbidden.exists():
                forbidden.unlink()

# The contract explicitly permits canned git archive bytes inside Docker.
# This fake is an executable boundary, not a replacement of release internals.
FAKE_GIT = r'''#!/usr/local/bin/python3
import json, os, pathlib, sys
args = sys.argv[1:]
while args and args[0] in ('-C', '--git-dir', '--work-tree'):
    args = args[2:]
cmd, rest = args[0], args[1:]
sha = os.environ['PROBE_COMMIT']
archive = pathlib.Path(os.environ['PROBE_ARCHIVE'])
if cmd == 'archive':
    if not any(a == sha or a == sha + '^{commit}' for a in rest):
        sys.exit(2)
    output = next((a.split('=', 1)[1] for a in rest if a.startswith('--output=')), None)
    for flag in ('-o', '--output'):
        if flag in rest:
            output = rest[rest.index(flag) + 1]
    if output:
        pathlib.Path(output).write_bytes(archive.read_bytes())
    else:
        sys.stdout.buffer.write(archive.read_bytes())
elif cmd in ('rev-parse', 'cat-file'):
    if any(a == sha or a.startswith(sha + '^') for a in rest):
        if cmd == 'rev-parse':
            print(sha)
        elif '-t' in rest:
            print('commit')
    else:
        sys.exit(1)
elif cmd == 'ls-tree':
    rows = json.loads(os.environ['PROBE_TREE'])
    for name, mode in rows:
        row = name if '--name-only' in rest else mode + ' blob ' + 'b'*40 + '\t' + name
        sys.stdout.write(row + ('\0' if '-z' in rest else '\n'))
else:
    sys.stderr.write('unsupported probe git operation\n')
    sys.exit(3)
'''

class ReleaseProbe(ProbeCase):
    def setUp(self):
        super().setUp()
        self.sha = 'a' * 40
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        private(self.repo / 'data.txt', 'dirty checkout content')
        private(self.repo / 'untracked-secret', 'untracked-private-content')
        self.archive = self.base / 'archive.tar'
        self.files = {'data.txt': (b'committed bytes\n', 0o644),
            'bin/tool': (b'#!/bin/sh\nexit 0\n', 0o755)}
        self.make_archive()
        bindir = self.base / 'bin'
        bindir.mkdir()
        private(bindir / 'git', FAKE_GIT).chmod(0o700)
        self.env = clean_env(PATH=str(bindir) + os.pathsep + os.environ['PATH'],
            PROBE_COMMIT=self.sha, PROBE_ARCHIVE=str(self.archive),
            PROBE_TREE=json.dumps([(k, '100755' if v[1] == 0o755 else '100644')
            for k, v in self.files.items()]))
        self.root = self.base / 'delivery'

    def make_archive(self, extra=None):
        with tarfile.open(self.archive, 'w') as tar:
            for name, (data, mode) in self.files.items():
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), mode
                tar.addfile(member, io.BytesIO(data))
            if extra is not None:
                tar.addfile(extra, io.BytesIO(b'x') if extra.size else None)
        self.archive.chmod(0o600)

    def prepare(self, sha=None):
        return self.script('abg-release', ['prepare', '--repo', self.repo,
            '--sha', self.sha if sha is None else sha, '--root', self.root], env=self.env)

    def snapshot(self, path):
        return {str(p.relative_to(path)): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode),
            p.stat().st_mtime_ns, p.stat().st_ino)
            for p in path.rglob('*') if p.is_file()}

    def test_archive_and_repeat(self):
        proc = self.prepare()
        self.assertEqual(proc.returncode, 0, 'prepare failed: ' + proc.stderr)
        release = self.root / 'releases' / self.sha
        self.assertTrue(release.is_dir())
        self.assertEqual({str(p.relative_to(release)) for p in release.rglob('*') if p.is_file()}, set(self.files))
        for name, (data, mode) in self.files.items():
            self.assertEqual((release / name).read_bytes(), data)
            self.assertEqual(stat.S_IMODE((release / name).stat().st_mode), mode)
        for path in [release, *[p for p in release.rglob('*') if p.is_dir()]]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
        manifests = [p for p in self.root.rglob('*') if p.is_file() and release not in p.parents]
        self.assertTrue(manifests)
        content = b'\n'.join(p.read_bytes() for p in manifests)
        for name, (data, mode) in self.files.items():
            self.assertIn(hashlib.sha256(data).hexdigest().encode(), content)
            self.assertIn(name.encode(), content)
        before = self.snapshot(release)
        proc = self.prepare()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.snapshot(release), before)
        self.assertFalse((self.root / 'active').exists())
        self.redacted(proc.stdout + proc.stderr, ['untracked-private-content'])

    def test_mismatch(self):
        self.assertEqual(self.prepare().returncode, 0)
        release = self.root / 'releases' / self.sha
        path = release / 'data.txt'
        for alteration in ('content', 'mode', 'extra'):
            with self.subTest(alteration=alteration):
                if alteration == 'content':
                    path.write_bytes(b'foreign content')
                elif alteration == 'mode':
                    path.chmod(0o600)
                else:
                    private(release / 'foreign', 'keep')
                before = self.snapshot(release)
                proc = self.prepare()
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(self.snapshot(release), before)
                path.write_bytes(self.files['data.txt'][0])
                path.chmod(0o644)
                if (release / 'foreign').exists():
                    (release / 'foreign').unlink()

    def test_unsafe_release(self):
        for sha in ('HEAD', 'main', 'a' * 7, '../bad', 'g' * 40, 'b' * 40):
            self.assertNotEqual(self.prepare(sha).returncode, 0)
        self.assertFalse((self.root / 'releases' / self.sha).exists())
        for name, kind in (('../escape', tarfile.REGTYPE), ('/tmp/escape', tarfile.REGTYPE),
            ('link', tarfile.SYMTYPE), ('hard', tarfile.LNKTYPE)):
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = '../outside' if kind != tarfile.REGTYPE else ''
            info.size = 1 if kind == tarfile.REGTYPE else 0
            self.make_archive(info)
            self.assertNotEqual(self.prepare().returncode, 0)
            self.assertFalse((self.root / 'releases' / self.sha).exists())
        self.make_archive()
        victim = self.base / 'victim'
        victim.mkdir()
        private(victim / 'keep', 'keep-me')
        releases = self.root / 'releases'
        releases.mkdir(parents=True, exist_ok=True)
        (releases / self.sha).symlink_to(victim, target_is_directory=True)
        self.assertNotEqual(self.prepare().returncode, 0)
        self.assertTrue((releases / self.sha).is_symlink())
        self.assertEqual({p.name for p in victim.iterdir()}, {'keep'})
        self.assertEqual((victim / 'keep').read_text(), 'keep-me')

if __name__ == '__main__':
    unittest.main()
