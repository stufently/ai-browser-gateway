"""M4 contracts using synthetic data and fake external boundaries only."""

import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from bench.cli import main
from bench.models import FailureReason
from bench.providers.registry import by_name
from bench.report.build import build_report
from bench.report.coverage import incremental
from bench.runner.execute import execute_plan
from bench.runner.matrix import build_plan
from bench.runner.record import from_jsonl_line, to_jsonl_line
from tests.m2_helpers import FakeLauncher, output
from tests.m4_helpers import record
from tests.test_probe import load_probe


NOW = datetime(2026, 9, 7, 2, tzinfo=timezone.utc)
TARGET = 'https://example.invalid/path?a=1&b=2'
SNAPSHOT = 'http://web.archive.org/web/20260906171542/https://www.bizprofile.net/'
FEED = 'https://lowendtalk.com/categories/offers/feed.rss'
SENTINEL = 'Offers — LowEndTalk'


def archive_payload(**changes):
    closest = dict(status='200', available=True, url=SNAPSHOT, timestamp='20260906171542')
    closest.update(changes)
    return {'url': TARGET, 'archived_snapshots': {'closest': closest}}


class Response(io.BytesIO):
    def __init__(self, body, url=TARGET, status=200):
        super().__init__(body.encode('utf-8'))
        self.status = status
        self.url = url
        self.headers = {}

    def geturl(self):
        return self.url


class AgeRecordTests(unittest.TestCase):
    def test_unknown_age_roundtrip(self):
        got = from_jsonl_line(to_jsonl_line(record('wayback', 'target:a', entrance_age_hours=None)))
        self.assertIsNone(got.entrance_age_hours)

    def test_zero_and_positive_age_roundtrip(self):
        for age in (0.0, 3.9):
            with self.subTest(age=age):
                line = to_jsonl_line(record('wayback', 'target:a', entrance_age_hours=age))
                self.assertEqual(from_jsonl_line(line).entrance_age_hours, age)

    def test_invalid_ages_rejected_on_both_jsonl_boundaries(self):
        for age in (-1, True, '3.9', [], float('nan'), float('inf')):
            with self.subTest(age=age):
                with self.assertRaisesRegex(ValueError, 'entrance_age_hours'):
                    to_jsonl_line(record('rss', 'target:a', entrance_age_hours=age))
                raw = json.loads(to_jsonl_line(record('rss', 'target:a')))
                raw['entrance_age_hours'] = age
                with self.assertRaisesRegex(ValueError, 'entrance_age_hours'):
                    from_jsonl_line(json.dumps(raw))

    def test_missing_age_is_rejected_like_other_jsonl_fields(self):
        raw = json.loads(to_jsonl_line(record('rss', 'target:a')))
        del raw['entrance_age_hours']
        self.assertIsNone(from_jsonl_line(json.dumps(raw)).entrance_age_hours)
        del raw['provider']
        with self.assertRaisesRegex(ValueError, 'provider'):
            from_jsonl_line(json.dumps(raw))


class EntranceCoverageTests(unittest.TestCase):
    def test_unmeasured_only_cell_is_excluded(self):
        records = [record('curl', 'target:a'),
                   record('rss', 'target:a', success=False, error_type=FailureReason.not_measured),
                   record('rss', 'target:b', success=False, error_type=FailureReason.not_measured)]
        self.assertEqual(len(records), 3)
        rows = incremental(records, ['curl', 'rss'])
        self.assertEqual(rows[0].total_cells, 1)
        self.assertEqual((rows[0].solved, rows[1].solved), (1, 0))

    def test_one_measured_failure_keeps_cell(self):
        records = [record('rss', 'target:a', success=False, error_type=FailureReason.not_measured),
                   record('rss', 'target:a', success=False), record('curl', 'target:b')]
        self.assertEqual(len(records), 3)
        rows = incremental(records, ['curl', 'rss'])
        self.assertEqual(rows[0].total_cells, 2)
        self.assertEqual((rows[0].incremental, rows[1].incremental), (1, 0))

    def test_nonempty_unmeasured_dataset_has_no_measured_cells(self):
        records = [record('rss', 'target:a', success=False, error_type=FailureReason.not_measured)]
        self.assertTrue(records)
        row = incremental(records, ['rss'])[0]
        self.assertEqual((row.total_cells, row.solved, row.incremental, row.unique), (0, 0, 0, 0))


class EntranceProbeTests(unittest.TestCase):
    def setUp(self):
        self.probe = load_probe()

    def run_with(self, provider, responses):
        with patch.object(self.probe, 'urlopen', side_effect=responses) as fetch, \
                patch.object(self.probe, '_utcnow', return_value=NOW):
            result = self.probe.run_probe(provider, TARGET, SENTINEL, mode='cold', metrics=lambda: (0, 0))
        return result, fetch

    def test_empty_archive_at_http_200_is_not_a_snapshot(self):
        got = self.probe.parse_wayback({'status': 200, 'archived_snapshots': {}})
        self.assertIsNone(got)

    def test_no_closest_is_not_a_snapshot(self):
        self.assertIsNone(self.probe.parse_wayback({'archived_snapshots': {'other': {}}}))
        self.assertIsNone(self.probe.parse_wayback({}))

    def test_snapshot_is_selected_from_closest_not_status(self):
        for status in ('200', '404'):
            with self.subTest(status=status):
                got = self.probe.parse_wayback(archive_payload(status=status))
                self.assertEqual(got, (SNAPSHOT, '20260906171542'))

    def test_malformed_snapshot_is_not_silently_absent(self):
        for payload in ([], {'archived_snapshots': []},
                        {'archived_snapshots': {'closest': {}}}, archive_payload(url=5)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.probe.parse_wayback(payload)

    def test_empty_snapshot_fields_are_rejected(self):
        for fields in ({'url': ''}, {'timestamp': ''}, {'url': '', 'timestamp': ''}):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    self.probe.parse_wayback(archive_payload(**fields))

    def test_future_snapshot_age_is_clamped(self):
        self.assertEqual(self.probe._age_hours(NOW + timedelta(hours=5), NOW), 0.0)
        self.assertEqual(self.probe._age_hours(NOW - timedelta(hours=5), NOW), 5.0)

    def test_wayback_fetches_snapshot_and_uses_timestamp_age(self):
        result, fetch = self.run_with('wayback', [Response(json.dumps(archive_payload())),
                                                 Response('<title>' + SENTINEL + '</title>', SNAPSHOT)])
        self.assertTrue(result['ok'])
        self.assertEqual(result['final_url'], SNAPSHOT)
        self.assertAlmostEqual(result['entrance_age_hours'], 8 + 44 / 60 + 18 / 3600)
        self.assertEqual(fetch.call_args_list[0].args[0].full_url,
                         'https://archive.org/wayback/available?url=https%3A%2F%2Fexample.invalid%2Fpath%3Fa%3D1%26b%3D2')
        self.assertEqual(fetch.call_args_list[1].args[0].full_url, SNAPSHOT)
        self.assertEqual(fetch.call_count, 2)

    def test_entrance_requests_carry_a_browser_user_agent(self):
        # Measured 07.09.2026: lowendtalk.com refuses "Python-urllib/3.14" with
        # 403 and serves the same feed to curl and to a browser string. The
        # library default would lose the one cell this entrance was added for.
        result, fetch = self.run_with('rss', [Response('<rss><channel><title>'
                                                      + SENTINEL + '</title></channel></rss>')])
        self.assertTrue(result['ok'])
        sent = fetch.call_args_list[0].args[0]
        # A bare URL string means no header was set at all: fail on the value,
        # not on an attribute error, so the reason for the failure stays legible.
        agent = getattr(sent, 'get_header', lambda name: None)('User-agent')
        self.assertEqual(agent, self.probe.ENTRANCE_USER_AGENT)
        self.assertNotIn('urllib', agent)

    def test_absent_snapshot_is_measured_content_missing(self):
        result, fetch = self.run_with('wayback', [Response('{"archived_snapshots": {}}')])
        self.assertEqual(result['err'], 'content_missing')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['entrance_age_hours'])
        self.assertEqual(fetch.call_count, 1)

    def test_malformed_json_and_timestamp_are_probe_failures(self):
        for body in ('{broken', '[]', json.dumps(archive_payload(timestamp='broken'))):
            with self.subTest(body=body):
                result, _ = self.run_with('wayback', [Response(body)])
                self.assertFalse(result['ok'])
                self.assertTrue(result['err'])
                self.assertNotEqual(result['err'], 'content_missing')
                self.assertIsNone(result['entrance_age_hours'])

    def test_rss_raw_xml_sentinel_and_latest_pubdate(self):
        xml = ('<rss><channel><title>' + SENTINEL + '</title>'
               '<pubDate>Sun, 06 Sep 2026 00:00:00 +0000</pubDate>'
               '<item><pubDate>Mon, 07 Sep 2026 03:00:00 +0200</pubDate></item>'
               '<item><pubDate>Sun, 06 Sep 2026 12:00:00 +0000</pubDate></item>'
               '</channel></rss>')
        result, _ = self.run_with('rss', [Response(xml, FEED)])
        self.assertTrue(result['sentinel'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['entrance_age_hours'], 1.0)
        self.assertEqual(result['bytes'], len(xml.encode()))

    def test_rss_without_pubdate_has_unknown_age(self):
        result, _ = self.run_with('rss', [Response('<rss><channel><title>' + SENTINEL + '</title></channel></rss>')])
        self.assertTrue(result['ok'])
        self.assertIsNone(result['entrance_age_hours'])

    def test_naive_pubdate_gives_no_age(self):
        xml = ('<rss><channel><title>' + SENTINEL + '</title>'
               '<item><pubDate>Mon, 07 Sep 2026 01:00:00</pubDate></item>'
               '</channel></rss>')
        result, _ = self.run_with('rss', [Response(xml, FEED)])
        self.assertTrue(result['ok'])
        self.assertIsNone(result['entrance_age_hours'])

    def test_invalid_pubdate_is_unknown_but_valid_date_still_used(self):
        for date, expected in (('broken', None), ('Mon, 07 Sep 2026 02:00:00 +0000', 0.0)):
            with self.subTest(date=date):
                xml = f'<rss><channel><title>{SENTINEL}</title><pubDate>invalid</pubDate><pubDate>{date}</pubDate></channel></rss>'
                result, _ = self.run_with('rss', [Response(xml)])
                self.assertTrue(result['ok'])
                self.assertEqual(result['entrance_age_hours'], expected)

    def test_malformed_xml_is_failure(self):
        result, _ = self.run_with('rss', [Response('<rss>' + SENTINEL)])
        self.assertFalse(result['ok'])
        self.assertTrue(result['err'])

    def test_http_failure_retains_status_and_challenge(self):
        for provider in ('rss', 'wayback'):
            with self.subTest(provider=provider):
                error = HTTPError(TARGET, 403, 'Forbidden', {}, io.BytesIO(b'Forbidden'))
                result, _ = self.run_with(provider, [error])
                self.assertFalse(result['ok'])
                self.assertEqual(result['status'], 403)
                self.assertEqual(result['challenge'], 'access_denied')

    def test_status_400_is_a_measured_refusal(self):
        discovery_url = 'https://archive.org/wayback/available?url=example.invalid'
        body = b'<html><title>Bad Request</title></html>'
        error = HTTPError(discovery_url, 400, 'Bad Request', {}, io.BytesIO(body))
        result, fetch = self.run_with('wayback', [error])
        self.assertEqual(result['status'], 400)
        self.assertFalse(result['ok'])
        self.assertEqual(result['final_url'], discovery_url)
        self.assertEqual(result['bytes'], len(body))
        self.assertEqual(result['err'], '')
        self.assertIsNone(result['entrance_age_hours'])
        self.assertEqual(fetch.call_count, 1)


class EntranceExecutionTests(unittest.TestCase):
    def execute(self, provider='rss', entrances=None, cell='target:a', launcher=None):
        cells = {cell: {'url': TARGET, 'sentinel': SENTINEL}}
        if entrances is not None:
            cells[cell]['entrances'] = entrances
        plan = build_plan([by_name(provider)], cells, cold=1, warm=0)
        launcher = launcher if launcher is not None else FakeLauncher(output())
        return execute_plan(plan, launcher=launcher, cells=cells, env={}), launcher

    def test_missing_rss_is_explicitly_unmeasured(self):
        records, _ = self.execute()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].success)
        self.assertEqual(records[0].error_type, FailureReason.not_measured)
        self.assertIsNone(records[0].entrance_age_hours)

    def test_missing_rss_never_launches(self):
        records, launcher = self.execute()
        self.assertEqual(launcher.calls, [])
        self.assertEqual(len(records), 1)

    def test_scenarios_never_launch_any_entrance(self):
        for provider in ('rss', 'wayback'):
            with self.subTest(provider=provider):
                records, launcher = self.execute(provider, cell='scenario:static')
                self.assertEqual(launcher.calls, [])
                self.assertEqual(records[0].error_type, FailureReason.not_measured)

    def test_configured_rss_uses_feed_url_and_preserves_age(self):
        records, launcher = self.execute(entrances={'rss': FEED}, launcher=FakeLauncher(output(entrance_age_hours=3.9)))
        self.assertEqual(launcher.calls[0][0][-4:], [FEED, SENTINEL, '--mode', 'cold'])
        self.assertTrue(records[0].success)
        self.assertEqual(records[0].entrance_age_hours, 3.9)

    def test_wayback_uses_target_without_configuration(self):
        records, launcher = self.execute('wayback', launcher=FakeLauncher(output(entrance_age_hours=0.0)))
        self.assertEqual(launcher.calls[0][0][-4:], [TARGET, SENTINEL, '--mode', 'cold'])
        self.assertEqual(records[0].entrance_age_hours, 0.0)
        self.assertTrue(records[0].success)

    def test_bad_probe_age_is_provider_error(self):
        for age in (-1, True, '2', float('nan'), float('inf')):
            with self.subTest(age=age):
                records, _ = self.execute('wayback', launcher=FakeLauncher(output(entrance_age_hours=age)))
                self.assertEqual(records[0].error_type, FailureReason.provider_error)
                self.assertIsNone(records[0].entrance_age_hours)

    def test_cli_reads_only_verified_feed_into_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.jsonl'
            launcher = FakeLauncher(output(final_url=FEED, entrance_age_hours=1.0))
            rc = main(['run', '--providers', 'rss', '--targets', 'bench/targets/targets.toml',
                       '--output', str(path)], launcher=launcher, reader=lambda _: 'test', sleep=lambda _: None)
            records = [from_jsonl_line(line) for line in path.read_text().splitlines()]
        self.assertEqual(rc, 0)
        self.assertGreater(len(records), 1)
        self.assertEqual(len(launcher.calls), 1)
        self.assertEqual(launcher.calls[0][0][-4:], [FEED, SENTINEL, '--mode', 'cold'])
        measured = [r.target for r in records if r.error_type != FailureReason.not_measured]
        self.assertEqual(measured, ['cf-lowendtalk'])


class EntranceReportTests(unittest.TestCase):
    def report(self, records, order):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.jsonl'
            path.write_text(''.join(to_jsonl_line(r) for r in records))
            return build_report(path, order=order)

    def test_unmeasured_never_becomes_numeric_failure_or_metric(self):
        text = self.report([record('curl', 'target:a'),
                            record('rss', 'target:a', success=False, error_type=FailureReason.not_measured)],
                           ['curl', 'rss'])
        self.assertIn('| rss | не измерено |', text)
        self.assertNotIn('| rss | 0/1 |', text)
        self.assertIn('| rss | cold | не измерено | не измерено | не измерено | не измерено |', text)
        self.assertIn('| rss | не измерено | не измерено | не измерено | не измерено |', text)

    def test_mixed_attempts_count_only_measured_and_still_show_unmeasured(self):
        text = self.report([record('rss', 'target:a'),
                            record('rss', 'target:a', success=False, error_type=FailureReason.not_measured)], ['rss'])
        self.assertIn('| rss | 1/1; не измерено: 1 |', text)
        self.assertIn('| rss | cold | 1 |', text)

    def test_median_age_excludes_unknown_and_includes_zero(self):
        records = [record('wayback', 'target:a', entrance_age_hours=age) for age in (0.0, None, 2.0, 10.0)]
        records += [record('wayback', 'target:b', success=False, error_type=FailureReason.not_measured,
                           entrance_age_hours=100.0)]
        text = self.report(records, ['wayback'])
        self.assertIn('Медианный возраст, ч', text)
        self.assertIn('| wayback | 2.00 |', text)

    def test_measured_unknown_age_does_not_become_zero(self):
        text = self.report([record('rss', 'target:a')], ['rss'])
        self.assertIn('| rss | unknown |', text)


if __name__ == '__main__':
    unittest.main()
