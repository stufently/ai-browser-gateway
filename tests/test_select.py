"""Selection rule: coverage qualified by freshness, order taken from data."""

from __future__ import annotations

import random
import unittest

from bench.models import FailureReason
from bench.report.build import build_report
from bench.report.select import canonical_order, keep_set
from tests.m4_helpers import record
from tests.m6_helpers import (
    BIZPROFILE,
    LOWENDTALK,
    RSS_AGE,
    WAYBACK_AGE,
    fixture_records,
    write_real_run,
)


def _nonempty(records):
    if not records:
        raise AssertionError("fixture is empty")
    return records


class EmptySetTests(unittest.TestCase):
    def test_empty_records_are_empty_results(self):
        self.assertEqual(keep_set([]), {})
        self.assertEqual(canonical_order([]), [])

    def test_empty_is_not_keep_everyone(self):
        self.assertEqual(len(keep_set([])), 0)


class CanonicalOrderTests(unittest.TestCase):
    def test_order_comes_from_tier_cpu_name_not_registry_rows(self):
        records = _nonempty(fixture_records())
        providers = {item.provider for item in records}
        self.assertEqual(len(providers), 3, providers)
        self.assertEqual(canonical_order(records), ["rss", "wayback", "curl"])

    def test_reversing_registry_does_not_change_order(self):
        import bench.providers.registry as registry

        records = _nonempty(fixture_records())
        before = canonical_order(records)
        original = registry.PROVIDERS
        registry.PROVIDERS = tuple(reversed(list(original)))
        try:
            after = canonical_order(records)
        finally:
            registry.PROVIDERS = original
        self.assertEqual(before, after)

    def test_order_ignores_record_sequence(self):
        records = _nonempty(fixture_records())
        expected = canonical_order(records)
        shuffled = list(records)
        shuffled.reverse()
        self.assertEqual(canonical_order(shuffled), expected)

    def test_failed_cpu_is_not_a_median_sample(self):
        cheap_fail = record("curl", LOWENDTALK, success=False, cpu_ms=1)
        expensive_ok = record("curl", BIZPROFILE, cpu_ms=500)
        other = record("rss", LOWENDTALK, entrance_age_hours=RSS_AGE, cpu_ms=10)
        order = canonical_order([cheap_fail, expensive_ok, other])
        self.assertEqual(order[0], "rss")
        self.assertEqual(order[1], "curl")

    def test_name_breaks_tier_and_cpu_tie(self):
        later = record("wayback", "target:x", cpu_ms=500)
        earlier = record("curl", "target:y", cpu_ms=500)
        records = _nonempty([later, earlier])
        self.assertEqual(canonical_order(records), ["curl", "wayback"])
        self.assertEqual(canonical_order([earlier, later]), ["curl", "wayback"])


class OrderIndependenceTests(unittest.TestCase):
    def test_fixture_keep_set_is_byte_identical_after_shuffle(self):
        records = _nonempty(fixture_records())
        providers = {item.provider for item in records}
        self.assertEqual(len(providers), 3, providers)
        cells = {item.cell for item in records}
        self.assertGreaterEqual(len(cells), 2, cells)
        ages = {item.entrance_age_hours for item in records if item.success}
        self.assertGreaterEqual(len(ages), 2, ages)
        first_order = canonical_order(records)
        first_keep = keep_set(records)
        seen = 0
        rng = random.Random(0)
        for _ in range(20):
            shuffled = list(records)
            rng.shuffle(shuffled)
            self.assertEqual(canonical_order(shuffled), first_order)
            self.assertEqual(keep_set(shuffled), first_keep)
            seen += 1
        self.assertEqual(seen, 20)

    def test_equivalent_coverage_keeps_cheaper_regardless_of_record_order(self):
        cheap = record("curl", LOWENDTALK, cpu_ms=10)
        costly = record("wayback", LOWENDTALK, cpu_ms=100)
        records = _nonempty([costly, cheap])
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 1, ages)
        forward = keep_set(records)
        backward = keep_set([cheap, costly])
        self.assertEqual(forward, backward)
        self.assertTrue(forward["curl"][0], forward["curl"])
        self.assertFalse(forward["wayback"][0], forward["wayback"])

    def test_two_useful_cells_keep_reason_byte_identical(self):
        first = record("primp", "target:d", entrance_age_hours=0.5, cpu_ms=219)
        second = record("primp", "target:c", entrance_age_hours=0.5, cpu_ms=219)
        records = _nonempty([first, second])
        cells = {item.cell for item in records}
        self.assertEqual(len(cells), 2, cells)
        forward = keep_set(records)
        backward = keep_set([second, first])
        self.assertEqual(forward, backward)
        self.assertEqual(forward["primp"][1], "клетка `target:c`; клетка `target:d`")


class RegressionTests(unittest.TestCase):
    def test_rss_and_wayback_kept_curl_dropped_any_record_order(self):
        records = _nonempty(fixture_records())
        providers = {item.provider for item in records}
        self.assertEqual(providers, {"curl", "rss", "wayback"})
        for sequence in (records, list(reversed(records))):
            decisions = keep_set(sequence)
            self.assertEqual(set(decisions), {"curl", "rss", "wayback"})
            self.assertTrue(decisions["rss"][0], decisions["rss"])
            self.assertTrue(decisions["wayback"][0], decisions["wayback"])
            self.assertFalse(decisions["curl"][0], decisions["curl"])
            self.assertIn("cf-lowendtalk", decisions["rss"][1])

    def test_fresh_provider_kept_when_stale_is_cheaper(self):
        stale = record(
            "wayback", LOWENDTALK, entrance_age_hours=WAYBACK_AGE, cpu_ms=1
        )
        fresh = record("rss", LOWENDTALK, entrance_age_hours=RSS_AGE, cpu_ms=100)
        records = _nonempty([stale, fresh])
        ages = {item.entrance_age_hours for item in records if item.success}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["wayback"][0], decisions["wayback"])
        self.assertTrue(decisions["rss"][0], decisions["rss"])
        self.assertIn("свежее", decisions["rss"][1])
        self.assertIn("cf-lowendtalk", decisions["rss"][1])


class AgeSemanticsTests(unittest.TestCase):
    def test_unknown_age_does_not_cover_known(self):
        unknown = record("rss", LOWENDTALK, entrance_age_hours=None, cpu_ms=1)
        known = record(
            "wayback", LOWENDTALK, entrance_age_hours=WAYBACK_AGE, cpu_ms=100
        )
        records = _nonempty([unknown, known])
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["rss"][0], decisions["rss"])
        self.assertTrue(decisions["wayback"][0], decisions["wayback"])

    def test_known_age_does_not_cover_unknown(self):
        known = record(
            "rss", LOWENDTALK, entrance_age_hours=WAYBACK_AGE, cpu_ms=1
        )
        unknown = record("wayback", LOWENDTALK, entrance_age_hours=None, cpu_ms=100)
        records = _nonempty([known, unknown])
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["rss"][0], decisions["rss"])
        self.assertTrue(decisions["wayback"][0], decisions["wayback"])

    def test_ages_within_tolerance_are_comparable(self):
        older = record("curl", LOWENDTALK, entrance_age_hours=1.0, cpu_ms=1)
        newer = record("rss", LOWENDTALK, entrance_age_hours=1.5, cpu_ms=100)
        records = _nonempty([older, newer])
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["curl"][0], decisions["curl"])
        self.assertFalse(decisions["rss"][0], decisions["rss"])

    def test_ages_beyond_tolerance_are_not_comparable(self):
        stale = record("curl", LOWENDTALK, entrance_age_hours=5.0, cpu_ms=1)
        fresh = record("rss", LOWENDTALK, entrance_age_hours=0.5, cpu_ms=100)
        records = _nonempty([stale, fresh])
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["curl"][0], decisions["curl"])
        self.assertTrue(decisions["rss"][0], decisions["rss"])

    def test_repeat_unknown_and_known_still_cover_unknown(self):
        records = _nonempty(
            [
                record("wayback", LOWENDTALK, entrance_age_hours=None, cpu_ms=10),
                record("wayback", LOWENDTALK, entrance_age_hours=5.0, cpu_ms=10),
                record("rss", LOWENDTALK, entrance_age_hours=None, cpu_ms=20),
            ]
        )
        ages = {item.entrance_age_hours for item in records}
        self.assertEqual(len(ages), 2, ages)
        decisions = keep_set(records)
        self.assertTrue(decisions["wayback"][0], decisions["wayback"])
        self.assertFalse(decisions["rss"][0], decisions["rss"])

    def test_keep_set_returns_measurement_as_third_field(self):
        stale_first = keep_set(
            [
                record("wayback", "target:a", entrance_age_hours=400.0, cpu_ms=10),
                record("rss", "target:a", entrance_age_hours=0.5, cpu_ms=20),
            ]
        )
        plain = keep_set(
            [
                record("curl", "target:a", entrance_age_hours=None, cpu_ms=10),
                record("rss", "target:b", entrance_age_hours=None, cpu_ms=20),
            ]
        )
        for decision in list(stale_first.values()) + list(plain.values()):
            self.assertEqual(len(decision), 3, decision)
        self.assertEqual(stale_first["rss"][2], "свежесть")
        self.assertEqual(plain["rss"][2], "покрытие")
        self.assertEqual(stale_first["wayback"][2], "покрытие")


class NotMeasuredTests(unittest.TestCase):
    def test_only_not_measured_is_not_kept(self):
        records = _nonempty(
            [
                record(
                    "rss",
                    LOWENDTALK,
                    success=False,
                    error_type=FailureReason.not_measured,
                )
            ]
        )
        decisions = keep_set(records)
        self.assertEqual(set(decisions), {"rss"})
        self.assertFalse(decisions["rss"][0], decisions["rss"])

    def test_not_measured_does_not_discard_success(self):
        records = _nonempty(
            [
                record(
                    "rss",
                    LOWENDTALK,
                    entrance_age_hours=RSS_AGE,
                    cpu_ms=933,
                ),
                record(
                    "rss",
                    BIZPROFILE,
                    success=False,
                    error_type=FailureReason.not_measured,
                ),
            ]
        )
        decisions = keep_set(records)
        self.assertTrue(decisions["rss"][0], decisions["rss"])

    def test_not_measured_does_not_cover_another_provider(self):
        records = _nonempty(
            [
                record(
                    "rss",
                    LOWENDTALK,
                    success=False,
                    error_type=FailureReason.not_measured,
                    cpu_ms=1,
                ),
                record(
                    "wayback",
                    LOWENDTALK,
                    entrance_age_hours=WAYBACK_AGE,
                    cpu_ms=100,
                ),
            ]
        )
        decisions = keep_set(records)
        self.assertFalse(decisions["rss"][0], decisions["rss"])
        self.assertTrue(decisions["wayback"][0], decisions["wayback"])

    def test_not_measured_does_not_change_others_when_added(self):
        base = _nonempty(
            [record("curl", LOWENDTALK, entrance_age_hours=None, cpu_ms=10)]
        )
        extra = record(
            "rss",
            BIZPROFILE,
            success=False,
            error_type=FailureReason.not_measured,
        )
        base_decisions = keep_set(base)
        mixed = keep_set(base + [extra])
        self.assertEqual(base_decisions["curl"], mixed["curl"])
        self.assertFalse(mixed["rss"][0], mixed["rss"])


class ReportSelectionTests(unittest.TestCase):
    def _rss_decision_rows(self, text: str) -> list[str]:
        section = text.split("## Incremental coverage", 1)[1]
        return [
            line
            for line in section.splitlines()
            if line.startswith("| rss |")
        ]

    def test_report_keeps_rss_and_drops_curl(self):
        path = write_real_run()
        text = build_report(path, order=["curl", "wayback", "rss"])
        rows = self._rss_decision_rows(text)
        self.assertTrue(rows, text)
        self.assertNotIn("исключить", rows[0])
        self.assertIn("оставить", rows[0])
        curl_rows = [
            line
            for line in text.split("## Incremental coverage", 1)[1].splitlines()
            if line.startswith("| curl |")
        ]
        self.assertTrue(any("исключить" in line for line in curl_rows), text)

    def test_report_decision_does_not_follow_cli_order(self):
        path = write_real_run()
        first = build_report(path, order=["curl", "wayback", "rss"])
        second = build_report(path, order=["rss", "curl", "wayback"])
        self.assertNotIn("исключить", self._rss_decision_rows(first)[0])
        self.assertNotIn("исключить", self._rss_decision_rows(second)[0])

    def test_report_names_the_deciding_measurement(self):
        path = write_real_run()
        text = build_report(path, order=["curl", "wayback", "rss"])
        header = [
            line
            for line in text.splitlines()
            if line.startswith("| Провайдер |") and "Решение" in line
        ]
        self.assertTrue(header, text)
        self.assertIn("Измерение", header[0])
        self.assertTrue(
            any(word in text for word in ("покрытие", "свежесть")),
            text,
        )

    def test_report_has_no_hidden_decision_comment(self):
        path = write_real_run()
        text = build_report(path, order=["curl", "wayback", "rss", "playwright"])
        self.assertNotIn("<!--", text)
        section = text.split("## Incremental coverage", 1)[1]
        playwright_rows = [
            line for line in section.splitlines() if line.startswith("| playwright |")
        ]
        self.assertTrue(playwright_rows, text)
        self.assertTrue(all("incremental" not in line for line in playwright_rows), text)


if __name__ == "__main__":
    unittest.main()

class CoordinatorFindingsTests(unittest.TestCase):
    """Найдено на приёмке захода исправлений, закрыто постановщиком."""

    def test_name_breaks_tie_across_many_providers(self):
        """Ничья на ДВУХ именах разрывается порядком множества в половине прогонов.

        canonical_order сортирует set, поэтому без имени в ключе результат
        зависит от PYTHONHASHSEED: замерено 5 совпадений с алфавитом на 12
        семян. Восемь имён делают такое совпадение практически невозможным.
        """
        names = [f"probe{index}" for index in range(8)]
        records = _nonempty([
            record(name, f"target:{name}", cpu_ms=500, entrance_age_hours=None)
            for name in names
        ])
        self.assertEqual(len(set(names)), 8)
        self.assertEqual(canonical_order(records), sorted(names))

    def test_fresh_observation_is_not_absorbed_by_a_stale_one(self):
        """Один протухший замер кандидата не отменяет его же свежий."""
        records = _nonempty([
            record("wayback", "target:a", cpu_ms=10, entrance_age_hours=400.0),
            record("rss", "target:a", cpu_ms=20, entrance_age_hours=0.01),
            record("rss", "target:a", cpu_ms=20, entrance_age_hours=500.0),
        ])
        keep, reason, axis = keep_set(records)["rss"]
        self.assertTrue(keep, reason)
        self.assertEqual(axis, "свежесть")

    def test_decision_is_a_plain_three_field_tuple(self):
        """len()==3 при итерации на два поля — ловушка: list() молча терял ось."""
        decision = keep_set(fixture_records())["rss"]
        self.assertEqual(len(list(decision)), 3, decision)
        keep, reason, axis = decision
        self.assertTrue(keep, reason)
        self.assertIn(axis, ("покрытие", "свежесть"))
