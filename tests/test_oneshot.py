"""Offline CLI and local process contract; only the probe process is replaced."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import signal
import subprocess
import unittest
from unittest.mock import Mock, call, patch

from bench.providers.registry import PROVIDERS, build_argv, by_name
from gateway import oneshot
from gateway.product import plan_product
from tests.probe_m9_transport import _probe_payload


URL = 'https://example.invalid/'
HTML = '<html><head><title>Example</title></head><body><h1>Hello</h1></body></html>'


def process(status=200):
    proc = Mock(pid=12345, returncode=0)
    payload = _probe_payload(status=status, final_url=URL, html=HTML, text='Hello')
    proc.communicate.return_value = (json.dumps(payload), 'probe diagnostic')
    return proc


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = oneshot.main(args)
    return rc, out.getvalue(), err.getvalue()


class OneshotTests(unittest.TestCase):
    def test_exit_codes_and_output_contract(self):
        with patch.object(oneshot.subprocess, 'Popen', return_value=process(403)):
            rc, out, err = invoke([URL])
        self.assertEqual(rc, 1)
        value = json.loads(out)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(err, '')
        self.assertEqual(set(value), {'ok', 'url', 'final_url', 'provider', 'age_hours',
                                    'error_type', 'step', 'elapsed_ms', 'format',
                                    'content', 'attempts'})
        self.assertEqual((value['ok'], value['error_type'], value['step']),
                         (False, 'http_403', 'human'))
        self.assertEqual([a['provider'] for a in value['attempts']],
                         ['curl_cffi', 'patchright', 'scrapling'])
        self.assertTrue(all(a['status'] == 403 for a in value['attempts']))
        for mode, content in [('text', 'Hello'), ('html', HTML), ('markdown', '# Hello'),
                              ('links', []), ('meta', {'title': 'Example', 'h1': ['Hello']})]:
            with self.subTest(mode=mode), patch.object(
                    oneshot.subprocess, 'Popen', return_value=process()):
                rc, out, err = invoke([URL, '--format', mode])
                self.assertEqual((rc, err), (0, ''))
                value = json.loads(out)
                self.assertEqual(len(out.splitlines()), 1)
                self.assertEqual((value['ok'], value['provider'], value['content']),
                                 (True, 'curl_cffi', content))
                self.assertEqual((value['url'], value['final_url'], value['format']),
                                 (URL, URL, mode))
        with patch.object(oneshot.subprocess, 'Popen', return_value=process()):
            rc, out, err = invoke([URL, '--expected-text', 'missing', '--no-browser'])
        self.assertEqual((rc, json.loads(out)['error_type']), (1, 'content_missing'))
        with patch.object(oneshot.subprocess, 'Popen', side_effect=RuntimeError('private')):
            self.assertEqual(invoke([URL]), (3, '', '{"error": "internal_error"}\n'))

    def test_invalid_arguments_rc2_without_stdout(self):
        cases = [[], ['ftp://example.org/'], ['https://user:secret@example.org/'],
                 [URL, '--format', 'pdf'], [URL, '--budget-ms', '0'],
                 [URL, '--budget-ms', '180001'], [URL, '--budget-ms', 'abc'],
                 [URL, '--budget-ms'], [URL, '--expected-text', ' '],
                 [URL, '--unknown'], [URL, '--format'], [URL, 'extra']]
        with patch.object(oneshot.subprocess, 'Popen') as spawn:
            for args in cases:
                with self.subTest(args=args):
                    self.assertEqual(invoke(args), (2, '', '{"error": "invalid_request"}\n'))
            spawn.assert_not_called()

    def test_launcher_maps_image_to_provider_and_xvfb(self):
        for provider in PROVIDERS:
            argv = build_argv(provider, url=URL, content_only=True, include_content=True,
                              budget_ms=700)
            argv.extend(['--mode', 'cold'])
            env = {'HOME': '/custom', 'MARKER': 'kept', 'ABG_PROVIDER': 'wrong'}
            with patch.object(oneshot.subprocess, 'Popen', return_value=process()) as spawn:
                result = oneshot.LocalLauncher().run(argv, 0.7, env=env)
            actual, = spawn.call_args.args
            prefix = ['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24'] if provider.kind == 'browser' else []
            expected = prefix + ['python3', '/opt/abg/probe.py', URL, '--content-only',
                                 '--include-content', '--budget-ms', '700', '--mode', 'cold']
            self.assertEqual(actual, expected)
            self.assertEqual(spawn.call_args.kwargs['env'],
                             dict(env, ABG_PROVIDER=provider.name))
            self.assertEqual(env['ABG_PROVIDER'], 'wrong')
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(result[0], 0)
            self.assertEqual(result[2], 'probe diagnostic')
        with patch.object(oneshot.subprocess, 'Popen') as spawn:
            with self.assertRaises(ValueError):
                oneshot.LocalLauncher().run(['docker', 'run', 'unknown:image', URL], 1)
            spawn.assert_not_called()
        with patch.dict(os.environ, {'MARKER': 'inherited'}), patch.object(
                oneshot.subprocess, 'Popen', return_value=process()) as spawn:
            oneshot.LocalLauncher().run(['docker', 'run', by_name('curl_cffi').image, URL], 1)
            self.assertEqual(spawn.call_args.kwargs['env']['MARKER'], 'inherited')

    def test_launcher_timeout_kills_process_group(self):
        proc = process()
        expired = subprocess.TimeoutExpired(['probe'], 0.1)
        proc.communicate.side_effect = [expired, ('partial', 'diagnostic')]
        with patch.object(oneshot.subprocess, 'Popen', return_value=proc), patch.object(
                oneshot.os, 'killpg') as killpg:
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                oneshot.LocalLauncher().run(['docker', 'run', by_name('patchright').image, URL], 0.1)
        self.assertEqual(killpg.call_args_list, [call(proc.pid, signal.SIGKILL)])
        self.assertIs(raised.exception, expired)
        self.assertEqual(proc.communicate.call_args_list, [call(timeout=0.1), call()])
        proc.communicate.side_effect = [expired, ('', '')]
        with patch.object(oneshot.subprocess, 'Popen', return_value=proc), patch.object(
                oneshot.os, 'killpg', side_effect=ProcessLookupError):
            with self.assertRaises(subprocess.TimeoutExpired):
                oneshot.LocalLauncher().run(['docker', 'run', by_name('patchright').image, URL], 0.1)

    def test_proxy_environment_not_forwarded(self):
        proxies = {variant: 'http://127.0.0.1:9'
                   for name in ('http_proxy', 'https_proxy', 'all_proxy', 'ftp_proxy', 'no_proxy')
                   for variant in (name, name.upper(), name.title())}
        env = dict(proxies, HOME='/custom', MARKER='kept', ABG_PROXY='http://gateway:8080')
        expected = dict(HOME='/custom', MARKER='kept', ABG_PROXY='http://gateway:8080',
                        ABG_PROVIDER='curl_cffi')
        forwarded = []
        argv = ['docker', 'run', by_name('curl_cffi').image, URL]
        with patch.dict(os.environ, env, clear=True), patch.object(
                oneshot.subprocess, 'Popen', return_value=process()) as spawn, patch.object(
                oneshot.signal, 'signal') as install:
            for supplied in (None, env):
                oneshot.LocalLauncher().run(argv, 1, env=supplied)
                forwarded.append(spawn.call_args.kwargs['env'])
            install.assert_not_called()
            self.assertEqual(dict(os.environ), env)
        self.assertEqual(forwarded, [expected, expected])
        self.assertTrue(all(env[name] == value for name, value in proxies.items()))

    def test_signal_kills_active_probe_groups(self):
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
        previous = {sig: signal.getsignal(sig) for sig in signals}
        observed, outcomes, restored = [], [], []
        for sig in signals:
            for missing in (False, True):
                outer, inner = process(), process()
                inner.pid = outer.pid + 1
                payload = inner.communicate.return_value

                def interrupt(**kwargs):
                    handler = signal.getsignal(sig)
                    if handler is not previous[sig] and callable(handler):
                        handler(sig, None)
                    return payload

                def nested(**kwargs):
                    return launcher.run(['docker', 'run', by_name('patchright').image, URL], 1)[1:]

                launcher = oneshot.LocalLauncher()
                outer.communicate.side_effect = nested
                inner.communicate.side_effect = interrupt
                with patch.object(oneshot, 'LocalLauncher', return_value=launcher), patch.object(
                        oneshot.subprocess, 'Popen', side_effect=[outer, inner]), patch.object(
                        oneshot.os, 'killpg', side_effect=ProcessLookupError if missing else None) as killpg:
                    try:
                        outcomes.append(invoke([URL]))
                        observed.append(sorted(killpg.call_args_list, key=lambda c: c.args[0]))
                        restored.append({s: signal.getsignal(s) for s in signals})
                    finally:
                        for signum, handler in previous.items():
                            signal.signal(signum, handler)
        expected = [call(12345, signal.SIGKILL), call(12346, signal.SIGKILL)]
        self.assertEqual(observed, [expected] * 6)
        self.assertEqual(outcomes, [(4, '', '{"error": "interrupted"}\n')] * 6)
        self.assertEqual(restored, [previous] * 6)
        with patch.object(oneshot.subprocess, 'Popen', return_value=process()):
            self.assertEqual(invoke([URL])[0], 0)
        self.assertEqual({s: signal.getsignal(s) for s in signals}, previous)
        with patch.object(oneshot.subprocess, 'Popen', side_effect=RuntimeError):
            self.assertEqual(invoke([URL])[0], 3)
        self.assertEqual({s: signal.getsignal(s) for s in signals}, previous)

        # A signal can arrive after fork, before Popen returns the child's PID.
        proc = process()

        def interrupted_spawn(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return proc

        with patch.object(oneshot.subprocess, 'Popen', side_effect=interrupted_spawn), patch.object(
                oneshot.os, 'killpg') as killpg:
            self.assertEqual(invoke([URL]), (4, '', '{"error": "interrupted"}\n'))
            killpg.assert_called_once_with(proc.pid, signal.SIGKILL)
            proc.communicate.assert_not_called()
            proc.wait.assert_called_once_with()
        self.assertEqual({s: signal.getsignal(s) for s in signals}, previous)

        def interrupted_spawn_failure(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            raise OSError('spawn failed after interruption')

        with patch.object(oneshot.subprocess, 'Popen', side_effect=interrupted_spawn_failure):
            self.assertEqual(invoke([URL]), (4, '', '{"error": "interrupted"}\n'))
        self.assertEqual({s: signal.getsignal(s) for s in signals}, previous)

    def test_direct_only_request(self):
        for flags, allow, budget, expected in [([], True, 30000, None),
                (['--no-browser', '--budget-ms', '120000', '--expected-text', 'Hello'],
                 False, 120000, 'Hello')]:
            with patch.object(oneshot, 'plan_product', wraps=plan_product) as validate, patch.object(
                    oneshot.subprocess, 'Popen', return_value=process(403)) as spawn:
                rc, out, err = invoke([URL, *flags])
            self.assertEqual(rc, 1)
            request, = validate.call_args.args
            self.assertEqual((request.url, request.max_age_hours, request.egress_profiles,
                              request.allow_browser, request.budget_ms, request.expected_text),
                             (URL, 0, (), allow, budget, expected))
            attempts = json.loads(out)['attempts']
            self.assertEqual([a['egress_profile'] for a in attempts], ['direct'] * len(attempts))
            self.assertEqual([a['provider'] for a in attempts],
                             ['curl_cffi', 'patchright', 'scrapling'] if allow else ['curl_cffi'])
            self.assertEqual(spawn.call_count, len(attempts))


if __name__ == '__main__':
    unittest.main()
