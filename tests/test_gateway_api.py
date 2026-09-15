import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from tests.m11_helpers import URL, TOKEN, reply, serving, request


class APITests(unittest.TestCase):
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
                if step.provider == 'curl':
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
