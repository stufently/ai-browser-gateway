"""HTTP-level rotation checks: validation, concurrency and isolated snapshots."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import unittest

from gateway.httpapi import make_server
from tests.m11_helpers import TOKEN, reply, request, serving


class RotationTests(unittest.TestCase):
    def test_default_order_and_opt_in_only_valid_requests_consume_position(self):
        source = {'a': 'http://a:8', 'b': 'http://b:8', 'c': 'http://c:8'}
        for rotate in (False, True):
            seen = []
            def factory(url, **kw):
                seen.append(tuple(kw['profiles']))
                kw['profiles'].clear()
                return lambda step, budget: reply()
            server = make_server(('127.0.0.1', 0), token=TOKEN, profiles=source,
                                 fetcher_factory=factory, rotate_profiles=rotate)
            with serving(server) as address:
                self.assertEqual(request(address, method='GET', path='/health')[0], 200)
                self.assertEqual(request(address, token='wrong')[0], 401)
                self.assertEqual(request(address, {'url': 'not-url'})[0], 400)
                for _ in range(4):
                    status, body = request(address)
                    self.assertEqual(status, 200)
                    self.assertTrue(body['ok'])
            self.assertEqual(seen, [('a', 'b', 'c'), ('b', 'c', 'a'), ('c', 'a', 'b'),
                                    ('a', 'b', 'c')] if rotate else [('a', 'b', 'c')] * 4)
            self.assertEqual(source, {'a': 'http://a:8', 'b': 'http://b:8', 'c': 'http://c:8'})
            self.assertEqual(server.profiles, source)

    def test_concurrent_rotation_full_copies_do_not_change_in_flight(self):
        count = 6
        barrier, lock = Barrier(count), Lock()
        source = {'a': 'http://a:8', 'b': 'http://b:8', 'c': 'http://c:8'}
        snapshots, passed = [], []
        def factory(url, **kw):
            snapshot = tuple(kw['profiles'])
            with lock:
                snapshots.append(snapshot)
                passed.append(kw['profiles'])
            barrier.wait(timeout=5)
            self.assertEqual(tuple(kw['profiles']), snapshot)
            self.assertEqual(kw['profiles'], source)
            kw['profiles']['local'] = url
            return lambda step, budget: reply()
        server = make_server(('127.0.0.1', 0), token=TOKEN, profiles=source,
                             fetcher_factory=factory, rotate_profiles=True)
        with serving(server) as address, ThreadPoolExecutor(count) as pool:
            results = list(pool.map(lambda _: request(address), range(count)))
        self.assertTrue(all(status == 200 and body['ok'] for status, body in results), results)
        self.assertEqual(Counter(snapshots), Counter({('a', 'b', 'c'): 2,
                                                    ('b', 'c', 'a'): 2,
                                                    ('c', 'a', 'b'): 2}))
        self.assertEqual(len({id(value) for value in passed}), count)
        self.assertEqual(server.profiles, source)
