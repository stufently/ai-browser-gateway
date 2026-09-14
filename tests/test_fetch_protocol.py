"""Probe content protocol and budget plumbing; no Docker."""
from __future__ import annotations

import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.models import ChallengeType, FailureReason, FetchResult, evaluate
from tests.test_probe import Clock, FakeAdapter, load_probe

PROBE_PATH = Path(__file__).resolve().parents[1] / 'bench' / 'providers' / 'docker' / 'probe.py'
UNICODE_SEPARATORS = '\u0085\u2028\u2029'


def _page_result(html: str, text: str) -> FetchResult:
    return FetchResult(
        provider='curl', provider_version='test', requested_url='https://example.invalid/',
        final_url='https://example.invalid/', status=200, html=html, text=text,
        elapsed_ms=1, startup_ms=0, cpu_ms=0, peak_rss_mb=0.1, bytes_received=1,
        redirects=0, error_type=FailureReason.none, challenge=ChallengeType.none,
    )


class ContentProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_html_to_text_strips_inert_markup_and_decodes_entities(self):
        html = (
            '<html><body>keep-α &amp; &copy; '
            '<script>script-only</script><style>color:red</style>'
            '<template>template-only</template>tail</body></html>'
        )
        text = self.probe.html_to_text(html)
        self.assertIn('keep-α', text)
        self.assertIn('&', text)
        self.assertIn('©', text)
        self.assertIn('tail', text)
        self.assertNotIn('script-only', text)
        self.assertNotIn('color:red', text)
        self.assertNotIn('template-only', text)
        self.assertNotIn('<', text)

    def test_html_to_text_does_not_glue_adjacent_blocks_into_a_sentinel(self):
        text = self.probe.html_to_text('<p>PAGE</p><p>_OK</p>')
        self.assertNotIn('PAGE_OK', text)
        self.assertIn('PAGE', text)
        self.assertIn('_OK', text)

    def test_html_to_text_breaks_on_br_hr_and_block_edges(self):
        cases = (
            '<p>PAGE<br>_OK</p>',
            '<p>PAGE<br/>_OK</p>',
            '<p>PAGE<br />_OK</p>',
            'PAGE<div>_OK</div>',
            '<div>PAGE</div>_OK',
            'PAGE<hr>_OK',
            'PAGE<hr/>_OK',
        )
        for html in cases:
            with self.subTest(html=html):
                text = self.probe.html_to_text(html)
                self.assertNotIn('PAGE_OK', text, text)
                self.assertIn('PAGE', text)
                self.assertIn('_OK', text)
                ok, reason = evaluate(_page_result(html, text), 'PAGE_OK')
                self.assertFalse(ok, f'evaluate accepted glued text {text!r}')
                self.assertEqual(reason, FailureReason.content_missing)

    def test_html_to_text_does_not_split_words_on_inline_markup(self):
        cases = (
            '<b>PAGE</b>_OK',
            '<i>PAGE</i>_OK',
            'PA<span>GE</span>_OK',
            '<em>PAGE</em>_OK',
            '<strong>PA</strong>GE_OK',
        )
        for html in cases:
            with self.subTest(html=html):
                text = self.probe.html_to_text(html)
                self.assertIn('PAGE_OK', text, text)
                self.assertNotIn('<', text)
                ok, reason = evaluate(_page_result(html, text), 'PAGE_OK')
                self.assertTrue(ok, f'evaluate missed inline sentinel in {text!r}')
                self.assertEqual(reason, FailureReason.none)

    def test_parse_output_keeps_unicode_separators_and_rejects_broken_last_line(self):
        from bench.providers.registry import by_name, parse_output

        html = f'keep{UNICODE_SEPARATORS}PAGE_OK'
        payload = {'ok': True, 'html': html, 'text': html}
        wire = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        self.assertGreater(len(wire.splitlines()), 1)
        got = parse_output(by_name('curl'), 'log\n' + wire + '\ntrailer\n')
        self.assertEqual(got['html'], html)
        self.assertEqual(got['text'], html)
        for char in UNICODE_SEPARATORS:
            self.assertIn(char, got['html'])
            self.assertIn(char, got['text'])
        earlier = json.dumps({'ok': True, 'html': 'good'}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            parse_output(by_name('curl'), earlier + '\n{broken')

    def test_include_content_false_omits_fields_even_on_failure(self):
        class Broken:
            def start(self):
                raise RuntimeError('nope')

            def close(self):
                pass

        result = self.probe.run_probe(
            'curl', 'https://target.invalid/', 'marker', mode='cold',
            adapter_factory=lambda _: Broken(), metrics=lambda: (0, 0),
        )
        self.assertNotIn('html', result)
        self.assertNotIn('text', result)
        self.assertIn('nope', result['err'])

    def test_budget_ms_rejects_bool_and_non_positive(self):
        for budget in (0, -3, True, False, 1.5):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    self.probe.run_probe(
                        'curl', 'https://target.invalid/', 'marker', mode='cold',
                        adapter_factory=lambda _: FakeAdapter([]),
                        metrics=lambda: (0, 0), budget_ms=budget,
                    )

    def test_timeout_error_is_classified_without_content_leak(self):
        class Slow:
            def start(self):
                raise TimeoutError('wall clock')

            def close(self):
                pass

        result = self.probe.run_probe(
            'curl', 'https://target.invalid/', 'marker', mode='cold',
            adapter_factory=lambda _: Slow(), metrics=lambda: (0, 0),
            include_content=True, budget_ms=50,
        )
        self.assertEqual(result['err'], 'timeout')
        self.assertEqual(result['html'], '')
        self.assertEqual(result['text'], '')
        self.assertFalse(result['ok'])

    def test_foreign_timeout_class_is_still_timeout(self):
        class ForeignTimeout(Exception):
            pass

        ForeignTimeout.__name__ = 'TimeoutError'

        class Slow:
            def start(self):
                raise ForeignTimeout('playwright budget')

            def close(self):
                pass

        result = self.probe.run_probe(
            'patchright', 'https://target.invalid/', 'marker', mode='cold',
            adapter_factory=lambda _: Slow(), metrics=lambda: (0, 0),
            include_content=True, budget_ms=80,
        )
        self.assertEqual(result['err'], 'timeout')

    def test_curl_passes_remaining_budget_as_max_time(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout=b'marker\nABG_CURL_META:200\thttps://final.invalid/\t0\t{}',
            stderr=b'',
        )
        with patch.object(self.probe.subprocess, 'run', return_value=completed) as run:
            result = self.probe.run_probe(
                'curl', 'https://target.invalid/', 'marker', mode='cold',
                adapter_factory=lambda _: self.probe.CurlAdapter(),
                clock=lambda: 10, metrics=lambda: (0, 0),
                include_content=True, budget_ms=250,
            )
        command = run.call_args.args[0]
        self.assertIn('--max-time', command)
        self.assertEqual(command[command.index('--max-time') + 1], '0.25')
        self.assertEqual(result['html'], 'marker')
        self.assertIn('marker', result['text'])

    def test_curl_without_budget_has_no_max_time(self):
        completed = subprocess.CompletedProcess(
            [], 0, stdout=b'marker\nABG_CURL_META:200\thttps://final.invalid/\t0\t{}',
            stderr=b'',
        )
        with patch.object(self.probe.subprocess, 'run', return_value=completed) as run:
            self.probe.CurlAdapter().navigate('https://target.invalid/')
        command = run.call_args.args[0]
        self.assertNotIn('--max-time', command)

    def test_cli_keeps_legacy_args_and_accepts_new_flags(self):
        def fake_run_probe(*args, **kwargs):
            fake_run_probe.seen = kwargs
            return {'ok': False, 'err': ''}

        fake_run_probe.seen = {}
        probe = load_probe()
        with patch.object(probe, 'run_probe', side_effect=fake_run_probe), patch.object(
            sys, 'stdout'
        ):
            self.assertEqual(probe.main(['https://t.invalid/', 'S']), 0)
        self.assertFalse(fake_run_probe.seen.get('include_content'))
        self.assertIsNone(fake_run_probe.seen.get('budget_ms'))
        with patch.object(probe, 'run_probe', side_effect=fake_run_probe), patch.object(
            sys, 'stdout'
        ):
            self.assertEqual(
                probe.main(['https://t.invalid/', 'S', '--include-content', '--budget-ms', '40']),
                0,
            )
        self.assertTrue(fake_run_probe.seen['include_content'])
        self.assertEqual(fake_run_probe.seen['budget_ms'], 40)
        with patch.object(sys, 'stderr'), self.assertRaises(SystemExit):
            probe.main(['https://t.invalid/', 'S', '--budget-ms', '0'])

    def test_scrapling_fetch_timeout_uses_remaining_after_start(self):
        captured = {}

        class Page:
            status = 200
            url = 'https://final.invalid/'
            body = b'<html>marker</html>'
            headers = {}
            history = ()

        class Session:
            def __init__(self, **kwargs):
                captured['init'] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def fetch(self, url, **kwargs):
                captured['fetch'] = kwargs
                return Page()

        fetchers = types.ModuleType('scrapling.fetchers')
        fetchers.StealthySession = Session
        scrapling = types.ModuleType('scrapling')
        scrapling.fetchers = fetchers
        times = iter([100.0, 100.2, 100.3, 115.0, 115.1])

        def clock():
            return next(times)

        with patch.dict(sys.modules, {'scrapling': scrapling, 'scrapling.fetchers': fetchers}):
            result = self.probe.run_probe(
                'scrapling', 'https://target.invalid/', 'marker', mode='cold',
                adapter_factory=lambda _: self.probe.ScraplingAdapter(),
                clock=clock, metrics=lambda: (0, 0),
                include_content=True, budget_ms=30_000,
            )
        self.assertTrue(result['ok'])
        self.assertEqual(captured['fetch']['timeout'], 15_000)
        self.assertIs(captured['fetch']['solve_cloudflare'], True)

    def test_clock_call_count_unchanged_without_budget(self):
        events = []
        clock = Clock()
        self.probe.run_probe(
            'curl', 'https://target.invalid/', 'expected marker',
            mode='cold', adapter_factory=lambda _: FakeAdapter(events),
            clock=clock, metrics=lambda: (0, 0),
        )
        self.assertEqual(len(clock.values), 3)


class RegistryArgvExtensionTests(unittest.TestCase):
    def test_legacy_build_argv_has_no_probe_mount_or_content_flags(self):
        from bench.providers.registry import build_argv, by_name
        argv = build_argv(by_name('curl'), url='https://example.invalid/', sentinel='S')
        self.assertNotIn('--mount', argv)
        self.assertNotIn('-v', argv)
        self.assertNotIn('--include-content', argv)
        self.assertNotIn('--budget-ms', argv)
        self.assertEqual(argv[-2:], ['https://example.invalid/', 'S'])

    def test_optional_bind_and_content_flags_are_compatible(self):
        from bench.providers.registry import build_argv, by_name
        argv = build_argv(
            by_name('curl'), url='https://example.invalid/', sentinel='S',
            probe_bind=PROBE_PATH, include_content=True, budget_ms=80,
        )
        self.assertIn('--include-content', argv)
        self.assertEqual(argv[argv.index('--budget-ms') + 1], '80')
        self.assertTrue(any(token == '--mount' or token.startswith('--mount=') for token in argv))
        mount = argv[argv.index('--mount') + 1]
        self.assertIn('probe.py', mount)
        self.assertTrue(mount.endswith('readonly') or ',readonly' in mount)


if __name__ == '__main__':
    unittest.main()
