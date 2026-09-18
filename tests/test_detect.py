"""Challenge detection on the real fixture bodies, not invented markup."""

from __future__ import annotations

import importlib.util
import sys
import time
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

    def test_captcha_with_403_is_access_denied_and_named(self):
        body = (
            '<html><body><img id="captcha-history" '
            'src="/img/captcha-example.png"></body></html>'
        )
        verdict, markers = self.detect(403, {}, body)
        self.assertEqual(verdict, "access_denied")
        self.assertEqual(markers, ("body_captcha", "status_403"))

    def test_captcha_with_429_is_rate_limited_and_named(self):
        body = '<div class="g-captcha" id="box"></div>'
        verdict, markers = self.detect(429, {}, body)
        self.assertEqual(verdict, "rate_limited")
        self.assertEqual(markers, ("body_captcha", "status_429"))

    def test_captcha_plus_one_body_marker_is_none_but_named(self):
        body = (
            '<p>See challenges.cloudflare.com</p>'
            '<img id="captcha-history" src="/x.png">'
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "none")
        self.assertIn("body_captcha", markers)
        self.assertIn("body_cf_challenges_host", markers)

    def test_lowendtalk_grecaptcha_on_200_is_none_but_named(self):
        verdict, markers = self.detect(
            200, {}, fixture("lowendtalk_200_grecaptcha.html")
        )
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ("body_cf_challenge_platform", "body_captcha"))

    def test_lowendtalk_grecaptcha_on_403_is_access_denied(self):
        verdict, markers = self.detect(
            403, {}, fixture("lowendtalk_200_grecaptcha.html")
        )
        self.assertEqual(verdict, "access_denied")
        self.assertEqual(
            markers, ("body_cf_challenge_platform", "body_captcha", "status_403")
        )

    def test_lowendtalk_grecaptcha_with_second_body_marker_is_suspected(self):
        body = fixture("lowendtalk_200_grecaptcha.html") + "<div class=cf_chl_opt></div>"
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "suspected")
        self.assertIn("body_cf_chl_opt", markers)
        self.assertIn("body_cf_challenge_platform", markers)
        self.assertIn("body_captcha", markers)

    def test_interactive_widget_plus_one_cf_marker_is_captcha_and_named(self):
        body = (
            '<title>Offers</title>'
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<div class="g-recaptcha" data-sitekey="k"></div>'
        )
        verdict, markers = self.detect(200, {}, body)
        self.assertEqual(verdict, "captcha")
        self.assertIn("body_captcha", markers)
        self.assertEqual(markers, (
            "body_cf_challenge_platform", "body_captcha", "body_captcha_interactive",
        ))

    def test_interactive_widget_without_cf_on_200_is_none(self):
        verdict, markers = self.detect(200, {}, '<div class="g-recaptcha"></div>')
        self.assertEqual(verdict, "none")
        self.assertEqual(markers, ("body_captcha", "body_captcha_interactive"))

    def test_interactive_widget_on_other_error_status_is_none(self):
        for status in (404, 500):
            with self.subTest(status=status):
                verdict, markers = self.detect(
                    status, {}, '<div class="g-recaptcha" data-sitekey="k"></div>'
                )
                self.assertEqual(verdict, "none")
                self.assertEqual(markers, ("body_captcha", "body_captcha_interactive"))

    def test_interactive_widget_on_403_and_429_is_captcha(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.assertEqual(
                    self.detect(status, {}, '<div data-sitekey="k"></div>'),
                    ("captcha", ("body_captcha_interactive",)),
                )

    def test_interactive_markup_is_recognized_independently(self):
        cases = (
            ('<div class="g-recaptcha"></div>', ("body_captcha",)),
            ("<div class='form h-captcha active'></div>", ("body_captcha",)),
            ('<div class="cf-turnstile"></div>', ()),
            ('<div class=cf-turnstile></div>', ()),
            ('<div data-sitekey="k"></div>', ()),
            ('<DIV DATA-SITEKEY=k></DIV>', ()),
            ('<script src="https://www.google.com/recaptcha/api.js"></script>',
             ("body_captcha",)),
            ('<script src="https://www.google.com/recaptcha/api.js?hl=en"></script>',
             ("body_captcha",)),
            ('<script src=https://www.google.com/recaptcha/api.js></script>', ()),
        )
        for body, old_markers in cases:
            with self.subTest(body=body):
                self.assertEqual(
                    self.detect(200, {}, body),
                    ("none", old_markers + ("body_captcha_interactive",)),
                )

    def test_noninteractive_captcha_with_cf_never_becomes_captcha(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        bodies = (
            '<img id="captcha-history">',
            '<script src="https://www.google.com/recaptcha/api.js?render=KEY"></script>',
            '<script src="https://www.google.com/recaptcha/api.js?hl=en&amp;render=KEY"></script>',
            '<script src="https://www.google.com/recaptcha/api.js?render="></script>',
            '<script>grecaptcha.ready(function() { grecaptcha.execute("KEY"); });</script>',
        )
        for body in bodies:
            for status, expected in ((200, "none"), (403, "access_denied"), (429, "rate_limited")):
                with self.subTest(body=body, status=status):
                    verdict, markers = self.detect(status, {}, cf + body)
                    self.assertEqual(verdict, expected)
                    self.assertNotIn("body_captcha_interactive", markers)

    def test_widget_words_outside_attributes_are_not_interactive(self):
        bodies = (
            '<p>g-recaptcha h-captcha cf-turnstile data-sitekey recaptcha/api.js</p>',
            '<div class="g-recaptcha-history h-captcha-example cf-turnstile-info"></div>',
            '<div data-example="data-sitekey" id="g-recaptcha"></div>',
            '<!-- <div data-sitekey="k"></div> -->',
            '<script>const example = \'<div data-sitekey="k"></div>\';</script>',
        )
        for body in bodies:
            with self.subTest(body=body):
                verdict, markers = self.detect(403, {}, body)
                self.assertEqual(verdict, "access_denied")
                self.assertNotIn("body_captcha_interactive", markers)

    def test_v3_script_does_not_hide_a_separate_interactive_widget(self):
        body = (
            '<script src="https://www.google.com/recaptcha/api.js?render=KEY"></script>'
            '<div data-sitekey="k"></div>'
        )
        self.assertEqual(self.detect(403, {}, body), (
            "captcha", ("body_captcha", "body_captcha_interactive"),
        ))

    def test_explicit_render_with_cf_is_interactive(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for query in (
            "render=explicit", "onload=cb&render=explicit",
            "onload=cb&amp;render=explicit", "render=KEY&render=explicit",
            "render=explicit&render=KEY", "render=&render=explicit",
        ):
            with self.subTest(query=query):
                body = cf + f'<script src="https://www.google.com/recaptcha/api.js?{query}"></script>'
                verdict, markers = self.detect(200, {}, body)
                self.assertEqual(verdict, "captcha")
                self.assertEqual(markers, (
                    "body_cf_challenge_platform", "body_captcha", "body_captcha_interactive",
                ))

    def test_nonexplicit_render_with_cf_is_not_interactive(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for query in (
            "onload=cb&render=KEY", "render=KEY&render=OTHER",
            "render=explicitKEY", "render=KEY&onload=explicit", "render=",
        ):
            with self.subTest(query=query):
                body = cf + f'<script src="https://www.google.com/recaptcha/api.js?{query}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "none", ("body_cf_challenge_platform", "body_captcha"),
                ))

    def test_oversized_character_reference_does_not_raise(self):
        bad = "&#" + "9" * 5000 + ";"
        self.assertEqual(self.detect(200, {}, bad), ("none", ()))
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        attr = '<div title="' + bad + '"></div>'
        for body in (cf + widget + bad, cf + bad + widget, cf + attr + widget):
            with self.subTest(widget_before_bad=body.endswith(bad)):
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                ))

    def test_parser_error_preserves_recognized_widget(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        # Attribute references are decoded even with convert_charrefs=False.
        for bad in ('<span title="&#' + "9" * 5000 + ';">', '<![invalid]>'):
            with self.subTest(bad_kind=bad[:6]):
                expected = (
                    "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                )
                for body in (cf + widget + bad, cf + bad + widget):
                    self.assertEqual(self.detect(200, {}, body), expected)

    def test_parser_error_preserves_header_and_status_verdicts(self):
        bad = '<span title="&#' + "9" * 5000 + ';">'
        for status, headers, expected in (
            (200, {}, ("none", ())),
            (403, {}, ("access_denied", ("status_403",))),
            (429, {}, ("rate_limited", ("status_429",))),
            (200, {"cf-mitigated": "interactive"}, ("interactive", ("header_cf_mitigated",))),
        ):
            with self.subTest(status=status, headers=headers):
                self.assertEqual(self.detect(status, headers, bad), expected)

    def test_widget_class_tokens_are_case_sensitive(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        body = cf + '<div class="G-reCAPTCHA"></div>'
        self.assertEqual(self.detect(200, {}, body), (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_widget_parser_preserves_attribute_value_case(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<div class="G-reCAPTCHA"></div>'
            '<script src="https://www.google.com/recaptcha/api.js?render=EXPLICIT"></script>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_explicit_render_value_is_case_sensitive(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<script src="https://www.google.com/recaptcha/api.js?render=EXPLICIT"></script>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_empty_or_valueless_sitekey_is_interactive(self):
        for attribute in ('data-sitekey=""', 'data-sitekey'):
            with self.subTest(attribute=attribute):
                body = f'<div {attribute}></div>'
                self.assertEqual(self.detect(403, {}, body), (
                    "captcha", ("body_captcha_interactive",),
                ))

    def test_script_fragment_is_removed_before_render_query(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for suffix in ('#frag?render=explicit', '?render=explicit#frag'):
            with self.subTest(suffix=suffix):
                body = cf + f'<script src="recaptcha/api.js{suffix}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha",
                                "body_captcha_interactive"),
                ))

    def test_render_key_inside_fragment_is_not_a_query_parameter(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<script src="recaptcha/api.js#frag?render=KEY"></script>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "captcha", ("body_cf_challenge_platform", "body_captcha",
                        "body_captcha_interactive"),
        ))

    def test_semicolon_does_not_split_render_query(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<script src="recaptcha/api.js?render=explicit;foo=1"></script>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_render_parameter_name_is_case_sensitive(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<script src="recaptcha/api.js?RENDER=KEY"></script>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "captcha", ("body_cf_challenge_platform", "body_captcha",
                        "body_captcha_interactive"),
        ))

    def test_render_value_preserves_surrounding_spaces(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for value in (' explicit', 'explicit &foo=1', 'explicit #frag'):
            with self.subTest(value=value):
                body = cf + f'<script src="recaptcha/api.js?render={value}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "none", ("body_cf_challenge_platform", "body_captcha"),
                ))
        body = cf + '<script src="recaptcha/api.js?render=explicit "></script>'
        self.assertEqual(self.detect(200, {}, body), (
            "captcha", ("body_cf_challenge_platform", "body_captcha",
                        "body_captcha_interactive"),
        ))

    def test_script_src_removes_tabs_and_newlines(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for src in ('recaptcha/api.js?render=explicit\n',
                    'recaptcha/api.js?render=exp\tlicit',
                    'recaptcha/\rapi.js?render=explicit',
                    '\t recaptcha/api.js?render=explicit \r\n'):
            with self.subTest(src=src):
                body = cf + f'<script src="{src}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha",
                                "body_captcha_interactive"),
                ))

    def test_script_src_trims_c0_and_space_at_edges(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for codepoint in range(0x01, 0x21):
            char = chr(codepoint)
            for src in (f'{char}recaptcha/api.js?render=explicit',
                        f'recaptcha/api.js?render=explicit{char}'):
                with self.subTest(src=src):
                    body = cf + f'<script src="{src}"></script>'
                    self.assertEqual(self.detect(200, {}, body), (
                        "captcha", ("body_cf_challenge_platform", "body_captcha",
                                    "body_captcha_interactive"),
                    ))

    def test_script_src_replaces_nul_before_url_cleanup(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for src in ('recaptcha/api.js?render=explicit\x00',
                    '\x00recaptcha/api.js?render=explicit',
                    'recaptcha/api.js?render=explicit\x00 \t\n'):
            with self.subTest(src=src):
                body = cf + f'<script src="{src}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "none", ("body_cf_challenge_platform", "body_captcha"),
                ))

    def test_script_src_normalizes_backslashes(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for src in (r'recaptcha\api.js?render=explicit',
                    r'https:\\www.google.com\recaptcha\api.js?render=explicit'):
            with self.subTest(src=src):
                body = cf + f'<script src="{src}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha",
                                "body_captcha_interactive"),
                ))

    def test_script_src_internal_spaces_parse_within_time_budget(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<script src="recaptcha/api.js?render=' + ' ' * 32000 + 'KEY"></script>'
        )
        started = time.perf_counter()
        result = self.detect(200, {}, body)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertEqual(result, (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_script_src_preserves_non_url_whitespace(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for value in ('explicit\x7f', 'explicit\u00a0', 'explicit\u2003',
                      'exp\x00licit', 'exp\x0blicit', 'exp licit'):
            with self.subTest(value=value):
                body = cf + f'<script src="recaptcha/api.js?render={value}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "none", ("body_cf_challenge_platform", "body_captcha"),
                ))

    def test_recaptcha_path_rejects_prefixed_names(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for path in ('xrecaptcha/api.js', 'not-recaptcha/api.js', 'grecaptcha/api.js'):
            with self.subTest(path=path):
                body = cf + f'<script src="{path}?render=explicit"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "none", ("body_cf_challenge_platform", "body_captcha"),
                ))

    def test_iframe_src_is_not_an_interactive_script(self):
        body = (
            '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
            '<iframe src="recaptcha/api.js?render=explicit"></iframe>'
        )
        self.assertEqual(self.detect(200, {}, body), (
            "none", ("body_cf_challenge_platform", "body_captcha"),
        ))

    def test_sitekey_is_interactive_on_any_tag(self):
        for tag in ('span', 'input', 'button', 'p', 'section', 'img'):
            with self.subTest(tag=tag):
                body = f'<{tag} data-sitekey="k">'
                if tag not in ('input', 'img'):
                    body += f'</{tag}>'
                self.assertEqual(self.detect(403, {}, body), (
                    "captcha", ("body_captcha_interactive",),
                ))

    def test_widget_class_tokens_split_on_ascii_whitespace(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for whitespace in (' ', '\t', '\n', '\f', '\r'):
            with self.subTest(whitespace=whitespace):
                body = cf + f'<div class="g-recaptcha{whitespace}foo"></div>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha",
                                "body_captcha_interactive"),
                ))

    def test_widget_class_keeps_non_ascii_whitespace_in_token(self):
        for whitespace in ('\u00a0', '\x0b'):
            with self.subTest(whitespace=whitespace):
                body = f'<div class="g-recaptcha{whitespace}foo"></div>'
                self.assertEqual(self.detect(403, {}, body), (
                    "access_denied", ("body_captcha", "status_403"),
                ))

    def test_widget_class_nul_does_not_form_widget_token(self):
        body = '<div class="g-recaptcha\x00 foo"></div>'
        self.assertEqual(self.detect(403, {}, body), (
            "access_denied", ("body_captcha", "status_403"),
        ))

    def test_boolean_class_preserves_access_denied_verdict(self):
        body = '<div class></div>'
        self.assertEqual(self.detect(403, {}, body), (
            "access_denied", ("status_403",),
        ))

    def test_render_substring_is_not_a_render_parameter(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for query in ('onload=render', 'hl=render', 'rendering=KEY', 'foo=renderer'):
            with self.subTest(query=query):
                body = cf + f'<script src="recaptcha/api.js?{query}"></script>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha",
                                "body_captcha_interactive"),
                ))

    def test_template_widgets_with_cf_are_not_interactive(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for widget in (
            '<div data-sitekey="k"></div>', '<div class="g-recaptcha"></div>',
            '<div class="h-captcha"></div>', '<div class="cf-turnstile"></div>',
            '<script src="https://www.google.com/recaptcha/api.js?render=explicit"></script>',
        ):
            for template in (
                f'<template>{widget}</template>',
                f'<template><template>{widget}</template></template>',
                f'<template><template></template>{widget}</template>',
                f'<template data-sitekey="k">{widget}</template>',
            ):
                with self.subTest(template=template):
                    verdict, markers = self.detect(200, {}, cf + template)
                    self.assertEqual(verdict, "none")
                    self.assertIn("body_cf_challenge_platform", markers)
                    self.assertNotIn("body_captcha_interactive", markers)

    def test_widget_after_closed_templates_is_interactive(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for template in (
            '<template><span></span></template>',
            '<template><template></template></template>',
            '</template><template></template>',
        ):
            with self.subTest(template=template):
                body = cf + template + '<div data-sitekey="k"></div>'
                self.assertEqual(self.detect(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                ))

    def test_uppercase_body_needles_are_suspected_and_named(self):
        verdict, markers = self.detect(200, {}, '<p>CHALLENGES.CLOUDFLARE.COM CF_CHL_OPT</p>')
        self.assertEqual(verdict, "suspected")
        self.assertEqual(markers, ("body_cf_challenges_host", "body_cf_chl_opt"))

    def test_header_and_body_verdicts_outrank_interactive_widget(self):
        widget = '<div data-sitekey="k"></div>'
        body = '<p>challenges.cloudflare.com cf_chl_opt</p>' + widget
        self.assertEqual(self.detect(403, {}, body), (
            "suspected", ("body_cf_challenges_host", "body_cf_chl_opt", "body_captcha_interactive"),
        ))
        for value, expected in (("challenge", "suspected"), ("interactive", "interactive")):
            with self.subTest(value=value):
                self.assertEqual(self.detect(403, {"cf-mitigated": value}, body), (
                    expected, ("header_cf_mitigated", "body_cf_challenges_host",
                               "body_cf_chl_opt", "body_captcha_interactive"),
                ))


class CharacterReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_ampersand_without_hash_is_not_a_numeric_reference(self):
        self.assertEqual(self.probe._title("<title>&65;6</title>"), "&65;6")
        self.assertEqual(self.probe.html_to_text("<p>&65;</p>"), " &65; ")

    def test_empty_numeric_reference_is_preserved(self):
        self.assertEqual(self.probe._title("<title>L&#;R</title>"), "L&#;R")
        self.assertEqual(self.probe.html_to_text("<p>&#;</p>"), " &#; ")

    def test_title_reference_semicolon_separates_following_digit(self):
        self.assertEqual(self.probe._title("<title>&#65;6</title>"), "A6")

    def test_text_reference_semicolon_separates_following_digit(self):
        self.assertEqual(self.probe.html_to_text("<p>&#65;6</p>"), " A6 ")

    def test_title_replaces_all_oversized_references(self):
        references = "&#" + "9" * 5000 + ";X&#" + "9" * 5000 + ";"
        body = "<title>" + references + "</title>"
        self.assertEqual(self.probe._title(body), "\ufffdX\ufffd")

    def test_text_replaces_all_oversized_references(self):
        body = "&#" + "9" * 5000 + ";X&#" + "9" * 5000 + ";"
        self.assertEqual(self.probe.html_to_text(body), "\ufffdX\ufffd")

    def test_widget_after_multiple_oversized_references_is_recognized(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        references = "&#" + "9" * 5000 + ";X&#" + "9" * 5000 + ";"
        for fragment in (references, '<div title="' + references + '"></div>'):
            with self.subTest(attribute=fragment.startswith("<")):
                body = cf + fragment + widget
                self.assertEqual(self.probe.detect_challenge(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                ))

    def test_widget_after_oversized_reference_is_recognized(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        expected = ("captcha", ("body_cf_challenge_platform", "body_captcha_interactive"))
        for suffix in (";", ""):
            reference = "&#" + "9" * 5000 + suffix
            for fragment in (reference, '<div title="' + reference + '"></div>'):
                for body in (cf + fragment + widget, cf + widget + fragment):
                    for as_bytes in (False, True):
                        with self.subTest(semicolon=bool(suffix), attribute=fragment.startswith("<"),
                                          widget_last=body.endswith(widget), as_bytes=as_bytes):
                            payload = body.encode("utf-8") if as_bytes else body
                            self.assertEqual(self.probe.detect_challenge(200, {}, payload), expected)

    def test_oversized_title_preserves_header_and_status_verdicts(self):
        for suffix in (";", ""):
            body = "<title>&#" + "9" * 5000 + suffix + "</title><p>page</p>"
            for status, verdict, markers in (
                (200, "none", ()),
                (403, "access_denied", ("status_403",)),
                (429, "rate_limited", ("status_429",)),
            ):
                for headers, expected in (
                    ({}, (verdict, markers)),
                    ({"cf-mitigated": "challenge"}, ("suspected", ("header_cf_mitigated",))),
                    ({"cf-mitigated": "interactive"}, ("interactive", ("header_cf_mitigated",))),
                ):
                    with self.subTest(semicolon=bool(suffix), status=status, headers=headers):
                        self.assertEqual(self.probe.detect_challenge(status, headers, body), expected)

    def test_html_to_text_keeps_text_after_oversized_reference(self):
        for suffix in (";", ""):
            reference = "&#" + "9" * 5000 + suffix
            for body, expected in (
                ("<p>before " + reference + " after</p>", " before \ufffd after "),
                ('<p title="' + reference + '">after</p>', " after "),
            ):
                with self.subTest(semicolon=bool(suffix), attribute='title=' in body):
                    self.assertEqual(self.probe.html_to_text(body), expected)

    def test_title_replaces_oversized_decimal_reference(self):
        for suffix in (";", ""):
            body = "<title>before &#" + "9" * 5000 + suffix + " after</title>"
            with self.subTest(semicolon=bool(suffix)):
                self.assertEqual(self.probe._title(body), "before \ufffd after")

    def test_title_character_reference_boundaries_are_unchanged(self):
        for reference, expected in (
            ("&#1114111;", ""), ("&#x10FFFF;", ""),
            ("&#1114109;", "\U0010fffd"), ("&#1114112;", "\ufffd"),
            ("&#9999999;", "\ufffd"), ("&#10000000;", "\ufffd"),
            ("&#65;", "A"), ("&#x41;", "A"), ("&#0000065;", "A"),
            ("&#x" + "f" * 5000 + ";", "\ufffd"),
            ("&amp;", "&"), ("&nbsp;", "\xa0"),
        ):
            with self.subTest(reference=reference[:24]):
                self.assertEqual(self.probe._title("<title>L" + reference + "R</title>"),
                                 "L" + expected + "R")

    def test_zero_padded_references_preserve_their_value(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        for suffix in (";", ""):
            for digits, expected in (("0" * 5000 + "65", "A"), ("0" * 5000, "\ufffd")):
                reference = "&#" + digits + suffix
                with self.subTest(semicolon=bool(suffix), all_zero=digits.endswith("0")):
                    self.assertEqual(self.probe._title("<title>" + reference + "</title>"), expected)
                    self.assertEqual(self.probe.html_to_text("<p>" + reference + "</p>"),
                                     " " + expected + " ")
                    body = cf + '<div title="' + reference + '"></div>' + widget
                    self.assertEqual(self.probe.detect_challenge(200, {}, body), (
                        "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                    ))


class SelfClosingWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_self_closing_template_keeps_widgets_inert(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        widget = '<div data-sitekey="k"></div>'
        for template in (
            '<template/>' + widget + '</template>',
            '<template/><template/></template>' + widget + '</template>',
            '<template/>' + widget,
        ):
            with self.subTest(template=template):
                self.assertEqual(self.probe.detect_challenge(200, {}, cf + template), (
                    "none", ("body_cf_challenge_platform",),
                ))

    def test_self_closing_widget_is_recognized_after_template(self):
        cf = '<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>'
        for prefix in ("", "<template/></template>"):
            with self.subTest(prefix=prefix):
                body = cf + prefix + '<div data-sitekey="k"/>'
                self.assertEqual(self.probe.detect_challenge(200, {}, body), (
                    "captcha", ("body_cf_challenge_platform", "body_captcha_interactive"),
                ))


class RuleProvenanceTests(unittest.TestCase):
    """Where a rule came from is data, not a comment: it must survive review."""

    # One minimal body per unmeasured rule: firing that rule and nothing else.
    ASSUMED_SAMPLES = {
        "body_captcha": '<html><body><img id="captcha-history" src="/x.png"></body></html>',
        "body_captcha_interactive": '<html><body><div data-sitekey="k"></div></body></html>',
    }

    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_provenance_covers_every_rule_and_nothing_else(self):
        named = {name for name, _ in self.probe._BODY_RULES}
        named |= {name for name, _ in self.probe._SUPPORTING_BODY_RULES}
        named |= {"header_cf_mitigated", "body_captcha", "status_403", "status_429"}
        named.add("body_captcha_interactive")
        self.assertEqual(set(self.probe.RULE_PROVENANCE), named)

    def test_measured_rules_name_a_fixture_that_exists(self):
        for name, origin in self.probe.RULE_PROVENANCE.items():
            if not origin.startswith("fixture:"):
                continue
            with self.subTest(rule=name):
                # A renamed fixture must break the claim, not outlive it.
                self.assertTrue((FIXTURES / origin.split(":", 1)[1]).is_file(), origin)

    def test_assumed_rule_never_decides_a_verdict_alone(self):
        assumed = {n for n, o in self.probe.RULE_PROVENANCE.items()
                   if o == self.probe.ASSUMED}
        self.assertEqual(assumed, set(self.ASSUMED_SAMPLES), "sample missing for a rule")
        for name, body in self.ASSUMED_SAMPLES.items():
            with self.subTest(rule=name):
                verdict, markers = self.probe.detect_challenge(200, {}, body)
                self.assertEqual(verdict, "none")
                self.assertEqual(markers, (name,))

    def test_exact_provenance_of_both_unmeasured_rules(self):
        # Flipping this to "measured" has to be typed here as well: an assumption
        # cannot quietly become a fact between milestones.
        self.assertEqual(self.probe.RULE_PROVENANCE["body_captcha"], "assumed")
        self.assertEqual(self.probe.RULE_PROVENANCE["body_captcha_interactive"], "assumed")
        self.assertEqual(
            self.probe.RULE_PROVENANCE["body_just_a_moment"],
            "fixture:cf_interstitial_200body_403.html",
        )


class DecisiveTitleTests(unittest.TestCase):
    """The single decisive rule must not hang on the first <title> in the file."""

    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_inert_title_never_decides(self):
        cases = {
            "comment": '<html><head><!-- <title>Just a moment...</title> -->'
                       "<title>Offers</title></head><body>post</body></html>",
            "script": '<html><head><script>var t = "<title>Just a moment...</title>";'
                      "</script><title>Forum</title></head><body>post</body></html>",
            "template": "<html><head><template><title>Just a moment...</title></template>"
                        "<title>Shop</title></head><body>post</body></html>",
        }
        for where, body in cases.items():
            with self.subTest(where=where):
                # A forum post quoting a block page is not a block page.
                self.assertEqual(self.probe.detect_challenge(200, {}, body), ("none", ()))

    def test_real_title_still_decides(self):
        body = "<html><head><title>Just a moment...</title></head><body>x</body></html>"
        verdict, markers = self.probe.detect_challenge(200, {}, body)
        self.assertEqual(verdict, "suspected")
        self.assertEqual(markers, ("body_just_a_moment",))

    def test_output_title_field_is_left_alone(self):
        # _title() feeds the probe's output contract and must keep its behaviour.
        body = "<html><head><!-- <title>Ghost</title> --><title>Real</title></head></html>"
        self.assertEqual(self.probe._title(body), "Ghost")
        self.assertEqual(self.probe._decisive_title(body), "Real")


if __name__ == "__main__":
    unittest.main()
