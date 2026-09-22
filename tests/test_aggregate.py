import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bench.cli import main
from bench.models import ChallengeType, FailureReason
from bench.report.aggregate import CLASS_PATTERN, build_aggregate, load_classes
from bench.runner.record import RunRecord, to_jsonl_line

EGRESS = 'egress-fixture'
ASN = 'asn-fixture'
HOSTS = {
    'shop-alpha': 'alpha-shop.invalid',
    'forum-beta': 'beta-forum.invalid',
    'forum-gamma': 'gamma-forum.invalid',
    'social-delta': 'delta-social.invalid',
}
CLASSES = {
    'shop-alpha': 'none',
    'forum-beta': 'cloudflare',
    'forum-gamma': 'cloudflare',
    'social-delta': 'login-wall',
}
SECRETS = (*HOSTS, *HOSTS.values(), EGRESS, ASN, 'target:')


def record(provider, target, success, error=FailureReason.none):
    if not success and error is FailureReason.none:
        error = FailureReason.http_403
    return RunRecord(
        provider=provider, provider_version='1', scenario=None, target=target,
        run_id=f'{provider}-{target}', mode='cold', success=success, sentinel_found=success,
        status=200 if success else 403, final_url=f'https://{HOSTS[target]}/',
        challenge_type=ChallengeType.none, elapsed_ms=10, startup_ms=1, cpu_ms=1,
        peak_rss_mb=1.0, bytes=100, redirects=0, error_type=error,
        date='2026-09-22T00:00:00+00:00', kernel='k', docker_version='d', image_version='i',
        egress_ip=EGRESS, asn=ASN, cell=f'target:{target}')


def scenario():
    return RunRecord(
        provider='curl', provider_version='1', scenario='static', target=None,
        run_id='scenario', mode='cold', success=True, sentinel_found=True, status=200,
        final_url='http://stand.invalid/static', challenge_type=ChallengeType.none,
        elapsed_ms=5, startup_ms=1, cpu_ms=1, peak_rss_mb=1.0, bytes=10, redirects=0,
        error_type=FailureReason.none, date='2026-09-22T00:00:00+00:00', kernel='k',
        docker_version='d', image_version='i', egress_ip=EGRESS, asn=ASN,
        cell='scenario:static')


def targets_toml(classes=CLASSES):
    return ''.join(
        f'[[target]]\nid = "{tid}"\nurl = "https://{HOSTS[tid]}/"\n'
        + (f'class = {json.dumps(klass)}\n' if klass is not None else '')
        + 'expect = "E"\n\n'
        for tid, klass in classes.items())


# Chosen so that "Any provider" differs from every single provider column:
# cloudflare is taken by patchright on one target and by scrapling on the other.
RECORDS = [
    record('curl_cffi', 'shop-alpha', True),
    record('curl_cffi', 'forum-beta', False),
    record('curl_cffi', 'forum-gamma', False),
    record('curl_cffi', 'social-delta', False, FailureReason.not_measured),
    record('patchright', 'shop-alpha', False, FailureReason.not_measured),
    record('patchright', 'forum-beta', True),
    record('patchright', 'forum-gamma', False, FailureReason.timeout),
    record('patchright', 'social-delta', False, FailureReason.content_missing),
    record('scrapling', 'forum-beta', False),
    record('scrapling', 'forum-gamma', False),
    record('scrapling', 'forum-gamma', True),   # a retry: taken once, measured once
    scenario(),
]


class AggregateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.targets = self.write('local.toml', targets_toml())
        self.runs = self.write('run.jsonl', ''.join(map(to_jsonl_line, RECORDS)))

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def rows(self, text):
        return [line for line in text.splitlines() if line.startswith('|')]

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(list(args))
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def assert_private(self, text):
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertNotIn('://', text)

    def test_counts_targets_per_class_and_provider(self):
        rows = self.rows(build_aggregate(self.runs, [self.targets]))
        # The scenario record is the only curl record, so curl has no column.
        self.assertEqual(rows, [
            '| Class | Targets | curl_cffi | patchright | scrapling | Any provider |',
            '|---|---|---|---|---|---|',
            '| cloudflare | 2 | 0/2 | 1/2 | 1/2 | 2/2 |',
            '| login-wall | 1 | not measured | 0/1 | not measured | 0/1 |',
            '| none | 1 | 1/1 | not measured | not measured | 1/1 |',
        ])

    def test_any_provider_is_a_union_not_a_single_column(self):
        rows = self.rows(build_aggregate(self.runs, [self.targets]))
        cloudflare = rows[2].split('|')[3:-1]
        self.assertEqual([cell.strip() for cell in cloudflare], ['0/2', '1/2', '1/2', '2/2'])

    def test_order_selects_and_orders_columns(self):
        text = build_aggregate(self.runs, [self.targets],
                               order=['scrapling', 'patchright', 'curl_cffi', 'curl'])
        self.assertEqual(self.rows(text)[0],
                         '| Class | Targets | scrapling | patchright | curl_cffi | Any provider |')
        with self.assertRaisesRegex(ValueError, 'providers missing from --order: scrapling'):
            build_aggregate(self.runs, [self.targets], order=['curl_cffi', 'patchright'])

    def test_output_never_names_targets_hosts_or_egress(self):
        rc, out, err = self.cli('aggregate', str(self.runs), '--targets', str(self.targets))
        self.assertEqual(rc, 0)
        self.assert_private(out)
        self.assert_private(err)

    def test_invalid_classes_rejected_without_echo(self):
        for klass in ('alpha-shop.invalid', 'Cloudflare', '', None, 7, 'a--b', '-a'):
            with self.subTest(klass=klass):
                path = self.write('bad.toml', targets_toml(dict(CLASSES, **{'shop-alpha': klass})))
                rc, out, err = self.cli('aggregate', str(self.runs), '--targets', str(path))
                self.assertEqual(rc, 2)
                message = err.strip().splitlines()[-1]
                self.assertIn('bad.toml: target #1: class must match', message)
                self.assert_private(err)
                if isinstance(klass, str) and klass:
                    self.assertNotIn(klass, message)

    def test_public_classes_are_accepted(self):
        for klass in ('none', 'cloudflare', 'cloudflare+spa', 'login-wall',
                      'cloudflare-managed-challenge', 'cloudflare-passive'):
            self.assertTrue(CLASS_PATTERN.fullmatch(klass), klass)
        public = load_classes([Path('bench/targets/targets.toml')])
        self.assertEqual(len(public), 7)

    def test_records_for_unknown_targets_rejected_by_count(self):
        partial = self.write('partial.toml', targets_toml(
            {k: v for k, v in CLASSES.items() if k != 'forum-gamma'}))
        rc, out, err = self.cli('aggregate', str(self.runs), '--targets', str(partial))
        self.assertEqual(rc, 2)
        self.assertIn('4 records reference targets missing from --targets', err)
        self.assert_private(err)
        self.assertEqual(out, '')

    def test_duplicate_ids_across_files_rejected_without_echo(self):
        rc, _, err = self.cli('aggregate', str(self.runs), '--targets',
                              str(self.targets), str(self.targets))
        self.assertEqual(rc, 2)
        self.assertIn('duplicate target id across --targets', err)
        self.assert_private(err)

    def test_invalid_record_rejected_without_echo(self):
        runs = self.write('broken.jsonl', to_jsonl_line(RECORDS[0])
                          + '{"target": "shop-alpha", "final_url": "https://alpha-shop.invalid/"}\n')
        rc, _, err = self.cli('aggregate', str(runs), '--targets', str(self.targets))
        self.assertEqual(rc, 2)
        self.assertIn('line 2: invalid run record', err)
        self.assert_private(err)

    def test_foreign_providers_rejected_without_echo(self):
        # A provider value is JSONL data too: it must not reach the error or a header.
        forged = json.loads(to_jsonl_line(RECORDS[0]))
        forged['provider'] = 'alpha-shop.invalid'
        runs = self.write('forged.jsonl', to_jsonl_line(RECORDS[0]) + json.dumps(forged) + '\n')
        rc, out, err = self.cli('aggregate', str(runs), '--targets', str(self.targets))
        self.assertEqual(rc, 2)
        self.assertIn('1 records name providers outside the registry', err)
        self.assert_private(err)
        self.assertEqual(out, '')
        rc, out, err = self.cli('aggregate', str(self.runs), '--targets', str(self.targets),
                                '--order', 'curl_cffi', 'patchright', 'scrapling', 'forum-beta')
        self.assertEqual(rc, 2)
        self.assertIn('--order names providers outside the registry', err)
        self.assert_private(err)
        self.assertEqual(out, '')

    def test_output_is_exclusive(self):
        dest = self.root / 'summary.md'
        rc, out, _ = self.cli('aggregate', str(self.runs), '--targets', str(self.targets),
                              '--output', str(dest))
        self.assertEqual((rc, out), (0, ''))
        self.assertEqual(dest.read_text(encoding='utf-8'),
                         build_aggregate(self.runs, [self.targets]))
        dest.write_text('keep', encoding='utf-8')
        rc, _, _ = self.cli('aggregate', str(self.runs), '--targets', str(self.targets),
                            '--output', str(dest))
        self.assertEqual(rc, 2)
        self.assertEqual(dest.read_text(encoding='utf-8'), 'keep')

    def test_plan_merges_target_files_and_rejects_cross_file_duplicates(self):
        extra = self.write('extra.toml', '[[target]]\nid = "public-one"\n'
                           'url = "https://public.invalid/"\nexpect = "P"\n')
        rc, out, _ = self.cli('plan', '--targets', str(self.targets), str(extra),
                              '--providers', 'curl')
        self.assertEqual(rc, 0)
        cells = {json.loads(line)['cell'] for line in out.splitlines()}
        self.assertEqual(cells, {f'target:{tid}' for tid in [*CLASSES, 'public-one']})
        rc, _, err = self.cli('plan', '--targets', str(self.targets), str(self.targets),
                              '--providers', 'curl')
        self.assertEqual(rc, 2)
        self.assertIn('duplicate target', err)


if __name__ == '__main__':
    unittest.main()
