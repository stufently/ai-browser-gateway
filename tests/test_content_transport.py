"""Content-only wire contract exercised through the real probe and transport."""
import json
import unittest
from unittest.mock import patch

from bench.models import FailureReason
from bench.providers.docker import probe
from bench.providers.registry import build_argv, by_name
from bench.runner.execute import fetch_content, fetch_page


class Adapter:
    version = 'test'
    def start(self):
        pass
    def navigate(self, url):
        return dict(body='<p>unique</p><script>secret</script>', status=200, final_url=url)
    def close(self):
        pass


class ContentTests(unittest.TestCase):
    def test_no_expectation_is_sent_to_adapter_or_reported_found(self):
        adapter = Adapter()
        result = probe.run_probe('curl', 'https://a.test', None, mode='cold',
                                 content_only=True, include_content=True,
                                 adapter_factory=lambda _: adapter)
        self.assertFalse(result['sentinel'])
        self.assertFalse(result['ok'])
        self.assertFalse(adapter.sentinel)
        self.assertIn('unique', result['html'])
        self.assertEqual(result['text'].strip(), 'unique')
        self.assertEqual(result['err'], '')

    def test_transport_uses_content_mode_and_fractional_deadline(self):
        calls = []
        class Launcher:
            def run(self, argv, timeout, *, env):
                calls.append((argv, timeout, env))
                payload = probe.run_probe('curl', 'https://a.test', None, mode='cold',
                                          content_only=True, include_content=True,
                                          adapter_factory=lambda _: Adapter())
                return 0, json.dumps(payload), ''
        with patch.dict('os.environ', {'ABG_PROXY': 'secret'}):
            result, age = fetch_content('curl', url='https://a.test', budget_ms=1250, launcher=Launcher())
        self.assertEqual(result.error_type, FailureReason.none)
        self.assertEqual(result.text.strip(), 'unique')
        self.assertIsNone(age)
        argv, timeout, env = calls[0]
        self.assertEqual(timeout, 1.25)
        self.assertNotIn('ABG_PROXY', env)
        self.assertEqual(argv[argv.index('abg-curl:m2') + 1:],
                         ['https://a.test', '--content-only', '--include-content', '--budget-ms', '1250', '--mode', 'cold'])

    def test_legacy_still_requires_sentinel(self):
        for sentinel in (None, ''):
            with self.assertRaises(ValueError):
                fetch_page('curl', url='https://a.test', sentinel=sentinel, budget_ms=100)
        result = probe.run_probe('curl', 'https://a.test', '', mode='cold',
                                 adapter_factory=lambda _: self.fail('legacy empty sentinel reached adapter'))
        self.assertIn('empty sentinel', result['err'])
        with self.assertRaises(SystemExit):
            probe.main(['https://a.test'])

    def test_content_only_flag_allows_omitted_sentinel(self):
        argv = build_argv(by_name('curl'), url='https://a.test', content_only=True)
        self.assertEqual(argv[-2:], ['https://a.test', '--content-only'])

    def test_bad_inputs_do_not_reach_launcher(self):
        class Launcher:
            def run(inner, *args, **kwargs):
                self.fail('invalid request reached Docker')
        for url in (None, [], {}, 'https://a.test:0', 'https://a.test:bad', 'https://a.test/\n'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_content('curl', url=url, budget_ms=100, launcher=Launcher())
        with self.assertRaises(ValueError):
            fetch_content('curl', url='https://a.test', budget_ms=180001, launcher=Launcher())
