import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from tests.m11_helpers import URL, TOKEN, reply, serving, request


class APITests(unittest.TestCase):
    def test_duplicate_json_keys_rejected_before_factory(self):
        from gateway.httpapi import make_server
        calls = []
        def factory(url, **kw):
            calls.append(url)
            return lambda s, b: reply()
        bodies = [
            '{"url":"https://example.invalid/a","url":"https://example.invalid/b"}',
            '{"url":"https://example.invalid/a","format":"text","format":"html"}',
            '{"url":"https://example.invalid/a","budget_ms":1000,"budget_ms":1000}',
        ]
        with serving(make_server(('127.0.0.1', 0), token=TOKEN, fetcher_factory=factory)) as addr:
            for body in bodies:
                with self.subTest(body=body):
                    conn = HTTPConnection(*addr, timeout=8)
                    try:
                        conn.request('POST', '/v1/fetch', body.encode(),
                                     {'Authorization': 'Bearer ' + TOKEN,
                                      'Content-Type': 'application/json'})
                        res = conn.getresponse()
                        self.assertEqual((res.status, json.loads(res.read())),
                                         (400, {'error': 'invalid_request'}))
                    finally:
                        conn.close()
            self.assertEqual(calls, [], 'duplicate JSON reached the fetcher factory')

    def test_deep_html_keeps_success_for_all_parsed_formats(self):
        from gateway.httpapi import make_server
        html = '<h1><a href="/x">' + '<span>' * 2000 + 'visible' + '</span>' * 2000 + '</a></h1>'
        factory = lambda *a, **kw: lambda s, b: reply(html=html)
        with serving(make_server(('127.0.0.1', 0), token=TOKEN, fetcher_factory=factory)) as addr:
            for mode in ('markdown', 'links', 'meta'):
                with self.subTest(mode=mode):
                    status, value = request(addr, {'url': URL, 'format': mode})
                    self.assertEqual(status, 200)
                    self.assertTrue(value['ok'])
                    self.assertIn('visible', str(value['content']))

    def test_validation_framing_auth_and_internal_error(self):
        from gateway.httpapi import make_server
        calls = []
        def factory(*a, **kw):
            calls.append(1)
            raise RuntimeError('secret-upstream')
        with serving(make_server(('127.0.0.1', 0), token=TOKEN, fetcher_factory=factory)) as addr:
            self.assertEqual(request(addr, method='GET', path='/health'), (200, {'ok': True}))
            self.assertEqual(request(addr, token='bad'), (401, {'error': 'unauthorized'}))
            for data in ({'url': URL, 'format': []}, {'url': URL, 'budget_ms': True}, {'url': URL, 'token': 'x'}):
                self.assertEqual(request(addr, data), (400, {'error': 'invalid_request'}))
            for length in ('2\r\nContent-Length: 2', '-1', '65537', '+2'):
                with socket.create_connection(addr, timeout=6) as sock:
                    sock.sendall(('POST /v1/fetch HTTP/1.1\r\nHost: local\r\nAuthorization: Bearer ' + TOKEN +
                                  '\r\nContent-Type: application/json\r\nContent-Length: ' + length + '\r\n\r\n{}').encode())
                    self.assertIn(b'400', sock.recv(4096))
            self.assertEqual(calls, [])
            self.assertEqual(request(addr), (500, {'error': 'internal_error'}))
            self.assertEqual(calls, [1])

    def test_browser_slot_shared_health_and_http_bypass(self):
        from gateway.httpapi import make_server
        entered, release, second_http = threading.Event(), threading.Event(), threading.Event()
        active, maximum, lock = [0], [0], threading.Lock()
        def factory(url, **kw):
            def fetch(step, budget):
                if step.provider == 'curl_cffi':
                    if url.endswith('/second'):
                        second_http.set()
                    return reply(status=200 if url.endswith('/http') else 403)
                with lock:
                    active[0] += 1
                    maximum[0] = max(maximum[0], active[0])
                entered.set()
                if not release.wait(4):
                    raise RuntimeError('test gate timed out')
                with lock:
                    active[0] -= 1
                return reply(step.provider)
            return fetch
        with serving(make_server(('127.0.0.1', 0), token=TOKEN, fetcher_factory=factory)) as addr:
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(request, addr)
                try:
                    self.assertTrue(entered.wait(2))
                    second = pool.submit(request, addr, {'url': URL + '/second', 'budget_ms': 100})
                    self.assertTrue(second_http.wait(2))
                    self.assertEqual(request(addr, method='GET', path='/health')[0], 200)
                    self.assertTrue(request(addr, {'url': URL + '/http'})[1]['ok'])
                    result = second.result(3)[1]
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['error_type'], 'timeout')
                    self.assertIsNone(result['attempts'][-1]['status'])
                finally:
                    release.set()
                self.assertTrue(first.result(3)[1]['ok'])
        self.assertEqual(maximum[0], 1)

    def test_limiter_budget_rounding_and_exception_release(self):
        from gateway.httpapi import limit_fetcher
        from gateway.models import PlanStep
        now, calls = [0.0], []
        class Gate:
            def acquire(self, timeout):
                now[0] += 1.2
                return True
            def release(self):
                calls.append('release')
        step = PlanStep('scrapling', 'direct', 'browser')
        fn = limit_fetcher(lambda s, b: calls.append(b) or reply(s.provider), Gate(), url=URL, clock=lambda: now[0])
        fn(step, 10)
        self.assertEqual(calls, [8, 'release'])
        calls.clear()
        self.assertEqual(fn(step, 2).result.error_type, 'timeout')
        self.assertEqual(calls, ['release'])
        gate = threading.BoundedSemaphore(1)
        def broken(s, b):
            raise RuntimeError('expected')
        with self.assertRaises(RuntimeError):
            limit_fetcher(broken, gate, url=URL)(step, 100)
        self.assertTrue(gate.acquire(blocking=False))
        gate.release()

    def test_configured_browser_limit_admits_two_and_bounds_queue(self):
        from gateway.httpapi import make_server
        entered = [threading.Event(), threading.Event()]
        release, queued_http = threading.Event(), threading.Event()
        active, maximum, browser_urls = [0], [0], []
        lock = threading.Lock()
        def factory(url, **kw):
            def fetch(step, budget):
                if step.provider == 'curl_cffi':
                    if url.endswith('/queued'):
                        queued_http.set()
                    return reply(status=403)
                with lock:
                    browser_urls.append(url)
                    active[0] += 1
                    maximum[0] = max(maximum[0], active[0])
                if url.endswith('/first'):
                    entered[0].set()
                elif url.endswith('/second'):
                    entered[1].set()
                try:
                    if not release.wait(6):
                        raise RuntimeError('test gate timed out')
                    return reply(step.provider)
                finally:
                    with lock:
                        active[0] -= 1
            return fetch
        server = make_server(('127.0.0.1', 0), token=TOKEN, browser_limit=2,
                             fetcher_factory=factory)
        with serving(server) as addr, ThreadPoolExecutor(3) as pool:
            first = pool.submit(request, addr, {'url': URL + '/first'})
            second = pool.submit(request, addr, {'url': URL + '/second'})
            try:
                self.assertTrue(all(event.wait(2) for event in entered),
                                'configured browser_limit=2 must admit two held calls')
                with lock:
                    self.assertEqual(active[0], 2)
                queued = pool.submit(request, addr, {'url': URL + '/queued', 'budget_ms': 200})
                self.assertTrue(queued_http.wait(2))
                status, value = queued.result(3)
                self.assertEqual(status, 200)
                self.assertFalse(value['ok'])
                self.assertEqual(value['error_type'], 'timeout')
                self.assertIsNone(value['attempts'][-1]['status'])
                with lock:
                    self.assertNotIn(URL + '/queued', browser_urls)
                    self.assertEqual(active[0], 2)
                self.assertEqual(request(addr, method='GET', path='/health'), (200, {'ok': True}))
            finally:
                release.set()
            for future in (first, second):
                status, value = future.result(3)
                self.assertEqual(status, 200)
                self.assertTrue(value['ok'])
            status, value = request(addr, {'url': URL + '/after-release'})
            self.assertEqual(status, 200)
            self.assertTrue(value['ok'])
        self.assertEqual(maximum[0], 2)
        self.assertEqual(active[0], 0)
        self.assertCountEqual(browser_urls, [URL + suffix for suffix in
                                            ('/first', '/second', '/after-release')])
