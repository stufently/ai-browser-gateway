import json
import subprocess
import unittest

from bench.models import FailureReason
from bench.providers.registry import by_name
from bench.runner.execute import execute_plan
from bench.runner.matrix import build_plan
from bench.runner.record import from_jsonl_line, to_jsonl_line
from tests.m2_helpers import FakeLauncher, output, payload

CELLS = {'target:x': {'url': 'https://example.invalid/', 'sentinel': 'S'}}


class ExecuteTests(unittest.TestCase):
    def plan(self, name='curl', cold=1, warm=0):
        return build_plan([by_name(name)], CELLS, cold=cold, warm=warm)

    def test_failed_exit_is_a_record(self):
        records = execute_plan(self.plan(), launcher=FakeLauncher((1, '', 'boom')), cells=CELLS, env={})
        self.assertFalse(records[0].success)
        self.assertEqual(records[0].error_type, FailureReason.provider_error)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].egress_ip, 'unknown')

    def test_success_mapping_and_roundtrip(self):
        launcher = FakeLauncher(output(provider_version='observed-version'))
        records = execute_plan(self.plan(), launcher=launcher, cells=CELLS,
                               env={'kernel': 'observed-kernel'}, timeout=60)
        rec = records[0]
        self.assertTrue(rec.success)
        self.assertTrue(rec.sentinel_found)
        self.assertEqual(rec.error_type, FailureReason.none)
        self.assertEqual(rec.target, 'x')
        self.assertIsNone(rec.scenario)
        self.assertEqual(rec.kernel, 'observed-kernel')
        self.assertEqual(rec.provider_version, 'observed-version')
        self.assertEqual(rec.image_version, 'abg-curl:m2')
        self.assertEqual(from_jsonl_line(to_jsonl_line(rec)), rec)
        self.assertEqual(launcher.calls[0][1], 60)
        self.assertEqual(launcher.calls[0][0][-2:], ['--mode', 'cold'])

    def test_failures_do_not_abort_later_items(self):
        launcher = FakeLauncher((0, '', ''), (0, '{broken', ''),
                                subprocess.TimeoutExpired('docker', 1), OSError('missing'), output())
        records = execute_plan(self.plan(cold=5), launcher=launcher, cells=CELLS, env={})
        self.assertEqual([r.success for r in records], [False] * 4 + [True])
        self.assertEqual(records[2].error_type, FailureReason.timeout)
        self.assertEqual(records[3].error_type, FailureReason.provider_error)

    def test_m1_success_rule_and_error_precedence(self):
        cases = [({'sentinel': False}, FailureReason.content_missing),
                 ({'status': 403}, FailureReason.http_403),
                 ({'ok': False, 'status': 403}, FailureReason.http_403),
                 ({'ok': False, 'sentinel': False}, FailureReason.content_missing),
                 ({'status': 429}, FailureReason.http_429),
                 ({'status': 503}, FailureReason.http_5xx),
                 ({'ok': False, 'err': 'timeout'}, FailureReason.timeout),
                 ({'ok': False, 'err': 'browser exploded'}, FailureReason.provider_error),
                 ({'ok': False}, FailureReason.provider_error)]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                rec = execute_plan(self.plan(), launcher=FakeLauncher(output(**changes)), cells=CELLS, env={})[0]
                self.assertFalse(rec.success)
                self.assertEqual(rec.error_type, reason)

    def test_malformed_types_become_provider_failure(self):
        malformed = [{}, payload(sentinel='yes'), payload(elapsed_ms=-1),
                     payload(peak_rss_mb=float('nan')), payload(status='200'),
                     payload(ok='true'), payload(challenge='bogus'), payload(bytes=True)]
        for value in malformed:
            with self.subTest(value=value):
                rec = execute_plan(self.plan(), launcher=FakeLauncher((0, json.dumps(value), '')),
                                   cells=CELLS, env={})[0]
                self.assertFalse(rec.success)
                self.assertEqual(rec.error_type, FailureReason.provider_error)

    def test_oversized_numeric_output_does_not_abort_plan(self):
        launcher = FakeLauncher(output(elapsed_ms=10**400), output())
        records = execute_plan(self.plan(cold=2), launcher=launcher, cells=CELLS, env={})
        self.assertEqual([r.success for r in records], [False, True])
        self.assertEqual(records[0].error_type, FailureReason.provider_error)

    def test_modes_and_local_network(self):
        cells = {'scenario:static': {'url': 'http://127.0.0.1:8000/static', 'sentinel': 'S'}}
        plan = build_plan([by_name('playwright')], cells, cold=1, warm=1)
        launcher = FakeLauncher(output(), output())
        records = execute_plan(plan, launcher=launcher, cells=cells, env={})
        self.assertEqual([r.mode for r in records], ['cold', 'warm'])
        for (argv, _), mode in zip(launcher.calls, ('cold', 'warm')):
            self.assertEqual(argv[-2:], ['--mode', mode])
            self.assertEqual(argv[argv.index('--network') + 1], 'host')
        self.assertEqual(records[0].scenario, 'static')

    def test_pause_before_repeated_host_including_failed_requests(self):
        cells = {f'target:{i}': {'url': url, 'sentinel': 'S'} for i, url in enumerate([
            'https://same.invalid/a', 'https://else.invalid/', 'https://same.invalid/b'])}
        events = []
        class Launcher:
            def run(self, argv, timeout):
                events.append('run')
                return (1, '', 'failed')
        plan = build_plan([by_name('curl')], cells, cold=1, warm=0)
        execute_plan(plan, launcher=Launcher(), cells=cells, env={}, pause_s=20,
                     sleep=lambda seconds: events.append(seconds))
        self.assertEqual(events, ['run', 'run', 20, 'run'])

    def test_invalid_plan_inputs_fail_before_launch(self):
        launcher = FakeLauncher()
        for cells, pause in ((CELLS, -1), ({'target:x': {'url': 'u', 'sentinel': ''}}, 0)):
            with self.subTest(cells=cells), self.assertRaises(ValueError):
                execute_plan(self.plan(), launcher=launcher, cells=cells, env={}, pause_s=pause)
        self.assertEqual(launcher.calls, [])
