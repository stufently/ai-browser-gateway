"""Exercise one-shot proxy routing through the real ladder with stubbed probes."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from bench.runner import execute
from gateway import oneshot
from gateway.fetch import ProductFetcher
from gateway.models import PlanStep
from gateway.sessions import SessionStore
from tests.test_gateway_product import page
from tests.test_oneshot import URL, invoke, process


EXPLICIT = 'http://user1:s3cr%40t@proxy.invalid:8080'
FLAG = 'https://flag.invalid:8443'
EGRESS = 'socks5://fallback.invalid:1080'
LADDER = ['curl_cffi', 'patchright', 'scrapling']
SESSION = {'ua': 'test-agent', 'cookies': [{'name': 'test-cookie', 'value': 'session'}]}
HOST = 'example.invalid'
SESSION_FILE = f'{HOST}.json'


def cli(args=(), *, environ=None, solve=False):
    def spawn(command, *, env, **kwargs):
        if solve and env['ABG_PROVIDER'] == 'patchright':
            proc = process()
            out, err = proc.communicate.return_value
            proc.communicate.return_value = (json.dumps(dict(json.loads(out), session=SESSION)), err)
            return proc
        if 'ABG_SESSION' in env:
            return process()
        return process(403)

    with patch.dict(os.environ, environ or {}, clear=True), patch.object(
            oneshot.subprocess, 'Popen', side_effect=spawn) as probe:
        result = invoke([URL, *args])
    return result, probe.call_args_list


def scope(identity):
    return 'proxy-' + hashlib.sha256(identity.encode()).hexdigest()[:16]


class ProxyLadderTests(unittest.TestCase):
    def assert_route(self, result, calls, proxy, providers=LADDER):
        rc, out, err = result
        self.assertEqual((rc, err), (1, ''))
        self.assertEqual([(a['provider'], a['egress_profile']) for a in json.loads(out)['attempts']],
                         [(provider, 'explicit') for provider in providers])
        self.assertEqual([call.kwargs['env'].get('ABG_PROXY') for call in calls],
                         [proxy] * len(providers))

    def test_explicit_routes_every_probe_and_suppresses_fallback(self):
        cases = [
            ((), {'ABG_PROXY': EXPLICIT}, EXPLICIT),
            ((), {'ABG_PROXY': EXPLICIT, 'ABG_EGRESS_PROXY': EGRESS}, EXPLICIT),
            (('--proxy', FLAG), {'ABG_EGRESS_PROXY': EGRESS}, FLAG),
            (('--proxy', FLAG), {'ABG_PROXY': EXPLICIT}, FLAG),
            (('--proxy', FLAG), {'ABG_PROXY': 'ftp://ignored.invalid'}, FLAG),
        ]
        for args, env, proxy in cases:
            with self.subTest(args=args, env=env):
                result, calls = cli(args, environ=env)
                self.assert_route(result, calls, proxy)
                for call in calls:
                    self.assertNotIn('ABG_EGRESS_PROXY', call.kwargs['env'])
                    self.assertNotIn(proxy, ' '.join(call.args[0]))
                observed = ' '.join([result[1], result[2], *(' '.join(c.args[0]) for c in calls)])
                for secret in ('s3cr%40t', 's3cr@t'):
                    self.assertNotIn(secret, observed)

    def test_blank_explicit_proxy_preserves_direct_and_socks5_fallback(self):
        for blank in (None, '', '  '):
            env = {'ABG_EGRESS_PROXY': EGRESS}
            if blank is not None:
                env['ABG_PROXY'] = blank
            with self.subTest(blank=blank):
                (rc, out, err), calls = cli(environ=env)
                self.assertEqual((rc, err), (1, ''))
                self.assertEqual([(a['provider'], a['egress_profile'])
                                  for a in json.loads(out)['attempts']],
                                 [(provider, 'direct') for provider in LADDER] +
                                 [('curl_cffi', 'proxy')])
                self.assertEqual([call.kwargs['env'].get('ABG_PROXY') for call in calls],
                                 [None, None, None, EGRESS])

    def test_explicit_socks5_uses_remote_dns_and_strips_loopback_override(self):
        override = 'PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK'
        for given in ('SOCKS5://proxy.invalid:1080', 'socks5h://proxy.invalid:1080'):
            with self.subTest(proxy=given):
                result, calls = cli(environ={'ABG_PROXY': given, override: '1'})
                self.assert_route(result, calls, 'socks5h://proxy.invalid:1080')
                for call in calls:
                    self.assertNotIn(override, call.kwargs['env'])

    def assert_refused(self, args, env, error):
        result, calls = cli(args, environ=env)
        self.assertEqual(result, (2, '', json.dumps({'error': error}) + '\n'))
        self.assertEqual(calls, [])

    def test_argv_rejects_any_userinfo_and_accepts_url_without_it(self):
        for userinfo in ('user1:s3cr%40t', 'user1', ':s3cr%40t', ''):
            with self.subTest(userinfo=userinfo):
                self.assert_refused(('--proxy', f'http://{userinfo}@proxy.invalid'), {},
                                    'proxy_credentials_in_argv')
        self.assert_refused(('--proxy', EXPLICIT, '--proxy', FLAG), {},
                            'proxy_credentials_in_argv')
        result, calls = cli(('--proxy', FLAG))
        self.assert_route(result, calls, FLAG)

    def test_socks_credentials_reach_every_step(self):
        """SOCKS5 с паролем больше не отказ: креды уезжают в пробы тем же ABG_PROXY."""
        for scheme in ('socks5', 'socks5h'):
            for userinfo in ('user1:s3cr%40t', 'user1'):
                with self.subTest(scheme=scheme, userinfo=userinfo):
                    env = {'ABG_PROXY': f'{scheme}://{userinfo}@proxy.invalid:1080'}
                    relayed = f'socks5h://{userinfo}@proxy.invalid:1080'
                    result, calls = cli(environ=env)
                    self.assert_route(result, calls, relayed)
                    result, calls = cli(('--no-browser',), environ=env)
                    self.assert_route(result, calls, relayed, ['curl_cffi'])
                    observed = ' '.join([result[1], result[2],
                                         *(' '.join(c.args[0]) for c in calls)])
                    for secret in ('s3cr%40t', 's3cr@t'):
                        self.assertNotIn(secret, observed)
            proxy = f'{scheme}://proxy.invalid:1080'
            result, calls = cli(environ={'ABG_PROXY': proxy})
            self.assert_route(result, calls, 'socks5h://proxy.invalid:1080')

    def test_invalid_proxy_urls_are_rejected_before_running_probes(self):
        for proxy in ('ftp://proxy.invalid', 'proxy.invalid:80', 'http://',
                      'http://proxy.invalid:port', 'http://proxy.invalid:65536',
                      ' http://proxy.invalid', 'http://proxy.invalid/a b',
                      'http://proxy.invalid/\t',
                      'http://proxy.invalid/\x7f', 'http://proxy.invalid/\x85', 'http://[::1'):
            with self.subTest(proxy=proxy):
                self.assert_refused((), {'ABG_PROXY': proxy}, 'invalid_request')
                self.assert_refused(('--proxy', proxy), {}, 'invalid_request')
        for proxy in ('', '  ', 'http://proxy.invalid/\x00'):
            self.assert_refused(('--proxy', proxy), {'ABG_PROXY': EXPLICIT}, 'invalid_request')
        self.assert_refused(('--proxy', FLAG), {'ABG_EGRESS_PROXY': 'http://bad.invalid:port'},
                            'invalid_request')
        result, calls = cli(('--proxy', FLAG), environ={'ABG_EGRESS_PROXY': EGRESS})
        self.assert_route(result, calls, FLAG)

    def test_explicit_session_scope_and_replay_follow_proxy_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {'ABG_SESSION_DIR': directory}
            for proxy, identity in [(EXPLICIT, 'http|proxy.invalid|8080|user1'),
                                    ('SOCKS5://socks.invalid', 'socks5h|socks.invalid|1080|')]:
                with self.subTest(proxy=proxy):
                    (rc, _, err), calls = cli(environ={**env, 'ABG_PROXY': proxy}, solve=True)
                    self.assertEqual((rc, err), (0, ''))
                    self.assertEqual(calls[-1].kwargs['env']['ABG_SESSION_EXPORT'], '1')
                    self.assertTrue((root / scope(identity) / SESSION_FILE).is_file())
            self.assertFalse((root / SESSION_FILE).exists())

            for proxy, replay in [(EXPLICIT, True),
                                  ('HTTP://us%65r1:changed@PROXY.invalid:8080', True),
                                  ('http://user2:s3cr%40t@proxy.invalid:8080', False),
                                  ('http://user1:s3cr%40t@proxy.invalid:8081', False),
                                  ('socks5h://socks.invalid:1080', True), ('', False)]:
                with self.subTest(proxy=proxy):
                    _, calls = cli(environ={**env, 'ABG_PROXY': proxy})
                    replayed = calls[0].kwargs['env'].get('ABG_SESSION')
                    self.assertEqual(json.loads(replayed) if replayed else None,
                                     SESSION if replay else None)

    def test_explicit_sessions_require_private_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'sessions'
            root.mkdir(mode=0o700)
            link = root.with_name('alias')
            link.symlink_to(root, target_is_directory=True)
            for path, mode, cached in [(link, 0o700, False), (root, 0o777, False),
                                       (root, 0o700, True)]:
                with self.subTest(path=path.name, mode=oct(mode)):
                    root.chmod(mode)
                    env = {'ABG_SESSION_DIR': str(path), 'ABG_PROXY': EXPLICIT}
                    (rc, _, err), calls = cli(environ=env, solve=True)
                    self.assertEqual((rc, err), (0, ''))
                    self.assertEqual('ABG_SESSION_EXPORT' in calls[-1].kwargs['env'], cached)
                    self.assertEqual(bool(list(root.glob(f'*/{SESSION_FILE}'))), cached)

    def test_fallback_does_not_read_or_write_a_populated_session_store(self):
        store = SessionStore()
        store.put(HOST, SESSION)
        sessions = Mock(spec=SessionStore, wraps=store)
        fetcher = ProductFetcher(URL, profiles={'explicit': EXPLICIT, 'proxy': EGRESS},
                                 sessions=sessions, route='explicit')
        response = page(final_url=URL), None
        with patch.object(execute, 'fetch_content', return_value=response) as fetch:
            fetcher(PlanStep('curl_cffi', 'explicit', 'http'), 1000)
            self.assertEqual(fetch.call_args.kwargs['session'], SESSION)
            sessions.get.assert_called_once_with(HOST)
            sessions.reset_mock()
            for step in (PlanStep('curl_cffi', 'proxy', 'egress'),
                         PlanStep('curl_cffi', 'proxy', 'http'),
                         PlanStep('patchright', 'proxy', 'browser'),
                         PlanStep('curl_cffi', 'direct', 'http')):
                with self.subTest(step=step):
                    fetcher(step, 1000)
                    self.assertNotIn('session', fetch.call_args.kwargs)
                    self.assertNotIn('on_session', fetch.call_args.kwargs)
                    self.assertEqual(sessions.mock_calls, [])
        self.assertEqual(store.get(HOST), SESSION)
