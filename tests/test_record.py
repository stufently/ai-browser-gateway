"""JSONL round-trip and validate refusals."""

from __future__ import annotations

import json
import unittest

from bench.models import ChallengeType, FailureReason
from bench.runner.record import RunRecord, from_jsonl_line, to_jsonl_line, validate


def _record(**kwargs) -> RunRecord:
    data = dict(
        provider="curl",
        provider_version="8.5",
        scenario="static",
        target=None,
        run_id="run-1",
        mode="warm",
        success=True,
        sentinel_found=True,
        status=200,
        final_url="http://stand/static",
        challenge_type=ChallengeType.none,
        elapsed_ms=12,
        startup_ms=3,
        cpu_ms=4,
        peak_rss_mb=12.5,
        bytes=240,
        redirects=0,
        error_type=FailureReason.none,
        date="2026-09-06T00:00:00Z",
        kernel="test-kernel",
        docker_version="",
        image_version="",
        egress_ip="127.0.0.1",
        asn="0",
        cell="scenario:static",
    )
    data.update(kwargs)
    return RunRecord(**data)


class RecordTests(unittest.TestCase):
    def test_jsonl_roundtrip(self) -> None:
        record = _record()
        line = to_jsonl_line(record)
        self.assertEqual(from_jsonl_line(line), record)

    def test_from_jsonl_rejects_missing_field(self) -> None:
        payload = json.loads(to_jsonl_line(_record()))
        del payload["run_id"]
        with self.assertRaises(ValueError) as ctx:
            from_jsonl_line(json.dumps(payload))
        self.assertIn("run_id", str(ctx.exception))

    def test_validate_rejects_unknown_mode(self) -> None:
        record = _record(mode="hot")
        with self.assertRaises(ValueError) as ctx:
            validate(record)
        self.assertIn("mode", str(ctx.exception))

    def test_validate_rejects_negative_elapsed_ms(self) -> None:
        record = _record(elapsed_ms=-1)
        with self.assertRaises(ValueError) as ctx:
            validate(record)
        self.assertIn("elapsed_ms", str(ctx.exception))

    def test_validate_rejects_success_with_error(self) -> None:
        record = _record(success=True, error_type=FailureReason.timeout)
        with self.assertRaises(ValueError) as ctx:
            validate(record)
        self.assertIn("success=True", str(ctx.exception))

    def test_two_jsonl_lines_are_two_records(self) -> None:
        blob = to_jsonl_line(_record(run_id="a")) + to_jsonl_line(_record(run_id="b"))
        lines = [line for line in blob.splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertEqual(from_jsonl_line(lines[0]).run_id, "a")
        self.assertEqual(from_jsonl_line(lines[1]).run_id, "b")

    def test_to_jsonl_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            to_jsonl_line(_record(mode="hot"))
        self.assertIn("mode", str(ctx.exception))

    def test_to_jsonl_rejects_negative_elapsed_ms(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            to_jsonl_line(_record(elapsed_ms=-1))
        self.assertIn("elapsed_ms", str(ctx.exception))

    def test_to_jsonl_rejects_success_with_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            to_jsonl_line(_record(success=True, error_type=FailureReason.timeout))
        self.assertIn("success=True", str(ctx.exception))

    def test_from_jsonl_rejects_unknown_mode(self) -> None:
        payload = json.loads(to_jsonl_line(_record()))
        payload["mode"] = "hot"
        with self.assertRaises(ValueError) as ctx:
            from_jsonl_line(json.dumps(payload))
        self.assertIn("mode", str(ctx.exception))

    def test_from_jsonl_rejects_negative_elapsed_ms(self) -> None:
        payload = json.loads(to_jsonl_line(_record()))
        payload["elapsed_ms"] = -1
        with self.assertRaises(ValueError) as ctx:
            from_jsonl_line(json.dumps(payload))
        self.assertIn("elapsed_ms", str(ctx.exception))

    def test_from_jsonl_rejects_success_with_error(self) -> None:
        payload = json.loads(to_jsonl_line(_record()))
        payload["error_type"] = FailureReason.timeout.value
        with self.assertRaises(ValueError) as ctx:
            from_jsonl_line(json.dumps(payload))
        self.assertIn("success=True", str(ctx.exception))

    def test_roundtrip_filled_target(self) -> None:
        record = _record(
            target="bizprofile.net",
            scenario=None,
            cell="target:bizprofile.net",
        )
        got = from_jsonl_line(to_jsonl_line(record))
        self.assertEqual(got.target, "bizprofile.net")
        self.assertEqual(got, record)

    def test_egress_profile_roundtrip_and_default(self) -> None:
        defaulted = from_jsonl_line(to_jsonl_line(_record()))
        self.assertEqual(defaulted.egress_profile, "direct")
        record = _record(egress_profile="gold")
        got = from_jsonl_line(to_jsonl_line(record))
        self.assertEqual(got.egress_profile, "gold")
        self.assertEqual(got, record)

    def test_gold_profile_jsonl_never_contains_proxy_url(self) -> None:
        line = to_jsonl_line(_record(egress_profile="gold"))
        self.assertIn("gold", line)
        for forbidden in ("@", "proxy.invalid", "pass"):
            self.assertNotIn(forbidden, line)

    def test_roundtrip_failure_with_reason(self) -> None:
        record = _record(
            success=False,
            sentinel_found=False,
            status=403,
            error_type=FailureReason.http_403,
        )
        got = from_jsonl_line(to_jsonl_line(record))
        self.assertEqual(got.error_type, FailureReason.http_403)
        self.assertFalse(got.success)
        self.assertEqual(got, record)


if __name__ == "__main__":
    unittest.main()
