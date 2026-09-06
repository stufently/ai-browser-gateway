"""Hand-computed incremental and unique arithmetic."""

from __future__ import annotations

import unittest

from bench.models import ChallengeType, FailureReason
from bench.report.coverage import CoverageRow, incremental, keep_decision, solved_cells
from bench.runner.record import RunRecord

# Fixture (success only), computed by hand:
#   cells: scenario:static, scenario:js, scenario:shadow, scenario:session, target:cf
#   curl:       static, session
#   httpx:      static, js
#   playwright: js, shadow, session
#   camoufox:   cf
# order = curl, httpx, playwright, camoufox
# incremental:
#   curl       {static, session}                                = 2
#   httpx      {static, js} - {static, session} = {js}          = 1
#   playwright {js, shadow, session} - {static,session,js}
#              = {shadow}                                       = 1
#   camoufox   {cf} - {static,session,js,shadow} = {cf}         = 1
# unique (exactly one solver, order-independent):
#   static: curl+httpx; session: curl+playwright; js: httpx+playwright
#   shadow: playwright only; cf: camoufox only
#   curl unique=0, httpx unique=0, playwright unique=1, camoufox unique=1
# total_cells = 5


def _rec(provider: str, cell: str, success: bool = True) -> RunRecord:
    kind, ident = cell.split(":", 1)
    return RunRecord(
        provider=provider,
        provider_version="1",
        scenario=ident if kind == "scenario" else None,
        target=ident if kind == "target" else None,
        run_id="r1",
        mode="warm",
        success=success,
        sentinel_found=success,
        status=200 if success else 403,
        final_url="http://x",
        challenge_type=ChallengeType.none,
        elapsed_ms=1,
        startup_ms=0,
        cpu_ms=1,
        peak_rss_mb=1.0,
        bytes=10,
        redirects=0,
        error_type=FailureReason.none if success else FailureReason.http_403,
        date="2026-09-06",
        kernel="t",
        docker_version="",
        image_version="",
        egress_ip="127.0.0.1",
        asn="0",
        cell=cell,
    )


def _fixture() -> list[RunRecord]:
    return [
        _rec("curl", "scenario:static"),
        _rec("curl", "scenario:session"),
        _rec("httpx", "scenario:static"),
        _rec("httpx", "scenario:js"),
        _rec("playwright", "scenario:js"),
        _rec("playwright", "scenario:shadow"),
        _rec("playwright", "scenario:session"),
        _rec("camoufox", "target:cf"),
    ]


class CoverageTests(unittest.TestCase):
    def test_solved_cells(self) -> None:
        got = solved_cells(_fixture())
        self.assertEqual(got["curl"], {"scenario:static", "scenario:session"})
        self.assertEqual(got["httpx"], {"scenario:static", "scenario:js"})

    def test_failed_records_are_not_solved(self) -> None:
        records = [_rec("curl", "scenario:static", success=False)]
        self.assertEqual(solved_cells(records), {})

    def test_incremental_arithmetic(self) -> None:
        rows_by = {
            row.provider: row
            for row in incremental(
                _fixture(), ["curl", "httpx", "playwright", "camoufox"]
            )
        }
        self.assertEqual(rows_by["httpx"].incremental, 1)
        self.assertEqual(rows_by["curl"].incremental, 2)
        self.assertEqual(rows_by["playwright"].incremental, 1)
        self.assertEqual(rows_by["camoufox"].incremental, 1)
        self.assertEqual(rows_by["curl"].solved, 2)
        self.assertEqual(rows_by["httpx"].solved, 2)
        self.assertEqual(rows_by["playwright"].solved, 3)
        self.assertEqual(rows_by["camoufox"].solved, 1)
        self.assertEqual(rows_by["curl"].total_cells, 5)

    def test_unique_arithmetic(self) -> None:
        rows_by = {
            row.provider: row
            for row in incremental(
                _fixture(), ["curl", "httpx", "playwright", "camoufox"]
            )
        }
        self.assertEqual(rows_by["curl"].unique, 0)
        self.assertEqual(rows_by["httpx"].unique, 0)
        self.assertEqual(rows_by["playwright"].unique, 1)
        self.assertEqual(rows_by["camoufox"].unique, 1)

    def test_provider_absent_from_order_is_value_error(self) -> None:
        records = _fixture() + [_rec("scrapingbee", "scenario:static")]
        with self.assertRaises(ValueError):
            incremental(records, ["curl", "httpx", "playwright", "camoufox"])

    def test_keep_by_incremental_threshold(self) -> None:
        row = CoverageRow("curl", solved=2, incremental=1, unique=0, total_cells=5)
        keep, reason = keep_decision(row, threshold=0.05)
        self.assertTrue(keep)
        self.assertIn("incremental", reason)

    def test_keep_by_unique_even_if_incremental_low(self) -> None:
        row = CoverageRow("x", solved=1, incremental=0, unique=1, total_cells=20)
        keep, _ = keep_decision(row, 0.05)
        self.assertTrue(keep)

    def test_drop_when_neither(self) -> None:
        row = CoverageRow("x", solved=3, incremental=0, unique=0, total_cells=20)
        keep, _ = keep_decision(row, 0.05)
        self.assertFalse(keep)

    def test_threshold_is_a_parameter(self) -> None:
        row = CoverageRow("x", solved=1, incremental=1, unique=0, total_cells=100)
        keep_high, _ = keep_decision(row, 0.05)
        self.assertFalse(keep_high)
        keep_low, _ = keep_decision(row, 0.01)
        self.assertTrue(keep_low)


if __name__ == "__main__":
    unittest.main()
