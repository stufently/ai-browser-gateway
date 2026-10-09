"""Solved-challenge sessions: stores, the product fetcher, transport and probe."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from bench.models import ChallengeType as C, FailureReason as F, FetchResult
from bench.runner import fetch as transport
from gateway.fetch import ProductFetcher
from gateway.models import PlanStep
from gateway.sessions import MAX_AGE_S, FileSessionStore, SessionStore, valid_session
from tests.probe_m9_transport import _probe_payload
from tests.test_probe import load_probe

SESSION = {'ua': 'Mozilla/5.0 Chrome/153', 'cookies': [{'name': 'cf_clearance', 'value': 'v1'}]}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def result(status=200, challenge=C.none, error=F.none, provider='curl_cffi'):
    return FetchResult(
        provider=provider, provider_version='t', requested_url='https://a.test/',
        final_url='https://a.test/', status=status, html='<p>x</p>', text='x',
        elapsed_ms=1, startup_ms=0, cpu_ms=0, peak_rss_mb=0.0, bytes_received=1,
        redirects=0, error_type=error, challenge=challenge)


class SessionShapeTests(unittest.TestCase):
    def test_sessions_last_thirty_minutes(self):
        self.assertEqual(MAX_AGE_S, 1800)

    def test_valid_and_invalid_shapes(self):
        self.assertTrue(valid_session(SESSION))
        cookie = {'name': 'n', 'value': 'v'}
        for bad in (None, {}, {'ua': 'x'}, {'ua': '', 'cookies': [cookie]},
                    {'ua': 'a\nb', 'cookies': [cookie]}, {'ua': 'x' * 513, 'cookies': [cookie]},
                    {'ua': 'x', 'cookies': []}, {'ua': 'x', 'cookies': [cookie] * 65},
                    {'ua': 'x', 'cookies': [{'name': '', 'value': 'v'}]},
                    {'ua': 'x', 'cookies': [{'name': 'n', 'value': 1}]},
                    {'ua': 'x', 'cookies': [{'name': 'n', 'value': 'v', 'path': '/'}]},
                    {'ua': 'x', 'cookies': [{'name': 'n', 'value': 'v', 'domain': 1}]},
                    {'ua': 'x', 'cookies': [{'name': 'n', 'value': 'v', 'domain': 'd' * 256}]},
                    {'ua': 'x', 'cookies': [{'name': 'n', 'value': 'v' * 4097}]},
                    {'ua': 'x', 'cookies': [cookie], 'extra': 1}):
            with self.subTest(bad=bad):
                self.assertFalse(valid_session(bad))
        self.assertTrue(valid_session({'ua': 'x', 'cookies': [cookie] * 64}))
        self.assertTrue(valid_session({'ua': 'x', 'cookies': [dict(cookie, domain='.a.test')]}))


class SessionStoreTests(unittest.TestCase):
    def test_round_trip_copies_and_expiry(self):
        clock = Clock()
        store = SessionStore(clock=clock)
        store.put('a.test', json.loads(json.dumps(SESSION)))
        got = store.get('a.test')
        self.assertEqual(got, SESSION)
        got['cookies'][0]['value'] = 'changed'
        got['ua'] = 'changed'
        self.assertEqual(store.get('a.test'), SESSION)
        self.assertIsNone(store.get('b.test'))
        clock.now += MAX_AGE_S - 1
        self.assertEqual(store.get('a.test'), SESSION)
        clock.now += 1
        self.assertIsNone(store.get('a.test'))

    def test_drop_compares_user_agent_too(self):
        store = SessionStore()
        store.put('a.test', SESSION)
        store.drop('a.test', dict(SESSION, ua='Other UA'))
        self.assertEqual(store.get('a.test'), SESSION)

    def test_late_drop_keeps_a_newer_session(self):
        store = SessionStore()
        newer = {'ua': 'UA2', 'cookies': [{'name': 'cf_clearance', 'value': 'v2'}]}
        store.put('a.test', newer)
        store.drop('a.test', SESSION)
        self.assertEqual(store.get('a.test'), newer)
        store.drop('a.test', newer)
        self.assertIsNone(store.get('a.test'))

    def test_invalid_session_or_host_is_ignored_and_drop_removes(self):
        store = SessionStore()
        store.put('a.test', {'ua': 'x', 'cookies': []})
        store.put('', SESSION)
        self.assertIsNone(store.get('a.test'))
        self.assertIsNone(store.get(''))
        store.put('a.test', SESSION)
        store.drop('a.test')
        self.assertIsNone(store.get('a.test'))

    def test_oldest_entry_leaves_first_and_put_refreshes(self):
        store = SessionStore(max_entries=2)
        store.put('a.test', SESSION)
        store.put('b.test', SESSION)
        store.put('a.test', SESSION)
        store.put('c.test', SESSION)
        self.assertIsNone(store.get('b.test'))
        self.assertEqual(store.get('a.test'), SESSION)
        self.assertEqual(store.get('c.test'), SESSION)


class FileSessionStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, 'sessions')
        self.clock = Clock()
        self.store = FileSessionStore(self.dir, clock=self.clock)

    def test_round_trip_private_files_and_expiry(self):
        self.store.put('a.test', SESSION)
        path = os.path.join(self.dir, 'a.test.json')
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, '.lock')).st_mode), 0o600)
        self.assertEqual(FileSessionStore(self.dir, clock=self.clock).get('a.test'), SESSION)
        self.clock.now += MAX_AGE_S
        self.assertIsNone(self.store.get('a.test'))
        self.assertFalse(os.path.exists(path))

    def test_unsafe_hosts_are_never_paths(self):
        for host in ('../x', 'A.test', '.hidden', 'a/b', 'é.test', '', None, 'a' * 64 + '.t',
                     ('a' * 63 + '.') * 4 + 'aa'):
            with self.subTest(host=host):
                self.assertIsNone(self.store._path(host))
                self.store.put(host, SESSION)
                self.assertIsNone(self.store.get(host))
        self.assertEqual(os.listdir(self.dir) if os.path.isdir(self.dir) else [], [])

    def test_corrupt_or_foreign_file_reads_as_none(self):
        os.makedirs(self.dir, mode=0o700)
        path = os.path.join(self.dir, 'a.test.json')
        for content in ('not json', '{}', json.dumps({'deadline': 'x', 'session': SESSION}),
                        json.dumps({'deadline': 9e9, 'session': {'ua': 'x', 'cookies': []}}),
                        json.dumps({'deadline': None, 'session': SESSION}), '[]'):
            with self.subTest(content=content):
                with open(path, 'w') as stream:
                    stream.write(content)
                self.assertIsNone(self.store.get('a.test'))
        with open(path, 'w') as stream:
            stream.write(json.dumps({'deadline': 9e9, 'session': SESSION}))
        self.assertEqual(self.store.get('a.test'), SESSION)

    def test_drop_removes_file(self):
        self.store.put('a.test', SESSION)
        self.store.drop('a.test')
        self.assertIsNone(self.store.get('a.test'))
        self.store.drop('missing.test')

    def test_replace_and_checked_drop_run_under_the_lock(self):
        import fcntl
        events = []
        real_replace, real_unlink = os.replace, os.unlink
        with patch('fcntl.flock', lambda fd, op: events.append('lock' if op == fcntl.LOCK_EX else op)), \
                patch('os.replace', lambda *a: events.append('replace') or real_replace(*a)):
            self.store.put('a.test', SESSION)
            self.store.drop('a.test', SESSION)
        self.assertEqual(events, ['lock', 'replace', 'lock'])
        self.assertIsNone(self.store.get('a.test'))

    def test_late_drop_keeps_a_newer_session(self):
        newer = {'ua': 'UA2', 'cookies': [{'name': 'cf_clearance', 'value': 'v2'}]}
        self.store.put('a.test', newer)
        self.store.drop('a.test', SESSION)
        self.assertEqual(self.store.get('a.test'), newer)
        self.store.drop('a.test', newer)
        self.assertIsNone(self.store.get('a.test'))

    def test_shared_or_foreign_directory_is_refused(self):
        os.makedirs(self.dir, mode=0o700)
        self.store.put('a.test', SESSION)
        os.chmod(self.dir, 0o770)
        self.assertIsNone(self.store.get('a.test'))
        self.store.put('b.test', SESSION)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'b.test.json')))
        os.chmod(self.dir, 0o700)
        self.assertEqual(self.store.get('a.test'), SESSION)
        with patch('os.getuid', return_value=os.getuid() + 1):
            self.assertIsNone(self.store.get('a.test'))

    def test_planted_link_is_neither_followed_nor_written_through(self):
        os.makedirs(self.dir, mode=0o700)
        outside = os.path.join(os.path.dirname(self.dir), 'outside.json')
        with open(outside, 'w') as stream:
            stream.write(json.dumps({'deadline': 9e9, 'session': SESSION}))
        os.symlink(outside, os.path.join(self.dir, 'a.test.json'))
        self.assertIsNone(self.store.get('a.test'))
        self.store.put('a.test', {'ua': 'UA2', 'cookies': [{'name': 'n', 'value': 'v'}]})
        with open(outside) as stream:
            self.assertEqual(json.loads(stream.read())['session'], SESSION)
        self.assertFalse(os.path.islink(os.path.join(self.dir, 'a.test.json')))
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith('.session-')], [])


class ProductFetcherSessionTests(unittest.TestCase):
    def run_step(self, step, reply, store, *, report=None):
        calls = []

        def fake(provider, **kwargs):
            calls.append(kwargs)
            if report is not None and 'on_session' in kwargs:
                kwargs['on_session'](report)
            return reply, None
        with patch('bench.runner.execute.fetch_content', fake):
            ProductFetcher('https://a.test/page', sessions=store)(step, 1000)
        return calls[0]

    def test_direct_http_step_replays_and_keeps_a_passing_session(self):
        store = SessionStore()
        store.put('a.test', SESSION)
        kwargs = self.run_step(PlanStep('curl_cffi', 'direct', 'http'), result(), store)
        self.assertEqual(kwargs['session'], SESSION)
        self.assertNotIn('on_session', kwargs)
        self.assertEqual(store.get('a.test'), SESSION)

    def test_failed_replay_drops_the_session(self):
        from dataclasses import replace
        offsite = replace(result(), final_url='https://b.test/')
        for reply in (result(status=403), result(challenge=C.suspected),
                      result(status=None, error=F.timeout), result(status=302),
                      result(status=200, error=F.provider_error), offsite):
            with self.subTest(reply=reply):
                store = SessionStore()
                store.put('a.test', SESSION)
                self.run_step(PlanStep('curl_cffi', 'direct', 'http'), reply, store)
                self.assertIsNone(store.get('a.test'))

    def test_http_step_without_session_and_failure_keeps_nothing(self):
        store = SessionStore()
        kwargs = self.run_step(PlanStep('curl_cffi', 'direct', 'http'), result(status=403), store)
        self.assertNotIn('session', kwargs)

    def test_direct_browser_reports_its_session(self):
        store = SessionStore()
        kwargs = self.run_step(PlanStep('patchright', 'direct', 'browser'), result(), store,
                               report=SESSION)
        self.assertIn('on_session', kwargs)
        self.assertNotIn('session', kwargs)
        self.assertEqual(store.get('a.test'), SESSION)

    def test_egress_and_entrance_steps_never_touch_sessions(self):
        store = SessionStore()
        store.put('a.test', SESSION)
        for step in (PlanStep('curl_cffi', 'proxy', 'egress'), PlanStep('wayback', 'direct', 'entrance'),
                     PlanStep('patchright', 'proxy', 'browser')):
            with self.subTest(step=step):
                kwargs = self.run_step(step, result(status=403), store, report=SESSION)
                self.assertNotIn('session', kwargs)
                self.assertNotIn('on_session', kwargs)
        self.assertEqual(store.get('a.test'), SESSION)

    def test_plain_http_never_uses_sessions(self):
        store = SessionStore()
        store.put('a.test', SESSION)
        for step in (PlanStep('curl_cffi', 'direct', 'http'), PlanStep('patchright', 'direct', 'browser')):
            with self.subTest(step=step):
                calls = []
                def fake(provider, **kwargs):
                    calls.append(kwargs)
                    return result(status=403), None
                with patch('bench.runner.execute.fetch_content', fake):
                    ProductFetcher('http://a.test/page', sessions=store)(step, 1000)
                self.assertNotIn('session', calls[0])
                self.assertNotIn('on_session', calls[0])
        self.assertEqual(store.get('a.test'), SESSION)

    def test_late_failure_keeps_a_session_saved_meanwhile(self):
        store = SessionStore()
        store.put('a.test', SESSION)
        newer = {'ua': 'UA2', 'cookies': [{'name': 'cf_clearance', 'value': 'v2'}]}
        def fake(provider, **kwargs):
            store.put('a.test', newer)
            return result(status=403), None
        with patch('bench.runner.execute.fetch_content', fake):
            ProductFetcher('https://a.test/', sessions=store)(PlanStep('curl_cffi', 'direct', 'http'), 1000)
        self.assertEqual(store.get('a.test'), newer)

    def test_without_store_no_session_options(self):
        for step in (PlanStep('curl_cffi', 'direct', 'http'), PlanStep('scrapling', 'direct', 'browser')):
            with self.subTest(step=step):
                kwargs = self.run_step(step, result(), None)
                self.assertNotIn('session', kwargs)
                self.assertNotIn('on_session', kwargs)


class TransportSessionTests(unittest.TestCase):
    class Launcher:
        def __init__(self, payload):
            self.payload = payload
            self.calls = []

        def run(self, argv, timeout, *, env=None):
            self.calls.append((argv, env))
            return 0, json.dumps(self.payload), ''

    def fetch(self, provider, payload=None, **options):
        launcher = self.Launcher(payload or _probe_payload())
        with patch.dict(os.environ, {'ABG_SESSION': 'stale', 'ABG_SESSION_EXPORT': '1'}):
            transport.fetch_content(provider, url='https://a.test/', budget_ms=1000,
                                    launcher=launcher, **options)
        return launcher.calls[0]

    def test_curl_receives_session_by_environment_name_only(self):
        argv, env = self.fetch('curl_cffi', session=SESSION)
        self.assertEqual(json.loads(env['ABG_SESSION']), SESSION)
        self.assertNotIn('ABG_SESSION_EXPORT', env)
        index = argv.index('ABG_SESSION')
        self.assertEqual(argv[index - 1], '--env')
        self.assertFalse(any('cf_clearance' in part for part in argv))

    def test_inherited_session_variables_never_leak(self):
        argv, env = self.fetch('curl_cffi')
        self.assertNotIn('ABG_SESSION', env)
        self.assertNotIn('ABG_SESSION_EXPORT', env)
        self.assertNotIn('ABG_SESSION', argv)

    def test_browser_exports_and_reports_session(self):
        seen = []
        argv, env = self.fetch('patchright', _probe_payload(session=SESSION),
                               session=SESSION, on_session=seen.append)
        self.assertEqual(env['ABG_SESSION_EXPORT'], '1')
        self.assertNotIn('ABG_SESSION', env)
        self.assertIn('ABG_SESSION_EXPORT', argv)
        self.assertEqual(seen, [SESSION])

    def test_curl_never_exports(self):
        seen = []
        argv, env = self.fetch('curl_cffi', _probe_payload(session=SESSION), on_session=seen.append)
        self.assertNotIn('ABG_SESSION_EXPORT', env)
        self.assertEqual(seen, [SESSION])

    def test_no_session_in_payload_reports_nothing(self):
        seen = []
        self.fetch('scrapling', on_session=seen.append)
        self.assertEqual(seen, [])


class ProbeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def curl_chain(self, environ, responses):
        calls = []

        class Response:
            content, history = b'<p>x</p>', []

            def __init__(self, status, url, location=None):
                self.status_code, self.url = status, url
                self.headers = {'Location': location} if location else {}

        chain = iter(Response(*item) for item in responses)
        clients = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return next(chain)

        class Jar:
            def __init__(self):
                self.set_calls = []

            def set(self, name, value, domain=''):
                self.set_calls.append((name, value, domain))

        class Session:
            def __init__(self):
                self.closed = False
                self.cookies = Jar()
                clients.append(self)

            def get(self, url, **kwargs):
                return get(url, client=self, **kwargs)

            def close(self):
                self.closed = True
        curl_cffi = types.ModuleType('curl_cffi')
        requests_mod = types.ModuleType('curl_cffi.requests')
        requests_mod.get = get
        requests_mod.Session = Session
        curl_cffi.requests = requests_mod
        with patch.dict(sys.modules, {'curl_cffi': curl_cffi, 'curl_cffi.requests': requests_mod}), \
                patch.dict(os.environ, environ, clear=False):
            if 'ABG_SESSION' not in environ:
                os.environ.pop('ABG_SESSION', None)
            os.environ.pop('ABG_PROXY', None)
            value = self.probe.CurlCffiAdapter().navigate('https://a.test/')
        self.clients = clients
        return calls, value

    def test_replay_follows_only_https_redirects_on_the_same_host(self):
        env = {'ABG_SESSION': json.dumps(SESSION)}
        calls, value = self.curl_chain(env, [(302, 'https://a.test/', '/next'),
                                              (200, 'https://a.test/next')])
        self.assertEqual([url for url, _ in calls], ['https://a.test/', 'https://a.test/next'])
        # Both hops share one client (its cookie jar, seeded once) and it is closed after.
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(self.clients[0].cookies.set_calls, [('cf_clearance', 'v1', 'a.test')])
        self.assertTrue(all(kw['client'] is self.clients[0] and kw['allow_redirects'] is False
                            and 'cookies' not in kw for _, kw in calls))
        self.assertTrue(self.clients[0].closed)
        self.assertEqual((value['status'], value['final_url'], value['redirects']),
                         (200, 'https://a.test/next', 1))
        for status in (301, 303, 307, 308):
            with self.subTest(status=status):
                hops, _ = self.curl_chain(env, [(status, 'https://a.test/', '/n'),
                                                (200, 'https://a.test/n')])
                self.assertEqual(len(hops), 2)

    def test_replay_keeps_the_browser_cookie_domain_when_it_covers_the_host(self):
        cookies = [{'name': 'a', 'value': '1', 'domain': '.a.test'},
                   {'name': 'b', 'value': '2', 'domain': 'a.test'},
                   {'name': 'c', 'value': '3', 'domain': '.other.test'},
                   {'name': 'd', 'value': '4', 'domain': 'xa.test'},
                   {'name': 'e', 'value': '5'},
                   {'name': 'f', 'value': '6', 'domain': 'est'}]
        env = {'ABG_SESSION': json.dumps({'ua': 'UA', 'cookies': cookies})}
        self.curl_chain(env, [(200, 'https://a.test/')])
        self.assertEqual(self.clients[0].cookies.set_calls, [
            ('a', '1', '.a.test'), ('b', '2', 'a.test'), ('c', '3', 'a.test'),
            ('d', '4', 'a.test'), ('e', '5', 'a.test'), ('f', '6', 'a.test')])

    def test_leaving_the_host_falls_back_to_an_ordinary_request(self):
        env = {'ABG_SESSION': json.dumps(SESSION)}
        for location in ('http://a.test/plain', 'https://b.test/x', '//b.test/x'):
            with self.subTest(location=location):
                calls, value = self.curl_chain(env, [(301, 'https://a.test/', location),
                                                      (200, 'https://b.test/x')])
                self.assertEqual(len(calls), 2)
                url, plain = calls[1]
                self.assertEqual(url, 'https://a.test/')
                self.assertNotIn('client', plain)
                self.assertNotIn('headers', plain)
                self.assertTrue(plain['allow_redirects'])
                self.assertEqual((value['status'], value['final_url']), (200, 'https://b.test/x'))

    def test_replay_redirects_are_capped(self):
        env = {'ABG_SESSION': json.dumps(SESSION)}
        loop = [(307, 'https://a.test/', '/again')] * 12
        calls, value = self.curl_chain(env, loop)
        self.assertEqual(len(calls), 11)
        self.assertEqual(value['redirects'], 10)

    def test_without_session_curl_follows_redirects_itself(self):
        calls, value = self.curl_chain({}, [(200, 'https://b.test/')])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1]['allow_redirects'])
        self.assertNotIn('client', calls[0][1])
        self.assertEqual(self.clients, [])

    def test_curl_replays_user_agent_with_impersonation(self):
        calls, _ = self.curl_chain({'ABG_SESSION': json.dumps(SESSION)}, [(200, 'https://a.test/')])
        self.assertEqual(calls[0][1]['headers'], {'User-Agent': SESSION['ua']})
        self.assertEqual(calls[0][1]['impersonate'], 'chrome')

    def test_curl_ignores_absent_or_broken_session(self):
        cookie = [{'name': 'n', 'value': 'v'}]
        for raw in (None, '', 'not json', '{}', json.dumps({'ua': '', 'cookies': []}),
                    json.dumps({'ua': '', 'cookies': cookie}), json.dumps({'ua': 7, 'cookies': cookie}),
                    json.dumps({'ua': 'x', 'cookies': [{'name': 1, 'value': 'v'}]}),
                    json.dumps({'ua': 'x', 'cookies': 'c'})):
            with self.subTest(raw=raw):
                calls, _ = self.curl_chain({} if raw is None else {'ABG_SESSION': raw},
                                           [(200, 'https://a.test/')])
                self.assertNotIn('headers', calls[0][1])
                self.assertNotIn('client', calls[0][1])
                self.assertEqual(self.clients, [])

    def test_browser_session_shape_and_cookie_cap(self):
        class Page:
            def evaluate(self, script):
                assert script == 'navigator.userAgent'
                return 'UA'

        class Context:
            pages = [Page()]

            def __init__(self, cookies):
                self._cookies = cookies

            def cookies(self, url):
                assert url == 'https://a.test/'
                return self._cookies
        many = [{'name': f'n{i}', 'value': 'v', 'domain': 'a.test'} for i in range(70)]
        session = self.probe._browser_session(Context(many), None, 'https://a.test/',
                                              'https://a.test/')
        self.assertEqual(session['ua'], 'UA')
        self.assertEqual(len(session['cookies']), 64)
        self.assertEqual(session['cookies'][0], {'name': 'n0', 'value': 'v', 'domain': 'a.test'})
        self.assertIsNone(self.probe._browser_session(Context([]), None, 'https://a.test/',
                                                      'https://a.test/'))
        self.assertIsNone(self.probe._browser_session(None, None, 'https://a.test/', 'https://a.test/'))
        # A redirect to another host never files that host's cookies here.
        self.assertIsNone(self.probe._browser_session(Context(many), None, 'https://a.test/',
                                                      'https://b.test/x'))

    def run_probe(self, status, body, session):
        class Adapter:
            version = 'v'

            def start(self):
                pass

            def navigate(self, url):
                return {'status': status, 'final_url': url, 'body': body, 'session': session}

            def close(self):
                pass
        return self.probe.run_probe('patchright', 'https://a.test/', mode='cold',
                                    adapter_factory=lambda name: Adapter(),
                                    metrics=lambda: (0, 0.0), content_only=True)

    def test_payload_carries_session_only_for_a_passed_page(self):
        self.assertEqual(self.run_probe(200, '<p>ok</p>', SESSION)['session'], SESSION)
        cf = '<title>Just a moment...</title>'
        for status, body in ((403, '<p>no</p>'), (200, cf), (None, '<p>ok</p>'), (302, '<p>r</p>')):
            with self.subTest(status=status, body=body):
                self.assertNotIn('session', self.run_probe(status, body, SESSION))
        self.assertNotIn('session', self.run_probe(200, '<p>ok</p>', None))


class ServiceWiringTests(unittest.TestCase):
    def setUp(self):
        from tests import test_service_config as config
        config.ConfigurationTests.setUp(self)

    def test_service_shares_one_store_across_requests(self):
        from gateway import service
        server = service.make_service(self.env)
        self.addCleanup(server.server_close)
        self.assertIsInstance(server.sessions, SessionStore)
        made = []
        with patch('gateway.fetch.ProductFetcher', lambda url, **kw: made.append(kw) or None):
            for url in ('https://a.test/', 'https://b.test/'):
                server.factory(url, entrances={}, profiles={})
        self.assertEqual([kw['sessions'] for kw in made], [server.sessions] * 2)

    def test_oneshot_store_only_with_directory(self):
        from gateway import oneshot
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ABG_SESSION_DIR', None)
            self.assertIsNone(oneshot.session_store())
            os.environ['ABG_SESSION_DIR'] = '/tmp/x'
            self.assertIsInstance(oneshot.session_store(), FileSessionStore)


if __name__ == '__main__':
    unittest.main()
