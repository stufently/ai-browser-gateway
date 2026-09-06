"""Challenge detection on the real fixture bodies, not invented markup."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "bench" / "providers" / "docker" / "probe.py"
FIXTURES = ROOT / "tests" / "fixtures"


def load_probe():
    spec = importlib.util.spec_from_file_location("container_probe_detect", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class DetectChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def detect(self, status, headers, body):
        return self.probe.detect_challenge(status, headers, body)

    def test_interstitial_fixture_is_suspected_with_named_rules(self):
        verdict, markers = self.detect(
            403, {}, fixture("cf_interstitial_200body_403.html")
        )
        self.assertGreaterEqual(len(markers), 3)
        self.assertEqual(verdict, "suspected")

    def test_js_shell_fixture_is_none_with_no_rules(self):
        verdict, markers = self.detect(200, {}, fixture("js_shell_200.html"))
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_real_page_fixture_is_none_with_no_rules(self):
        verdict, markers = self.detect(200, {}, fixture("real_page_head.html"))
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_cf_mitigated_header_outranks_clean_body(self):
        verdict, markers = self.detect(
            200, {"cf-mitigated": "challenge"}, "<html><body>hello</body></html>"
        )
        self.assertEqual(verdict, "suspected")
        self.assertTrue(markers)

    def test_header_name_is_matched_case_insensitively(self):
        verdict, markers = self.detect(
            200, {"CF-Mitigated": "Challenge"}, "<p>plain</p>"
        )
        self.assertEqual(verdict, "suspected")
        self.assertTrue(markers)

    def test_short_body_without_markers_is_none(self):
        body = "short body without any challenge marker!"
        self.assertEqual(len(body), 40)
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_bare_403_is_access_denied_not_suspected(self):
        verdict, markers = self.detect(
            403, {}, "<html><body>nope</body></html>"
        )
        self.assertEqual(verdict, "access_denied")
        self.assertEqual(markers, ("status_403",))

    def test_prose_captcha_is_not_a_challenge_without_second_signal(self):
        body = fixture("real_page_head.html") + (
            "\n<p>The article mentions a captcha in passing, nothing more.</p>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_conflict_order_is_header_then_body_then_status(self):
        interstitial = fixture("cf_interstitial_200body_403.html")
        header_verdict, _ = self.detect(
            403, {"cf-mitigated": "interactive"}, interstitial
        )
        self.assertEqual(header_verdict, "interactive")
        body_verdict, _ = self.detect(403, {}, interstitial)
        self.assertEqual(body_verdict, "suspected")
        status_verdict, _ = self.detect(403, {}, "<html><body>nope</body></html>")
        self.assertEqual(status_verdict, "access_denied")

    def test_interactive_header_outranks_body_markers(self):
        verdict, markers = self.detect(
            403,
            {"cf-mitigated": "interactive"},
            fixture("cf_interstitial_200body_403.html"),
        )
        self.assertEqual(verdict, "interactive")
        self.assertIn("header_cf_mitigated", markers)

    def test_noindex_nofollow_alone_is_not_a_challenge(self):
        verdict, markers = self.detect(
            200, {}, '<meta name="robots" content="noindex,nofollow">'
        )
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_interactive_cf_mitigated_value_is_interactive(self):
        verdict, markers = self.detect(
            403, {"cf-mitigated": "interactive"}, "<p>x</p>"
        )
        self.assertEqual(verdict, "interactive")
        self.assertTrue(markers)

    def test_status_429_without_markers_is_rate_limited(self):
        verdict, markers = self.detect(429, {}, "<p>slow down</p>")
        self.assertEqual(verdict, "rate_limited")
        self.assertEqual(markers, ("status_429",))

    def test_missing_headers_skip_header_rules(self):
        verdict, markers = self.detect(200, None, "<p>hello</p>")
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())


if __name__ == "__main__":
    unittest.main()
