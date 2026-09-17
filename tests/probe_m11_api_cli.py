"""Independent M11 public-contract probe; stdlib, local stands, no Docker daemon.

Run inside the contract's pinned Python Docker image as 1002:1002:
python3 -m tests.probe_m11_api_cli
python3 -m unittest -q tests.probe_m11_api_cli
"""
import contextlib
from dataclasses import replace
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from bench.escalate import Step
from bench.models import ChallengeType as C, FailureReason as F, FetchResult
from gateway.models import Attempt, GatewayOutcome, PlanStep, ProviderReply

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://origin.invalid/start'
FINAL = 'https://final.invalid/dir/page'
TOKEN = 'probe-token-ONLY'
SECRET = 'private-marker-7d9a'
MODES = ('text', 'html', 'markdown', 'links', 'meta')
PAGE = '''<html lang="ru"><head><title>A &amp; B</title>
<meta property="og:description" content="fallback"><meta name="description" content="chosen">
<meta property="og:title" content="OG"><meta property="og:image" content="https://img.invalid/i">
<link rel="canonical" href="../canon"></head><body><h1>Top <em>nested</em></h1>
<h2>Second</h2><p>Visible <strong>bold</strong> and <em>soft</em> &amp; entity<br>Next</p>
<ul><li>Item</li></ul><blockquote>Quote</blockquote><pre>preformatted</pre><code>codeword</code>
<a href="child"><span>deep</span> &amp; label</a><a href="/root">Root</a>
<a href="child">again</a><a href="https://absolute.invalid/article">Absolute link</a><a href="mailto:a@b">Mail</a><a href="javascript:bad()">JS</a>
<img alt="Picture" src="/pic"><script>HIDDEN_SCRIPT</script><style>HIDDEN_STYLE</style>
<nav><a href="/nav">HIDDEN_NAV</a></nav><header><h1>HIDDEN_HEADER</h1></header><footer>HIDDEN_FOOTER</footer>
<noscript>HIDDEN_NOSCRIPT</noscript><iframe>HIDDEN_IFRAME</iframe><svg>HIDDEN_SVG</svg></body></html>'''


def reply(provider='curl_cffi', **kw):
    values = dict(provider=provider, provider_version='probe', requested_url=URL,
                  final_url=FINAL, status=200, html=PAGE, text='Visible русский',
                  elapsed_ms=7, startup_ms=0, cpu_ms=0, peak_rss_mb=0,
                  bytes_received=12, redirects=1, error_type=F.none, challenge=C.none)
    values.update(kw)
    return ProviderReply(FetchResult(**values), 1.5)


def outcome(ok=True):
    return GatewayOutcome(ok, URL, FINAL, PAGE, 'Visible русский', 'curl_cffi', 1.5,
                          F.none if ok else F.http_403, Step.stop if ok else Step.human,
                          (Attempt('curl_cffi', 'edge', ok, F.none, C.none, 200, 7, 1.5, Step.stop),), 9)


def envelope(mode='text', content='selected', ok=True):
    return dict(ok=ok, url=URL, final_url=FINAL, format=mode, content=content,
                provider='curl_cffi', age_hours=None, error_type='none' if ok else 'http_403',
                step='stop' if ok else 'human', elapsed_ms=9, attempts=[])


@contextlib.contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def request(address, data=None, *, path='/v1/fetch', method='POST', auth=TOKEN,
            body=None, headers=None):
    payload = json.dumps(data if data is not None else {'url': URL}).encode() if body is None else body
    h = {'Content-Type': 'application/json; charset=utf-8'}
    if auth is not None:
        h['Authorization'] = 'Bearer ' + auth
    h.update(headers or {})
    conn = http.client.HTTPConnection(*address, timeout=8)
    try:
        conn.request(method, path, payload, h)
        response = conn.getresponse()
        raw = response.read()
        return response.status, dict(response.getheaders()), raw
    finally:
        conn.close()


class Public(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module('gateway.httpapi')
        except ModuleNotFoundError as exc:
            if exc.name != 'gateway.httpapi':
                raise
            self.fail('M11 public API absent: gateway.httpapi (BASE M10 imports succeeded)')

    def renderer(self):
        try:
            return importlib.import_module('gateway.format').render_content
        except ModuleNotFoundError as exc:
            if exc.name != 'gateway.format':
                raise
            self.fail('M11 formatter absent: gateway.format (BASE M10 imports succeeded)')

    def json_response(self, result, status, payload=None):
        code, headers, raw = result
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual(code, status)
        self.assertEqual(headers.get('content-type', '').split(';')[0], 'application/json')
        self.assertEqual(int(headers['content-length']), len(raw))
        parsed = json.loads(raw.decode('utf-8'))
        if payload is not None:
            self.assertEqual(parsed, payload)
        return parsed

    def server(self, factory=None, **kw):
        return self.api().make_server(('127.0.0.1', 0), token=TOKEN,
                                     fetcher_factory=factory or (lambda *a, **k: lambda s, b: reply(s.provider)), **kw)


class API(Public):
    def test_config_rejected_before_bind(self):
        api = self.api()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            for key, values in {'token': ['', None, 12, 'a b', 'a\n', 'é', '\x7f'],
                                'browser_limit': [0, -1, True, 1.2, '2']}.items():
                for value in values:
                    with self.subTest(key=key, value=value):
                        args = dict(token=TOKEN, browser_limit=1)
                        args[key] = value
                        with self.assertRaises(ValueError) as error:
                            api.make_server(occupied.getsockname(), **args)
                        self.assertNotIn(TOKEN, str(error.exception))
            for address in [('', 0), ('x', True), ('x', -1), ('x', 65536), ('x', '1'), ('x',), None]:
                with self.subTest(address=address), self.assertRaises(ValueError):
                    api.make_server(address, token=TOKEN)

    def test_auth_health_routes_and_no_factory(self):
        calls = []
        def factory(*a, **k):
            calls.append(a)
            return lambda s, b: reply(s.provider)
        with serving(self.server(factory)) as addr:
            self.json_response(request(addr, method='GET', path='/health', auth=None), 200, {'ok': True})
            for token in [None, '', 'wrong', TOKEN + 'x']:
                self.json_response(request(addr, auth=token), 401, {'error': 'unauthorized'})
            for method, path, status in [('GET', '/v1/fetch', 405), ('POST', '/health', 405),
                                         ('PUT', '/health', 405), ('TRACE', '/health', 405), ('BREW', '/v1/fetch', 405),
                                         ('GET', '/missing', 404)]:
                self.assertEqual(request(addr, method=method, path=path)[0], status)
        self.assertEqual(calls, [], 'auth and health must precede factory')

    def test_invalid_json_schema_framing(self):
        calls = []
        def factory(*a, **k):
            calls.append(a)
            return lambda s, b: reply(s.provider)
        invalid = [b'[]', b'null', b'{', b'\xff', b'{"url":"https://x","url":"https://y"}',
                   b'{"url":"https://x","max_age_hours":NaN}',
                   b'{"url":"https://x","max_age_hours":Infinity}',
                   b'{"url":"https://x","max_age_hours":-Infinity}']
        fields = {'url': [None, 1, '', 'file:///x', 'https://u:p@x', 'https://x:0', ' https://x'],
                  'budget_ms': [True, 0, -1, 180001, 1.2, '3', None],
                  'max_age_hours': [True, -1, '2', None, 1e309],
                  'allow_browser': [0, 'true', None], 'expected_text': ['', '  ', 1, False],
                  'format': ['unknown', None, 1], 'provider': ['curl'], 'token': [SECRET],
                  'profiles': [{}], 'proxy_url': [SECRET], 'docker_options': [[]]}
        invalid.append(b'{}')
        for key, values in fields.items():
            invalid.extend(json.dumps(dict(url=URL, **{key: value}) if key != 'url' else {'url': value}).encode()
                           for value in values)
        with serving(self.server(factory)) as addr:
            for body in invalid:
                with self.subTest(body=body):
                    self.json_response(request(addr, body=body), 400, {'error': 'invalid_request'})
            self.json_response(request(addr, headers={'Content-Type': 'text/plain'}), 400,
                               {'error': 'invalid_request'})
            cases = [('Content-Length: -1\r\n', b''), ('Content-Length: bad\r\n', b''),
                     ('', b''), ('Content-Length: 2\r\nContent-Length: 2\r\n', b'{}'),
                     ('Content-Length: 2\r\nTransfer-Encoding: chunked\r\n', b'{}'),
                     ('Content-Length: 65537\r\n', b''), ('Content-Length: 10\r\n', b'{}')]
            for framing, body in cases:
                with self.subTest(framing=framing), socket.create_connection(addr, timeout=8) as sock:
                    wire = ('POST /v1/fetch HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer ' +
                            TOKEN + '\r\nContent-Type: application/json\r\n' + framing + '\r\n').encode() + body
                    sock.sendall(wire)
                    # Last case stays open: bounded read must reply without EOF.
                    response = http.client.HTTPResponse(sock)
                    response.begin()
                    self.assertEqual(response.status, 400)
                    self.assertEqual(json.loads(response.read()), {'error': 'invalid_request'})
        self.assertEqual(calls, [], 'invalid request reached factory')

    def test_body_bound_inclusive(self):
        body = json.dumps({'url': URL}).encode()
        with serving(self.server()) as addr:
            self.assertTrue(self.json_response(request(addr, body=body.ljust(65536)), 200)['ok'])
            self.json_response(request(addr, body=body.ljust(65537)), 400, {'error': 'invalid_request'})

    def test_serialization_copies_and_profile_order(self):
        seen = []
        profiles = {'first': 'http://u:' + SECRET + '@proxy.invalid', 'second': ''}
        entrances = {'rss': 'https://feed.invalid/rss'}
        def factory(url, *, entrances, profiles):
            seen.append((url, dict(entrances), dict(profiles)))
            def fetch(step, budget):
                seen.append((step.provider, step.egress_profile))
                return reply(step.provider, status=429 if step.egress_profile == 'direct' else 200,
                             error_type=F.not_measured if step.egress_profile == 'first' else F.none)
            return fetch
        server = self.server(factory, profiles=profiles, entrances=entrances)
        profiles.clear()
        entrances.clear()
        with serving(server) as addr:
            result = self.json_response(request(addr), 200)
        self.assertEqual(seen[0], (URL, {'rss': 'https://feed.invalid/rss'},
                                  {'first': 'http://u:' + SECRET + '@proxy.invalid', 'second': ''}))
        self.assertEqual(seen[1:], [('curl_cffi', 'direct'), ('curl_cffi', 'first'), ('curl_cffi', 'second')])
        wanted = envelope(content='Visible русский')
        wanted.update(age_hours=1.5)
        for key in wanted.keys() - {'attempts', 'elapsed_ms'}:
            self.assertEqual(result[key], wanted[key], key)
        self.assertIs(type(result['elapsed_ms']), int)
        self.assertGreaterEqual(result['elapsed_ms'], 0)
        expected = [dict(provider='curl_cffi', egress_profile='direct', success=False, error_type='http_429',
                         challenge='none', status=429, elapsed_ms=7, age_hours=1.5, next_step='change_egress'),
                    dict(provider='curl_cffi', egress_profile='first', success=False, error_type='not_measured',
                         challenge='none', status=200, elapsed_ms=7, age_hours=1.5, next_step=None),
                    dict(provider='curl_cffi', egress_profile='second', success=True, error_type='none',
                         challenge='none', status=200, elapsed_ms=7, age_hours=1.5, next_step='stop')]
        self.assertEqual(result['attempts'], expected)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn('<html', json.dumps(result))

    def test_success_modes_and_failed_human(self):
        for ok in (True, False):
            def factory(*a, **k):
                return lambda s, b: reply(s.provider, challenge=C.none if ok else C.interactive)
            with serving(self.server(factory)) as addr:
                for mode, typ, empty in [('text', str, ''), ('html', str, ''), ('markdown', str, ''),
                                         ('links', list, []), ('meta', dict, {})]:
                    with self.subTest(ok=ok, mode=mode):
                        value = self.json_response(request(addr, {'url': URL, 'format': mode}), 200)
                        self.assertIs(value['ok'], ok)
                        self.assertIs(type(value['content']), typ)
                        if ok:
                            self.assertTrue(value['content'])
                        else:
                            self.assertEqual(value['content'], empty, 'failed outcome body leaked')
                            self.assertEqual(value['step'], 'human')
                            self.assertEqual(value['attempts'][0]['challenge'], 'interactive')
                            self.assertEqual(value['attempts'][0]['error_type'], 'interactive_challenge')

    def test_options_reach_m10_policy(self):
        cases = [({'budget_ms': 321}, True, ['curl_cffi']),
                 ({'expected_text': 'absent', 'allow_browser': False}, False, ['curl_cffi']),
                 ({'max_age_hours': 2}, True, ['rss']),
                 ({'allow_browser': False}, False, ['curl_cffi']),
                 ({'allow_browser': True}, True, ['curl_cffi', 'patchright'])]
        for index, (options, ok, providers) in enumerate(cases):
            calls = []
            def factory(*a, **k):
                def fetch(step, budget):
                    calls.append((step.provider, budget))
                    return reply(step.provider, status=403 if index >= 3 and step.provider == 'curl_cffi' else 200)
                return fetch
            with self.subTest(options=options), serving(self.server(factory)) as addr:
                value = self.json_response(request(addr, {'url': URL, **options}), 200)
                self.assertIs(value['ok'], ok, 'API dropped an M10 option')
                self.assertEqual([provider for provider, budget in calls], providers, 'API options did not reach M10 policy')
                if index == 0:
                    self.assertTrue(0 < calls[0][1] <= 321, 'API dropped budget_ms')
                if not ok:
                    self.assertEqual(value['content'], '')

    def test_browser_limit_two(self):
        entered = [threading.Event(), threading.Event()]
        release, done = threading.Event(), threading.Event()
        results, calls, errors = {}, [], []
        def factory(url, **kw):
            def fetch(step, budget):
                if step.provider == 'curl_cffi':
                    return reply('curl_cffi', status=403)
                calls.append(url)
                if url.endswith('/0') or url.endswith('/1'):
                    entered[int(url[-1])].set()
                    release.wait(5)
                return reply(step.provider)
            return fetch
        with serving(self.server(factory, browser_limit=2)) as addr:
            def worker(index):
                try:
                    results[index] = request(addr, {'url': URL + '/' + str(index),
                                                   'budget_ms': 160 if index == 2 else 4000})
                except Exception as exc:
                    errors.append(type(exc).__name__)
                finally:
                    if index == 2:
                        done.set()
            threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(3)]
            try:
                for thread in threads[:2]:
                    thread.start()
                self.assertTrue(all(event.wait(2) for event in entered), 'browser_limit=2 did not admit two browsers')
                threads[2].start()
                self.assertTrue(done.wait(2), 'third request did not finish bounded acquire')
                self.assertNotIn(URL + '/2', calls, 'third browser exceeded configured limit')
                value = self.json_response(results[2], 200)
                self.assertFalse(value['ok'])
                self.assertEqual(value['error_type'], 'timeout')
            finally:
                release.set()
                for thread in threads:
                    if thread.ident:
                        thread.join(5)
            self.assertEqual(errors, [])
            for index in (0, 1):
                self.assertTrue(self.json_response(results[index], 200)['ok'])

    def test_static_exception(self):
        def factory(*a, **k):
            raise RuntimeError(SECRET)
        output = io.StringIO()
        with contextlib.redirect_stderr(output), serving(self.server(factory)) as addr:
            self.json_response(request(addr), 500, {'error': 'internal_error'})
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())

    def test_global_slots_health_http_and_exception_release(self):
        entered, release, second_done, exited = (threading.Event() for _ in range(4))
        calls, results, errors = [], {}, []
        def factory(url, **kw):
            def fetch(step, budget):
                calls.append((url, step.provider))
                if url.endswith('/http'):
                    return reply(step.provider)
                if step.provider == 'curl_cffi' or (url.endswith('/hold') and step.provider == 'patchright'):
                    return reply(step.provider, status=403)
                if url.endswith('/hold'):
                    entered.set()
                    release.wait(5)
                    exited.set()
                    raise RuntimeError(SECRET)
                return reply(step.provider)
            return fetch
        with serving(self.server(factory)) as addr:
            def worker(name, budget):
                try:
                    results[name] = request(addr, {'url': URL + '/' + name, 'budget_ms': budget})
                except Exception as exc:
                    errors.append(type(exc).__name__)
                finally:
                    if name == 'second':
                        second_done.set()
            first = threading.Thread(target=worker, args=('hold', 4000), daemon=True)
            second = threading.Thread(target=worker, args=('second', 160), daemon=True)
            first.start()
            try:
                self.assertTrue(entered.wait(3), 'first browser did not enter')
                second.start()
                self.json_response(request(addr, method='GET', path='/health', auth=None), 200, {'ok': True})
                bypass = self.json_response(request(addr, {'url': URL + '/http', 'allow_browser': False}), 200)
                self.assertTrue(bypass['ok'], 'HTTP waited for browser slot')
                self.assertFalse(exited.is_set(), 'health/HTTP queued behind occupied browser slot')
                self.assertTrue(second_done.wait(3), 'browser acquire must be finite')
                self.assertNotIn((URL + '/second', 'patchright'), calls, 'browser semaphore is not global')
                value = self.json_response(results['second'], 200)
                self.assertFalse(value['ok'])
                self.assertEqual(value['error_type'], 'timeout')
                self.assertIsNone(value['attempts'][-1]['status'])
            finally:
                release.set()
                first.join(5)
                if second.ident:
                    second.join(5)
            self.assertEqual(errors, [])
            self.json_response(results['hold'], 500, {'error': 'internal_error'})
            recovered = self.json_response(request(addr, {'url': URL + '/after', 'budget_ms': 500}), 200)
            self.assertTrue(recovered['ok'], 'exception leaked the global slot')


class Limiter(Public):
    def test_budget_rounding_timeout_and_http_bypass(self):
        limit = self.api().limit_fetcher
        for provider in ('patchright', 'scrapling'):
            for wait, acquired in [(25.4, True), (99.7, True), (100, True), (50, False)]:
                with self.subTest(provider=provider, wait=wait, acquired=acquired):
                    now, calls, acquires, releases = [10.0], [], [], []
                    class Gate:
                        def acquire(self, blocking=True, timeout=None):
                            acquires.append(timeout)
                            now[0] += wait
                            return acquired
                        def release(self):
                            releases.append(True)
                    step = PlanStep(provider, 'direct', 'browser')
                    inner = lambda s, b: calls.append((s, b)) or reply(s.provider)
                    result = limit(inner, Gate(), url=URL, clock=lambda: now[0])(step, 100)
                    self.assertEqual(len(acquires), 1)
                    self.assertIsNotNone(acquires[0])
                    self.assertTrue(math.isfinite(acquires[0]))
                    self.assertGreater(acquires[0], 0)
                    self.assertLessEqual(acquires[0], .1)
                    self.assertEqual(len(releases), int(acquired), 'slot must be released')
                    if acquired and wait == 25.4:
                        self.assertEqual(calls, [(step, 74)], 'browser wait budget was reset')
                        self.assertEqual(result.result.status, 200)
                    else:
                        self.assertEqual(calls, [], 'zero/expired budget called inner fetcher')
                        r = result.result
                        self.assertEqual((r.provider, r.requested_url, r.final_url, r.error_type, r.status,
                                          r.challenge, r.html, r.text, result.age_hours),
                                         (provider, URL, URL, F.timeout, None, C.none, '', '', None))
                        self.assertAlmostEqual(r.elapsed_ms, wait, delta=1)
                        self.assertEqual((r.startup_ms, r.cpu_ms, r.peak_rss_mb, r.bytes_received, r.redirects),
                                         (0, 0, 0, 0, 0))
        actions = []
        class NoGate:
            def acquire(self, *a, **k):
                actions.append('acquire')
                return True
            def release(self):
                actions.append('release')
        for provider in ('curl_cffi', 'rss', 'wayback'):
            calls = []
            step = PlanStep(provider, 'direct', 'entrance' if provider != 'curl_cffi' else 'http')
            limit(lambda s, b: calls.append((s, b)) or reply(s.provider), NoGate(), url=URL)(step, 123)
            self.assertEqual(calls, [(step, 123)])
        self.assertEqual(actions, [], 'HTTP/entrances acquired browser slot')

    def test_release_on_exception(self):
        limit = self.api().limit_fetcher
        gate = threading.BoundedSemaphore(1)
        def broken(s, b):
            raise RuntimeError(SECRET)
        step = PlanStep('scrapling', 'direct', 'browser')
        with self.assertRaises(RuntimeError):
            limit(broken, gate, url=URL)(step, 100)
        free = gate.acquire(blocking=False)
        self.assertTrue(free, 'exception leaked semaphore slot')
        if free:
            gate.release()


class Formats(Public):
    def test_formats_nested_links_meta_and_no_failed_body(self):
        render = self.renderer()
        good = outcome()
        self.assertEqual(render(good, 'text'), good.text)
        self.assertEqual(render(good, 'html'), PAGE)
        for mode, empty in zip(MODES, ('', '', '', [], {})):
            self.assertEqual(render(outcome(False), mode), empty, 'failed outcome body leaked')
        with self.assertRaises(ValueError):
            render(good, SECRET)
        links = render(good, 'links')
        self.assertEqual(links, [{'text': 'deep & label', 'href': 'https://final.invalid/dir/child'},
                                 {'text': 'Root', 'href': 'https://final.invalid/root'},
                                 {'text': 'again', 'href': 'https://final.invalid/dir/child'},
                                 {'text': 'Absolute link', 'href': 'https://absolute.invalid/article'},
                                 {'text': 'HIDDEN_NAV', 'href': 'https://final.invalid/nav'}])
        long = replace(good, html='<a href="//else.invalid/a">' + 'x' * 120 + '</a><a href="/empty"></a>')
        self.assertEqual(render(long, 'links'), [{'text': 'x' * 100, 'href': 'https://else.invalid/a'},
                                               {'text': '', 'href': 'https://final.invalid/empty'}])
        md = render(good, 'markdown')
        for word in ('Top', 'nested', 'Second', 'Visible', 'bold', 'soft', '&', 'entity',
                     'Next', 'Item', 'Quote', 'preformatted', 'codeword', 'deep', 'label', 'Picture'):
            self.assertIn(word, md, 'nested visible markdown text lost')
        self.assertNotIn('HIDDEN_', md)
        self.assertNotIn('&amp;', md)
        for expression in (r'(?m)(^\s*#\s+Top|^Top[^\n]*\n=+)', r'(?m)(^\s*##\s+Second|^Second[^\n]*\n-+)', r'(\*\*bold\*\*|__bold__)',
                           r'(\*soft\*|_soft_)', r'`codeword`', r'(?m)^\s*>\s*Quote',
                           r'(?m)^\s*(?:[-+*]|\d+[.)])\s+Item', r'\[Absolute link\]\(https://absolute.invalid/article\)'):
            self.assertRegex(md, expression)
        self.assertRegex(md, r'!\[Picture\]\((?:https://final.invalid)?/pic\)')
        self.assertRegex(md, r'(?m)(^\s*(?:```|~~~)|^ {4}preformatted)')
        self.assertEqual(render(good, 'meta'), dict(title='A & B', description='chosen', ogTitle='OG',
                         ogImage='https://img.invalid/i', canonical='https://final.invalid/canon',
                         h1=['Top nested', 'HIDDEN_HEADER'], lang='ru'))
        self.assertEqual(render(replace(good, html='<meta property="og:description" content="fallback">'), 'meta'),
                         dict(title='', h1=[], description='fallback'))
        self.assertEqual(good, outcome(), 'formatter mutated outcome')


@contextlib.contextmanager
def stand(payload, status=200, location=None):
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            hits.append((self.path, self.headers.get('Authorization'), body))
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            if location:
                self.send_header('Location', location)
            self.end_headers()
            self.wfile.write(raw)
        do_GET = do_POST
        def log_message(self, *a):
            pass
    with serving(ThreadingHTTPServer(('127.0.0.1', 0), Handler)) as addr:
        yield 'http://%s:%s/v1/fetch' % addr, hits


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_') and
           k not in ('PYTHONPATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')}
    env.update(extra)
    return env


class CLI(Public):
    def client(self, args, env):
        source = ROOT / 'gateway/client.py'
        self.assertTrue(source.is_file(), 'M11 standalone client absent: gateway/client.py')
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'client.py'
            shutil.copyfile(source, target)
            return subprocess.run([sys.executable, str(target), *args], cwd=tmp,
                                  env=clean_env(**env), capture_output=True, text=True, timeout=8)

    def failure(self, proc):
        self.assertNotEqual(proc.returncode, 0, 'CLI accepted failed response/config')
        self.assertEqual(proc.stdout, '', 'CLI failure leaked body on stdout')
        error = json.loads(proc.stderr)
        self.assertIsInstance(error, dict)
        self.assertIsInstance(error.get('error'), str)
        self.assertTrue(error['error'])
        self.assertNotIn(SECRET, proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)
        self.assertNotIn(TOKEN, proc.stderr)

    def test_one_request_selected_content_auth_and_env(self):
        for mode, content in [('text', 'русский'), ('html', '<b>ok</b>'), ('markdown', '**ok**'),
                              ('links', [{'text': 'L', 'href': FINAL}]), ('meta', {'title': 'T', 'h1': []})]:
            with self.subTest(mode=mode), stand(envelope(mode, content)) as (url, hits):
                proc = self.client([URL, mode], dict(ABG_URL=url, ABG_TOKEN=TOKEN, ABG_BUDGET_MS='1234',
                                   ABG_MAX_AGE_HOURS='2.5', ABG_ALLOW_BROWSER='0', ABG_EXPECTED_TEXT='found'))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stderr, '')
                self.assertEqual(json.loads(proc.stdout) if mode in ('links', 'meta') else proc.stdout.rstrip('\n'), content)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0][:2], ('/v1/fetch', 'Bearer ' + TOKEN))
                self.assertEqual(json.loads(hits[0][2]), dict(url=URL, format=mode, budget_ms=1234,
                                 max_age_hours=2.5, allow_browser=False, expected_text='found'))
        with stand(envelope()) as (url, hits):
            proc = self.client([URL], dict(ABG_URL=url, ABG_TOKEN=TOKEN))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            defaults = dict(format='text', budget_ms=30000, max_age_hours=0, allow_browser=True, expected_text=None)
            self.assertEqual(defaults | json.loads(hits[0][2]), defaults | {'url': URL})

        with stand(envelope()) as (url, hits):
            original = URL + '/a b'
            proc = self.client([original], dict(ABG_URL=url, ABG_TOKEN=TOKEN))
            self.assertEqual(proc.returncode, 0, 'client tightened BASE URL validation: ' + proc.stderr)
            self.assertEqual(len(hits), 1)
            self.assertEqual(json.loads(hits[0][2])['url'], original)

    def test_failed_invalid_responses_and_redirect(self):
        bad = [envelope(content=SECRET, ok=False), b'raw-' + SECRET.encode(), [], {},
               envelope(content=[]), envelope(mode='html'), dict(envelope(), ok='true'), dict(envelope(), elapsed_ms=True),
               dict(envelope(), attempts={}), dict(envelope(), provider=12),
               dict(envelope(), age_hours='2'), dict(envelope(), error_type=SECRET)]
        for payload in bad:
            with self.subTest(payload=payload), stand(payload) as (url, hits):
                self.failure(self.client([URL], dict(ABG_URL=url, ABG_TOKEN=TOKEN)))
                self.assertEqual(len(hits), 1)
        with stand(envelope()) as (receiver, received):
            with stand({'error': SECRET}, status=302, location=receiver) as (url, sent):
                proc = self.client([URL], dict(ABG_URL=url, ABG_TOKEN=TOKEN))
                self.assertEqual(len(sent), 1)
                self.assertEqual(received, [], 'CLI followed redirect / forwarded Bearer')
                self.failure(proc)
        with stand({'error': SECRET}, status=500) as (url, hits):
            self.failure(self.client([URL], dict(ABG_URL=url, ABG_TOKEN=TOKEN)))
            self.assertEqual(len(hits), 1)
        self.failure(self.client([URL], dict(ABG_URL='http://127.0.0.1:0/' + SECRET, ABG_TOKEN=TOKEN)))

    def test_bad_config_and_token_file(self):
        with stand(envelope()) as (url, hits):
            base = dict(ABG_URL=url, ABG_TOKEN=TOKEN)
            for args in ([], [URL, 'text', 'extra'], [URL, 'bad'], ['file:///x']):
                self.failure(self.client(args, base))
            for key, values in {'ABG_BUDGET_MS': ['0', '180001', 'x'], 'ABG_MAX_AGE_HOURS': ['nan', '-1'],
                                'ABG_ALLOW_BROWSER': ['true', '2'], 'ABG_EXPECTED_TEXT': [' ', '']}.items():
                for value in values:
                    with self.subTest(key=key, value=value):
                        self.failure(self.client([URL], dict(base, **{key: value})))
            self.assertEqual(hits, [], 'invalid client config made an HTTP request')
            with tempfile.TemporaryDirectory() as tmp:
                token = Path(tmp) / 'token'
                token.write_text(TOKEN + '\n')
                proc = self.client([URL], dict(ABG_URL=url, ABG_TOKEN_FILE=str(token)))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(hits[-1][1], 'Bearer ' + TOKEN)
                proc = self.client([URL], dict(base, ABG_TOKEN_FILE='/missing/' + SECRET))
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_wrapper_symlink_mount_env_and_default_home(self):
        wrapper = ROOT / 'scripts/abg-fetch'
        self.assertTrue(wrapper.is_file(), 'M11 Docker wrapper absent: scripts/abg-fetch')
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / '.config/abg').mkdir(parents=True)
            token = home / '.config/abg/client-token'
            token.write_text(TOKEN)
            fake = home / 'docker'
            record = home / 'argv.json'
            fake.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                            'json.dump({"argv":sys.argv[1:],"env":{k:v for k,v in os.environ.items() '
                            'if k.startswith("ABG_")}},open(os.environ["PROBE_RECORD"],"w"))\n')
            fake.chmod(0o755)
            link = home / 'abg-fetch'
            link.symlink_to(wrapper)
            for via_file in (False, True):
                env = clean_env(HOME=str(home), PATH=str(home) + ':' + os.environ['PATH'], PROBE_RECORD=str(record),
                                ABG_URL='http://127.0.0.1:8765/v1/fetch', ABG_BUDGET_MS='123',
                                ABG_MAX_AGE_HOURS='2', ABG_ALLOW_BROWSER='0', ABG_EXPECTED_TEXT='needle')
                if not via_file:
                    env['ABG_TOKEN'] = TOKEN
                proc = subprocess.run([str(link), URL, 'meta'], env=env, cwd=tmp, capture_output=True, text=True, timeout=5)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                data = json.loads(record.read_text())
                argv = data['argv']
                self.assertNotIn(TOKEN, '\n'.join(argv), 'token value leaked in Docker argv')
                options, mounts, forwarded = {}, [], []
                i = 0
                while i < len(argv):
                    arg = argv[i]
                    name, sep, value = arg.partition('=')
                    if name in ('--user', '-u', '--network', '--mount', '--volume', '-v', '--env', '-e'):
                        if not sep:
                            i += 1
                            value = argv[i]
                        options[name] = value
                        if name in ('--mount', '--volume', '-v'):
                            mounts.append(value)
                        if name in ('--env', '-e'):
                            forwarded.append(value)
                    i += 1
                self.assertEqual(options.get('--user', options.get('-u')), '1002:1002')
                self.assertEqual(options.get('--network'), 'host')
                self.assertIn('python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6', argv)
                self.assertEqual(argv[-2:], [URL, 'meta'])
                self.assertFalse(any('docker.sock' in m for m in mounts))
                for mount in mounts:
                    self.assertTrue('readonly' in mount or mount.endswith(':ro'), 'mount must be read-only')
                    self.assertTrue(str(ROOT / 'gateway/client.py') in mount or str(token) in mount, 'unexpected mount')
                self.assertTrue(any(str(ROOT / 'gateway/client.py') in m for m in mounts), 'standalone client not mounted')
                for key in ('ABG_URL', 'ABG_BUDGET_MS', 'ABG_MAX_AGE_HOURS', 'ABG_ALLOW_BROWSER', 'ABG_EXPECTED_TEXT'):
                    self.assertTrue(key in forwarded or key + '=' + env[key] in forwarded, key)
                if via_file:
                    self.assertTrue(any(str(token) in m for m in mounts), 'default host HOME token was not mounted')
                else:
                    self.assertIn('ABG_TOKEN', forwarded)
                    self.assertEqual(data['env'].get('ABG_TOKEN'), TOKEN)

    def test_module_bootstrap_token_priority_and_fail_closed(self):
        self.api()
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, '-m', 'gateway.httpapi'], cwd=ROOT,
                                  env=clean_env(HOME=tmp), capture_output=True, text=True, timeout=5)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, '')
            self.assertTrue(proc.stderr.strip())
            self.assertNotIn('Traceback', proc.stderr)
            for file_mode in (False, True):
                token = Path(tmp) / 'token'
                token.write_text(TOKEN + '\n')
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                env = clean_env(ABG_BIND='127.0.0.1', ABG_PORT=str(port), ABG_BROWSER_LIMIT='2',
                                ABG_TOKEN_FILE=str(token) if file_mode else '/missing/' + SECRET)
                if not file_mode:
                    env['ABG_TOKEN'] = TOKEN
                child = subprocess.Popen([sys.executable, '-m', 'gateway.httpapi'], cwd=ROOT, env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline, started = time.monotonic() + 3, False
                    while time.monotonic() < deadline and child.poll() is None:
                        try:
                            result = request(('127.0.0.1', port), method='GET', path='/health', auth=None)
                            started = True
                            break
                        except OSError:
                            threading.Event().wait(.02)
                    self.assertTrue(started, 'HTTP module did not start with configured token')
                    self.json_response(result, 200, {'ok': True})
                    self.json_response(request(('127.0.0.1', port), auth='wrong'), 401, {'error': 'unauthorized'})
                    # Valid auth + invalid schema tests token loading without starting ProductFetcher.
                    self.json_response(request(('127.0.0.1', port), body=b'{}'), 400, {'error': 'invalid_request'})
                finally:
                    child.terminate()
                    out, err = child.communicate(timeout=5)
                self.assertNotIn(SECRET, err)
                self.assertNotIn(TOKEN, out + err)


if __name__ == '__main__':
    unittest.main(verbosity=2)
