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

    def test_just_a_moment_in_body_prose_is_not_a_challenge(self):
        body = (
            "<html><head><title>Offers — LowEndTalk</title></head>"
            "<body><p>Wait just a moment before you order.</p></body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ())

    def test_just_a_moment_in_title_is_suspected(self):
        body = (
            "<html><head><title>Just a moment...</title></head>"
            "<body><p>x</p></body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "suspected")
        self.assertIn("body_just_a_moment", markers)

    def test_single_body_cf_challenges_host_is_not_suspected(self):
        verdict, markers = self.detect(
            200, {}, "<p>See challenges.cloudflare.com for details.</p>"
        )
        self.assertEqual(verdict, "none")
        self.assertIn("body_cf_challenges_host", markers)

    def test_single_body_marker_on_403_keeps_rule_name(self):
        verdict, markers = self.detect(
            403, {}, "<p>See challenges.cloudflare.com for details.</p>"
        )
        self.assertIn("body_cf_challenges_host", markers)
        self.assertEqual(verdict, "access_denied")
        self.assertIn("status_403", markers)

    def test_single_body_marker_on_429_keeps_rule_name(self):
        verdict, markers = self.detect(
            429, {}, "<p>See challenges.cloudflare.com for details.</p>"
        )
        self.assertIn("body_cf_challenges_host", markers)
        self.assertEqual(verdict, "rate_limited")
        self.assertIn("status_429", markers)

    def test_single_body_cf_chl_opt_is_not_suspected(self):
        verdict, markers = self.detect(200, {}, "<p>window._cf_chl_opt = {}</p>")
        self.assertEqual(verdict, "none")
        self.assertIn("body_cf_chl_opt", markers)

    def test_single_body_cf_chl_is_not_suspected(self):
        verdict, markers = self.detect(200, {}, "<p>token=__cf_chl_tk</p>")
        self.assertEqual(verdict, "none")
        self.assertIn("body_cf_chl", markers)

    def test_single_body_cf_challenge_platform_is_not_suspected(self):
        verdict, markers = self.detect(
            200, {}, "<script src='/cdn-cgi/challenge-platform/x.js'></script>"
        )
        self.assertEqual(verdict, "none")
        self.assertIn("body_cf_challenge_platform", markers)

    def test_two_body_markers_are_suspected(self):
        verdict, markers = self.detect(
            200, {}, "<p>challenges.cloudflare.com cf_chl_opt</p>"
        )
        self.assertEqual(verdict, "suspected")
        self.assertIn("body_cf_challenges_host", markers)
        self.assertIn("body_cf_chl_opt", markers)

    def test_body_cf_challenges_host_is_named_with_title(self):
        body = (
            "<html><head><title>Just a moment...</title></head>"
            "<body>challenges.cloudflare.com</body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertIn("body_cf_challenges_host", markers)
        self.assertEqual(verdict, "suspected")

    def test_body_cf_chl_opt_is_named_with_title(self):
        body = (
            "<html><head><title>Just a moment...</title></head>"
            "<body>cf_chl_opt</body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertIn("body_cf_chl_opt", markers)
        self.assertEqual(verdict, "suspected")

    def test_body_cf_chl_is_named_with_title(self):
        body = (
            "<html><head><title>Just a moment...</title></head>"
            "<body>__cf_chl</body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertIn("body_cf_chl", markers)
        self.assertEqual(verdict, "suspected")

    def test_body_cf_challenge_platform_is_named_with_title(self):
        body = (
            "<html><head><title>Just a moment...</title></head>"
            "<body>/cdn-cgi/challenge-platform</body></html>"
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertIn("body_cf_challenge_platform", markers)
        self.assertEqual(verdict, "suspected")

    def test_supporting_noindex_is_named_on_interstitial(self):
        verdict, markers = self.detect(
            403, {}, fixture("cf_interstitial_200body_403.html")
        )
        self.assertIn("body_noindex_nofollow", markers)
        self.assertEqual(verdict, "suspected")

    def test_lone_captcha_attribute_is_none_but_named(self):
        body = (
            '<html><body><img id="captcha-history" '
            'src="/img/captcha-example.png"></body></html>'
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "none")
        self.assertIn("body_captcha", markers)

    def test_captcha_with_403_is_captcha_and_named(self):
        body = (
            '<html><body><img id="captcha-history" '
            'src="/img/captcha-example.png"></body></html>'
        )
        verdict, markers = self.detect(403, {}, body)
        self.assertEqual(verdict, "captcha")
        self.assertIn("body_captcha", markers)

    def test_captcha_with_429_is_captcha_and_named(self):
        body = '<div class="g-captcha" id="box"></div>'
        verdict, markers = self.detect(429, {}, body)
        self.assertEqual(verdict, "captcha")
        self.assertIn("body_captcha", markers)

    def test_captcha_plus_one_body_marker_is_captcha(self):
        body = (
            '<p>See challenges.cloudflare.com</p>'
            '<img id="captcha-history" src="/x.png">'
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "captcha")
        self.assertIn("body_captcha", markers)
        self.assertIn("body_cf_challenges_host", markers)


if __name__ == "__main__":
    unittest.main()
