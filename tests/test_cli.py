import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.cli import build_parser, main
from bench.models import FailureReason
from bench.providers.registry import PROVIDERS
from bench.runner.record import from_jsonl_line
from tests.m2_helpers import FakeLauncher, output


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, args, **kwargs):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            rc = main(args, **kwargs)
        self.assertEqual(rc, 0)
        return stream.getvalue()

    def test_parser_commands_and_safe_defaults(self):
        parser = build_parser()
        args = parser.parse_args(['run', '--output', 'out.jsonl'])
        self.assertEqual(args.pause_s, 20)
        self.assertEqual(args.timeout, 180)
        self.assertEqual(parser.parse_args(['providers']).command, 'providers')
        self.assertEqual(parser.parse_args(['report', 'in.jsonl']).jsonl_path, 'in.jsonl')

    def test_providers_lists_registry(self):
        text = self.invoke(['providers'])
        for provider in PROVIDERS:
            self.assertIn(provider.name, text)
            self.assertIn(provider.image, text)

    def test_plan_does_not_launch(self):
        launcher = FakeLauncher()
        text = self.invoke(['plan', '--providers', 'curl', 'playwright', '--cells', 'scenario:static',
                            '--cold', '2', '--warm', '3'], launcher=launcher)
        plan = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(plan), 7)
        self.assertEqual(len({p['run_id'] for p in plan}), 7)
        self.assertNotIn(('curl', 'warm'), {(p['provider'], p['mode']) for p in plan})
        self.assertEqual(launcher.calls, [])

    def test_run_writes_roundtrippable_jsonl_then_report(self):
        path = self.root / 'out.jsonl'
        self.invoke(['run', '--providers', 'curl', '--cells', 'scenario:static', '--output', str(path)],
                    launcher=FakeLauncher(output()), reader=lambda key: None, sleep=lambda seconds: None)
        records = [from_jsonl_line(line) for line in path.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success)
        self.assertEqual(records[0].egress_ip, 'unknown')
        rendered = self.invoke(['report', str(path), '--order', 'curl', '--unmeasured', 'paid'])
        self.assertIn('Incremental', rendered)
        self.assertIn('paid', rendered)
        dest = self.root / 'out.md'
        self.invoke(['report', str(path), '--order', 'curl', '--output', str(dest)])
        self.assertIn('scenario:static', dest.read_text())

    def test_targets_skip_invalid_and_default_one_request(self):
        path = self.root / 'targets.toml'
        path.write_text('''[[target]]
id = "valid"
url = "https://example.invalid/a"
expect = "S"
[[target]]
id = "invalid"
url = "https://example.invalid/b"
expect = "S"
valid = false
''')
        text = self.invoke(['plan', '--targets', str(path), '--providers', 'curl', 'playwright'])
        items = [json.loads(line) for line in text.splitlines()]
        self.assertEqual(len(items), 2)
        self.assertEqual({p['cell'] for p in items}, {'target:valid'})
        self.assertEqual({p['mode'] for p in items}, {'cold'})
        pauses = []
        self.invoke(['run', '--targets', str(path), '--providers', 'curl', 'playwright',
                     '--output', str(self.root / 'out.jsonl')],
                    launcher=FakeLauncher(output(), output()), reader=lambda key: None, sleep=pauses.append)
        self.assertEqual(pauses, [30])

    def test_invalid_selection_and_target_repeats_rejected_without_launch(self):
        launcher = FakeLauncher()
        for options in (['--providers', 'nope'], ['--cells', 'target:nope'], ['--cold', '-1'],
                        ['--targets', 'bench/targets/targets.toml', '--warm', '1']):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
                main(['plan', *options], launcher=launcher)
            self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(launcher.calls, [])

    def test_report_preserves_source_and_existing_destination(self):
        from tests.m2_helpers import observed_record
        from bench.runner.record import to_jsonl_line
        source = self.root / 'source.jsonl'
        original = to_jsonl_line(observed_record())
        source.write_text(original)
        destination = self.root / 'report.md'
        destination.write_text('preserve report')
        for target in (source, destination):
            with self.subTest(target=target), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['report', str(source), '--order', 'curl', '--output', str(target)])
            self.assertEqual(source.read_text(), original)
            self.assertEqual(destination.read_text(), 'preserve report')

    def test_run_accepts_egress_flag(self):
        parser = build_parser()
        args = parser.parse_args(['run', '--output', 'out.jsonl', '--egress', 'gold'])
        self.assertEqual(args.egress, 'gold')

    def test_run_missing_egress_profile_writes_not_measured(self):
        home = self.root / 'home'
        home.mkdir()
        path = self.root / 'out.jsonl'
        launcher = FakeLauncher()
        with patch.dict(os.environ, {'HOME': str(home)}):
            self.invoke(
                ['run', '--providers', 'curl', '--cells', 'scenario:static',
                 '--output', str(path), '--egress', 'gold'],
                launcher=launcher, reader=lambda key: None, sleep=lambda seconds: None,
            )
        records = [from_jsonl_line(line) for line in path.read_text().splitlines()]
        self.assertEqual(records[0].error_type, FailureReason.not_measured)
        self.assertEqual(records[0].egress_profile, 'gold')
        self.assertEqual(launcher.calls, [])
        self.assertNotIn('pass', path.read_text())

    def test_run_with_proxy_profile_passes_env_name_not_url(self):
        home = self.root / 'home'
        config = home / '.config' / 'abg'
        config.mkdir(parents=True)
        proxies = config / 'proxies.toml'
        proxies.write_text('[profile.gold]\nurl = "http://user:pass@proxy.invalid:8080"\n')
        os.chmod(proxies, 0o600)
        path = self.root / 'out.jsonl'
        seen = {}

        class Capture(FakeLauncher):
            def run(self, argv, timeout):
                seen['proxy'] = os.environ.get('ABG_PROXY')
                seen['argv'] = list(argv)
                return super().run(argv, timeout)

        launcher = Capture(output())
        with patch.dict(os.environ, {'HOME': str(home)}):
            self.invoke(
                ['run', '--providers', 'curl', '--cells', 'scenario:static',
                 '--output', str(path), '--egress', 'gold'],
                launcher=launcher, reader=lambda key: None, sleep=lambda seconds: None,
            )
        records = [from_jsonl_line(line) for line in path.read_text().splitlines()]
        self.assertEqual(records[0].egress_profile, 'gold')
        self.assertTrue(records[0].success)
        self.assertEqual(seen['proxy'], 'http://user:pass@proxy.invalid:8080')
        self.assertEqual(seen['argv'][seen['argv'].index('--env') + 1], 'ABG_PROXY')
        self.assertFalse(any('pass' in part or part.startswith('ABG_PROXY=') for part in seen['argv']))
        self.assertNotIn('pass', path.read_text())
        self.assertNotIn('proxy.invalid', path.read_text())

    def test_run_does_not_overwrite_existing_log(self):
        path = self.root / 'out.jsonl'
        path.write_text('preserve me')
        launcher = FakeLauncher()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['run', '--providers', 'curl', '--output', str(path)], launcher=launcher,
                 reader=lambda key: None)
        self.assertEqual(path.read_text(), 'preserve me')
        self.assertEqual(launcher.calls, [])
