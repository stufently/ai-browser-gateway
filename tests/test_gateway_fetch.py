"""BenchFetcher and fetch_page contract tests; launchers are fakes."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.escalate import Step
from bench.models import FailureReason, FetchResult
from bench.providers.registry import by_name
from bench.runner.execute import DockerLauncher, execute_plan, fetch_page
from bench.runner.matrix import PlanItem
from bench.runner.record import to_jsonl_line
from gateway.engine import run as gateway_run
from gateway.fetch import BenchFetcher
from gateway.models import GatewayRequest, PlanStep
from tests.m2_helpers import FakeLauncher, output
from tests.probe_m9_transport import (
    ProbeLauncher,
    _budget_argument,
    _mounts,
    _probe_payload,
)

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / 'bench' / 'providers' / 'docker' / 'probe.py'
CELLS = {'target:x': {'url': 'https://example.invalid/', 'sentinel': 'S'}}


class FetchPageContractTests(unittest.TestCase):
    def test_real_html_text_unicode_and_metrics(self):
        html = '<html><body>unicode ✨ &copy; unique-marker-ω</body></html>'
        payload = _probe_payload(
            html=html, text='unicode ✨ © unique-marker-ω',
            final_url='https://final.invalid/page', elapsed_ms=11, startup_ms=2,
            cpu_ms=3, peak_rss_mb=1.5, redirects=1, bytes=len(html.encode()),
        )
        launcher = ProbeLauncher((0, json.dumps(payload), ''))
        result, age = fetch_page(
            'curl', url='https://example.invalid/page', sentinel='unique-marker-ω',
            budget_ms=900, launcher=launcher,
        )
        self.assertIsInstance(result, FetchResult)
        self.assertIsNone(age)
        self.assertEqual(result.html, html)
        self.assertEqual(result.text, payload['text'])
        self.assertIn('unique-marker-ω', result.html)
        self.assertIn('unique-marker-ω', result.text)
        self.assertEqual(result.requested_url, 'https://example.invalid/page')
        self.assertEqual(result.final_url, 'https://final.invalid/page')
        self.assertEqual(result.error_type, FailureReason.none)
        self.assertEqual(result.elapsed_ms, 11)
        self.assertEqual(result.bytes_received, payload['bytes'])

    def test_fetch_page_keeps_probe_unicode_separators_through_one_line_json(self):
        from tests.test_probe import load_probe

        separators = '\u0085\u2028\u2029'
        html = f'<html><body>keep{separators}unique-marker-ω</body></html>'

        class BodyAdapter:
            version = 'probe-test'

            def start(self):
                return None

            def close(self):
                return None

            def navigate(self, url):
                return {
                    'status': 200, 'final_url': url, 'body': html,
                    'title': '', 'redirects': 0,
                }

        payload = load_probe().run_probe(
            'curl', 'https://example.invalid/page', 'unique-marker-ω',
            mode='cold', adapter_factory=lambda _: BodyAdapter(),
            metrics=lambda: (0, 0), include_content=True,
        )
        self.assertEqual(payload['html'], html)
        for char in separators:
            self.assertIn(char, payload['html'])
            self.assertIn(char, payload['text'])
        wire = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n'
        self.assertGreater(len(wire.splitlines()), 1)
        launcher = ProbeLauncher((0, wire, ''))
        result, _ = fetch_page(
            'curl', url='https://example.invalid/page', sentinel='unique-marker-ω',
            budget_ms=900, launcher=launcher,
        )
        self.assertEqual(result.html, html)
        self.assertEqual(result.text, payload['text'])
        for char in separators:
            self.assertIn(char, result.html)
            self.assertIn(char, result.text)
        self.assertEqual(result.error_type, FailureReason.none)

    def test_missing_body_is_provider_error_not_sentinel_success(self):
        payload = _probe_payload(sentinel=True, ok=True)
        del payload['html']
        del payload['text']
        launcher = ProbeLauncher((0, json.dumps(payload), ''))
        result, _ = fetch_page(
            'curl', url='https://example.invalid/', sentinel='probe-ok',
            budget_ms=200, launcher=launcher,
        )
        self.assertEqual(result.error_type, FailureReason.provider_error)
        self.assertEqual((result.html, result.text), ('', ''))

    def test_subsecond_budget_is_not_rounded_up(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ''))
        fetch_page(
            'curl', url='https://example.invalid/', sentinel='probe-ok',
            budget_ms=125, launcher=launcher,
        )
        argv, timeout, env = launcher.calls[0]
        self.assertAlmostEqual(timeout, 0.125, places=12)
        self.assertEqual(_budget_argument(argv), ['125'])
        self.assertIn('--include-content', argv)
        self.assertIsNotNone(env)

    def test_probe_mount_is_file_readonly_and_excludes_socket(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ''))
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as workdir:
            os.chdir(workdir)
            try:
                fetch_page(
                    'patchright', url='https://example.invalid/', sentinel='probe-ok',
                    budget_ms=400, launcher=launcher,
                )
            finally:
                os.chdir(cwd)
        argv = launcher.calls[0][0]
        mounts = _mounts(argv)
        self.assertTrue(mounts)
        for mount in mounts:
            source = str(mount['source'])
            self.assertTrue(os.path.isabs(source))
            self.assertTrue(mount['readonly'])
            self.assertNotIn('docker.sock', source)
            self.assertNotEqual(Path(source).resolve(), ROOT)
        joined = ' '.join(argv)
        self.assertNotIn('/var/run/docker.sock', joined)
        self.assertNotIn('docker.sock', joined)

    def test_invalid_inputs_do_not_launch_or_leak_values(self):
        launcher = ProbeLauncher()
        secret = 'https://user:pass@example.invalid/'
        with self.assertRaises(ValueError) as raised:
            fetch_page('curl', url=secret, sentinel='x', budget_ms=100, launcher=launcher)
        self.assertEqual(launcher.calls, [])
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn('user:pass', str(raised.exception))
        with self.assertRaises(ValueError):
            fetch_page('curl', url='https://example.invalid/', sentinel='x',
                       budget_ms=True, launcher=launcher)
        with self.assertRaises(ValueError):
            fetch_page('nope', url='https://example.invalid/', sentinel='x',
                       budget_ms=100, launcher=launcher)
        self.assertEqual(launcher.calls, [])

    def test_named_egress_without_url_and_rss_without_entrance_do_not_launch(self):
        launcher = ProbeLauncher()
        result, age = fetch_page(
            'rss', url='https://example.invalid/', sentinel='probe-ok',
            budget_ms=100, launcher=launcher,
        )
        self.assertEqual(result.error_type, FailureReason.not_measured)
        self.assertIsNone(age)
        result, age = fetch_page(
            'curl', url='https://example.invalid/', sentinel='probe-ok',
            budget_ms=100, launcher=launcher, egress=('gold', None),
        )
        self.assertEqual(result.error_type, FailureReason.not_measured)
        self.assertEqual(launcher.calls, [])


class EnvIsolationTests(unittest.TestCase):
    def test_parallel_profiles_do_not_share_or_mutate_environ(self):
        profiles = {
            'gold': 'http://user:pass@gold-proxy:8080',
            'silver': 'http://user:pass@silver-proxy:8080',
        }
        barrier = threading.Barrier(3)
        observed_env = {}
        observed_argv = {}
        lock = threading.Lock()

        class BarrierLauncher(ProbeLauncher):
            def run(self, argv, timeout, *, env=None):
                barrier.wait(timeout=2)
                name = threading.current_thread().name
                with lock:
                    observed_env[name] = None if env is None else dict(env)
                    observed_argv[name] = list(argv)
                return super().run(argv, timeout, env=env)

        launcher = BarrierLauncher(*[(0, json.dumps(_probe_payload()), '')] * 3)
        fetcher = BenchFetcher(
            'https://example.invalid/', 'probe-ok', profiles=profiles, launcher=launcher,
        )
        previous = os.environ.get('ABG_PROXY')
        os.environ['ABG_PROXY'] = 'http://global.proxy:8080'
        expected = dict(os.environ)
        errors = []

        def call(profile):
            try:
                fetcher(PlanStep('curl', profile, 'http' if profile == 'direct' else 'egress'), 300)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(name='direct', target=call, args=('direct',), daemon=True),
            threading.Thread(name='gold', target=call, args=('gold',), daemon=True),
            threading.Thread(name='silver', target=call, args=('silver',), daemon=True),
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            after = dict(os.environ)
        finally:
            if previous is None:
                os.environ.pop('ABG_PROXY', None)
            else:
                os.environ['ABG_PROXY'] = previous
        self.assertFalse(errors)
        self.assertEqual(after, expected)
        self.assertNotIn('ABG_PROXY', observed_env['direct'] or {})
        self.assertEqual(observed_env['gold']['ABG_PROXY'], profiles['gold'])
        self.assertEqual(observed_env['silver']['ABG_PROXY'], profiles['silver'])
        for argv in observed_argv.values():
            self.assertFalse(any('user:pass@' in part for part in argv))
            self.assertFalse(any(part.startswith('ABG_PROXY=') for part in argv))


class BenchFetcherTests(unittest.TestCase):
    def test_copies_maps_and_keeps_requested_url_for_entrance(self):
        payload = _probe_payload(entrance_age_hours=4.0, final_url='https://feed.invalid/item')
        launcher = ProbeLauncher((0, json.dumps(payload), ''))
        entrances = {'rss': 'https://feed.invalid/original'}
        profiles = {'gold': 'http://gold.invalid:1'}
        fetcher = BenchFetcher(
            'https://example.invalid/page', 'probe-ok',
            entrances=entrances, profiles=profiles, launcher=launcher, network='host',
        )
        entrances['rss'] = 'https://changed.invalid/'
        profiles['gold'] = 'http://changed.invalid/'
        reply = fetcher(PlanStep('rss', 'gold', 'entrance'), 250)
        argv, _, env = launcher.calls[0]
        self.assertIn('https://feed.invalid/original', argv)
        self.assertNotIn('https://changed.invalid/', argv)
        self.assertEqual(env.get('ABG_PROXY'), 'http://gold.invalid:1')
        self.assertEqual(reply.result.requested_url, 'https://example.invalid/page')
        self.assertEqual(reply.result.final_url, payload['final_url'])
        self.assertEqual(reply.age_hours, 4.0)
        self.assertTrue('--network=host' in argv or argv[argv.index('--network') + 1] == 'host')

    def test_unknown_profile_is_not_direct(self):
        launcher = ProbeLauncher()
        fetcher = BenchFetcher(
            'https://example.invalid/', 'probe-ok',
            profiles={'gold': 'http://proxy'}, launcher=launcher,
        )
        reply = fetcher(PlanStep('curl', 'silver', 'egress'), 100)
        self.assertEqual(reply.result.error_type, FailureReason.not_measured)
        self.assertEqual(launcher.calls, [])

    def test_gateway_403_with_marker_is_not_success(self):
        payload = _probe_payload(
            ok=False, status=403,
            html='<html><body>M9_SENTINEL visible-marker</body></html>',
            text='M9_SENTINEL visible-marker',
        )
        launcher = ProbeLauncher((0, json.dumps(payload), ''))
        out = gateway_run(
            GatewayRequest(url='https://example.invalid/page', sentinel='M9_SENTINEL',
                           budget_ms=1000),
            BenchFetcher('https://example.invalid/page', 'M9_SENTINEL', launcher=launcher),
        )
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.http_403)
        self.assertEqual(out.step, Step.change_egress)
        self.assertEqual(out.html, '')
        self.assertEqual(out.text, '')


class BenchmarkIsolationTests(unittest.TestCase):
    def test_execute_plan_still_omits_page_body_and_content_flag(self):
        payload = _probe_payload()
        payload.pop('html')
        payload.pop('text')
        launcher = FakeLauncher((0, json.dumps(payload), ''))
        records = execute_plan(
            [PlanItem('curl', 'target:x', 'cold', 0)],
            launcher=launcher, cells=CELLS, env={},
        )
        self.assertTrue(records[0].success)
        wire = json.loads(to_jsonl_line(records[0]))
        self.assertNotIn('html', wire)
        self.assertNotIn('text', wire)
        self.assertNotIn('--include-content', launcher.calls[0][0])

    def test_dockerlauncher_legacy_call_omits_env_kwarg(self):
        command = ['docker', 'run', by_name('curl').image, 'https://example.invalid', 'S']
        result = subprocess.CompletedProcess(command, 0, '', '')
        with patch('subprocess.run', return_value=result) as run:
            DockerLauncher().run(command, 1)
        self.assertNotIn('env', run.call_args.kwargs)
        with patch('subprocess.run', return_value=result) as run:
            DockerLauncher().run(command, timeout=1, env={'ABG_PROXY': 'http://p'})
        self.assertEqual(run.call_args.kwargs['env'], {'ABG_PROXY': 'http://p'})


class LiveLauncherLabelTests(unittest.TestCase):
    def test_labeled_launcher_wraps_real_dockerlauncher_and_labels_argv(self):
        from tests.live_m9_fetch import LabeledDockerLauncher, inject_run_labels

        self.assertIsInstance(LabeledDockerLauncher('run-x').inner, DockerLauncher)
        argv = ['docker', 'run', '--rm', 'abg-curl:m2', 'https://example.invalid/', 'S']
        labeled = inject_run_labels(argv, 'run-x')
        self.assertEqual(labeled[:2], ['docker', 'run'])
        self.assertEqual(labeled[labeled.index('--label') + 1], 'abg-m9-run=run-x')
        self.assertIn('abg-m9-role=provider', labeled)
        self.assertEqual(argv[:2], ['docker', 'run'])
        self.assertNotIn('abg-m9-role=provider', argv)

        class Inner:
            def run(self, argv, timeout, *, env=None):
                self.seen = list(argv)
                self.timeout = timeout
                self.env = env
                return (0, json.dumps(_probe_payload()), '')

        inner = Inner()
        launcher = LabeledDockerLauncher('run-x', inner=inner)
        result, _ = fetch_page(
            'curl', url='https://example.invalid/', sentinel='probe-ok',
            budget_ms=200, launcher=launcher,
        )
        self.assertEqual(result.error_type, FailureReason.none)
        self.assertIn('--label', inner.seen)
        self.assertEqual(inner.seen[inner.seen.index('--label') + 1], 'abg-m9-run=run-x')
        self.assertIn('abg-m9-role=provider', inner.seen)
        self.assertLess(inner.seen.index('--label'), inner.seen.index(by_name('curl').image))

    def test_leftover_ids_do_not_treat_failed_ps_or_empty_stdout_as_clean(self):
        from tests.live_m9_fetch import leftover_ids

        with self.assertRaises(RuntimeError):
            leftover_ids(subprocess.CompletedProcess(['docker', 'ps'], 1, '', 'boom'))
        with self.assertRaises(RuntimeError):
            leftover_ids(subprocess.CompletedProcess(['docker', 'ps'], 2, '', ''))
        self.assertEqual(
            leftover_ids(subprocess.CompletedProcess(['docker', 'ps'], 0, '', '')),
            [],
        )
        self.assertEqual(
            leftover_ids(subprocess.CompletedProcess(['docker', 'ps'], 0, 'cid1\ncid2\n', '')),
            ['cid1', 'cid2'],
        )

    def test_live_browser_budget_stays_at_cold_start_limit(self):
        from tests.live_m9_fetch import PROVIDER_BUDGETS

        budgets = dict(PROVIDER_BUDGETS)
        self.assertEqual(budgets['patchright'], 30_000)
        self.assertEqual(budgets['scrapling'], 30_000)
        self.assertLessEqual(max(budgets.values()), 30_000)


if __name__ == '__main__':
    unittest.main()
