"""Twelve scenarios, twelve distinct sentinels."""

from __future__ import annotations

import unittest

from bench.scenarios import SCENARIOS, by_id


class ScenarioTests(unittest.TestCase):
    def test_exactly_twelve_scenarios(self) -> None:
        self.assertEqual(len(SCENARIOS), 12)

    def test_twelve_sentinels_are_all_different(self) -> None:
        sentinels = [item.sentinel for item in SCENARIOS]
        self.assertEqual(len(set(sentinels)), 12)

    def test_sentinels_match_the_required_shape(self) -> None:
        for item in SCENARIOS:
            self.assertTrue(
                item.sentinel.startswith("ABG_TEST_") and item.sentinel.endswith("_OK"),
                item.sentinel,
            )

    def test_ids_follow_the_plan_order(self) -> None:
        self.assertEqual(
            [item.id for item in SCENARIOS],
            [
                "static",
                "redirect",
                "compression",
                "js",
                "spa",
                "iframe",
                "shadow",
                "session",
                "errors",
                "slow",
                "broken_js",
                "large_dom",
            ],
        )

    def test_by_id_returns_the_named_scenario(self) -> None:
        self.assertIs(by_id("js"), next(item for item in SCENARIOS if item.id == "js"))

    def test_unknown_id_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            by_id("no-such-scenario")

    def test_errors_scenario_has_a_sentinel_but_expected_status_from_subpath(self) -> None:
        item = by_id("errors")
        self.assertEqual(item.expected_status, 403)
        self.assertTrue(item.sentinel)
        self.assertIn("explain", item.description)

    def test_compression_description_mentions_brotli_limit_when_missing(self) -> None:
        item = by_id("compression")
        try:
            import brotli  # noqa: F401
        except ImportError:
            self.assertIn("standard library has no brotli", item.description)


if __name__ == "__main__":
    unittest.main()
