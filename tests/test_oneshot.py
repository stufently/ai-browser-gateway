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
