import math
import statistics
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from bench.models import FailureReason
from bench.report.build import build_report
from bench.report.coverage import incremental
from bench.runner.record import to_jsonl_line
from tests.m2_helpers import observed_record


class ReportBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fixture.jsonl'
        self.records = [observed_record(), observed_record('playwright', mode='warm')]
        self.write(self.records)

    def write(self, records):
        self.path.write_text(''.join(to_jsonl_line(r) for r in records), encoding='utf-8')

    def test_metadata_matrix_metrics_and_coverage(self):
        text = build_report(self.path, order=['curl', 'playwright'], unmeasured=['paid-api'])
        for expected in ('kernel', 'local-test-observation', 'egress_ip', 'unknown', 'target:x',
                         'Медиана', 'p95', 'RSS', 'Incremental', 'не измерено', 'paid-api'):
            self.assertIn(expected, text)
        self.assertIn('| curl | 1/1 |', text)
        self.assertIn('| playwright | 1/1 |', text)
        rec = self.records[0]
        self.assertIn(f'| curl | cold | 1 | {rec.elapsed_ms:.2f} | {rec.elapsed_ms:.2f} | {rec.peak_rss_mb:.2f} |', text)
        self.assertIn('| playwright | warm |', text)

    def test_passes_a_stream_to_coverage(self):
        observed = {}
        def consume(records, order):
            observed['iterator'] = iter(records) is records
            return incremental(records, order)
        with patch('bench.report.build.incremental', side_effect=consume):
            build_report(self.path, order=['curl', 'playwright'])
        self.assertTrue(observed['iterator'])

    def test_threshold_changes_coverage_decision(self):
        # Both providers solve x, neither solves y: curl adds 1/2, with no unique cell.
        self.write(self.records + [replace(self.records[0], cell='target:y', target='y',
                                          success=False, sentinel_found=False,
                                          error_type=FailureReason.content_missing)])
        for threshold, expected in (
            (0.5, '| curl | 1 | 1 | 0 | оставить: incremental 1/2 = 0.5000 >= 0.5 |'),
            (0.75, '| curl | 1 | 1 | 0 | исключить: incremental 0.5000 < 0.75 and unique = 0 |'),
        ):
            with self.subTest(threshold=threshold):
                text = build_report(self.path, order=['curl', 'playwright'], threshold=threshold)
                self.assertIn(expected, text)

    def test_unknown_even_failed_provider_rejected(self):
        self.write([replace(self.records[0], provider='ghost', success=False,
                            error_type=FailureReason.provider_error)])
        with self.assertRaisesRegex(ValueError, 'ghost'):
            build_report(self.path, order=['curl'])

    def test_median_and_nearest_rank_p95_use_observed_values(self):
        records = [observed_record() for _ in range(7)]
        self.write(records)
        values = sorted(r.elapsed_ms for r in records)
        text = build_report(self.path, order=['curl'])
        self.assertIn(f'| {statistics.median(values):.2f} | {values[math.ceil(.95 * len(values)) - 1]:.2f} |', text)
        self.assertIn(f'{max(r.peak_rss_mb for r in records):.2f}', text)

    def test_failed_launch_metrics_unavailable_and_cell_still_counted(self):
        from bench.runner.execute import execute_plan
        from bench.runner.matrix import PlanItem
        from tests.m2_helpers import FakeLauncher
        records = execute_plan([PlanItem('curl', 'target:failed', 'cold', 0)],
                               launcher=FakeLauncher((1, '', 'boom')),
                               cells={'target:failed': {'url': 'https://example.invalid/', 'sentinel': 'S'}}, env={})
        self.write(records)
        text = build_report(self.path, order=['curl', 'playwright'])
        self.assertIn('| curl | 0/1 |', text)
        self.assertIn('| playwright | не измерено |', text)
        self.assertIn('| curl | cold | 0 | unknown | unknown | unknown |', text)
        self.assertIn('0/1', text)

    def test_empty_and_mixed_environments(self):
        self.write([])
        self.assertIn('unknown', build_report(self.path, order=['curl']))
        self.write([self.records[0], replace(self.records[1], egress_ip='observed-other-egress')])
        self.assertIn('observed-other-egress', build_report(self.path, order=['curl', 'playwright']))

    def test_egress_profile_is_in_metadata_and_url_is_not(self):
        from tests.m4_helpers import record
        gold = record('curl', 'target:a', egress_profile='gold')
        self.write([gold])
        text = build_report(self.path, order=['curl'])
        self.assertIn('egress_profile', text)
        self.assertIn('gold', text)
        self.assertNotIn('proxy.invalid', text)
        self.assertNotIn('pass', text)
        self.assertNotIn('@', text.split('gold', 1)[-1] if 'gold' in text else text)

    def test_environment_error_metrics_are_unavailable(self):
        from bench.runner.execute import execute_plan
        from bench.runner.matrix import PlanItem
        from tests.m2_helpers import FakeLauncher
        records = execute_plan(
            [PlanItem('curl', 'target:failed', 'cold', 0)],
            launcher=FakeLauncher((125, '', 'image missing')),
            cells={'target:failed': {'url': 'https://example.invalid/', 'sentinel': 'S'}},
            env={},
        )
        self.assertEqual(records[0].error_type, FailureReason.environment_error)
        self.write(records)
        text = build_report(self.path, order=['curl'])
        self.assertIn('| curl | 0/1 |', text)
        self.assertIn('| curl | cold | 0 | unknown | unknown | unknown |', text)

    def test_bad_json_line_context(self):
        self.path.write_text(to_jsonl_line(self.records[0]) + '{broken\n')
        with self.assertRaisesRegex(ValueError, 'line 2'):
            build_report(self.path, order=['curl'])
