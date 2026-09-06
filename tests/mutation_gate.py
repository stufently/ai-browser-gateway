"""Prove the suite kills the six required mutants. Restore files in finally."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", "/tmp"),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "TERM": "dumb",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONPATH": str(ROOT),
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
}

MUTANTS = [
    {
        "name": "1",
        "file": "bench/models.py",
        "old": "        return (False, FailureReason.content_missing)",
        "new": "        return (True, FailureReason.none)",
        "test": "tests.test_models.EvaluateTests.test_http_200_without_sentinel_is_not_success",
        "assert": "self.assertFalse(ok)",
    },
    {
        "name": "2",
        "file": "bench/report/coverage.py",
        "old": "        added = solved - already",
        "new": "        added = set(solved)",
        "test": "tests.test_coverage.CoverageTests.test_incremental_arithmetic",
        "assert": 'self.assertEqual(rows_by["httpx"].incremental, 1)',
    },
    {
        "name": "3",
        "file": "bench/report/coverage.py",
        "old": "        if len(who) == 1:",
        "new": "        if len(who) >= 1:",
        "test": "tests.test_coverage.CoverageTests.test_unique_arithmetic",
        "assert": 'self.assertEqual(rows_by["curl"].unique, 0)',
    },
    {
        "name": "4",
        "file": "bench/scenarios.py",
        "old": '        sentinel="ABG_TEST_SPA_OK",',
        "new": '        sentinel="ABG_TEST_JS_OK",',
        "test": "tests.test_scenarios.ScenarioTests.test_twelve_sentinels_are_all_different",
        "assert": "self.assertEqual(len(set(sentinels)), 12)",
    },
    {
        "name": "5",
        "file": "bench/server/app.py",
        "old": "document.getElementById('root').textContent = 'ABG_TEST_' + 'JS_OK';",
        "new": "document.getElementById('root').textContent = 'ABG_TEST_JS_OK';",
        "test": "tests.test_server_app.ServerAppTests.test_js_raw_html_has_no_sentinel",
        "assert": "self.assertNotIn(js_sentinel, raw_html)",
    },
    {
        "name": "6",
        "file": "bench/report/render.py",
        "old": '"не измерено"',
        "new": '"99.9"',
        "test": "tests.test_render.RenderTests.test_unmeasured_row_is_literal_not_a_number",
        "assert": 'self.assertIn("не измерено", rendered)',
    },
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_test(test_id: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", test_id],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _first_assert_line(output: str) -> str:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        normalized = line.replace("\\", "/")
        if "File " in line and "/tests/" in normalized:
            if index + 1 < len(lines):
                return lines[index + 1].strip()
    return ""


def _apply(item: dict) -> dict:
    path = ROOT / item["file"]
    original = path.read_bytes()
    digest = _sha256(original)
    text = original.decode("utf-8")
    result = {
        "name": item["name"],
        "file": item["file"],
        "killed": False,
        "line": "",
        "detail": "",
    }
    try:
        count = text.count(item["old"])
        if count != 1:
            result["detail"] = f"fragment occurs {count} times, want 1"
            return result
        rc_clean, out_clean = _run_test(item["test"])
        if rc_clean != 0:
            result["detail"] = "clean test was not green"
            result["line"] = _first_assert_line(out_clean)
            return result
        path.write_text(text.replace(item["old"], item["new"], 1), encoding="utf-8")
        rc_mut, out_mut = _run_test(item["test"])
        line = _first_assert_line(out_mut)
        result["line"] = line
        if rc_mut != 0 and line == item["assert"]:
            result["killed"] = True
        else:
            result["detail"] = (
                f"rc={rc_mut} line={line!r} want {item['assert']!r}\n{out_mut}"
            )
        return result
    finally:
        path.write_bytes(original)
        if _sha256(path.read_bytes()) != digest:
            raise RuntimeError(f"restore failed for {path}")


def main() -> int:
    reports = []
    for item in MUTANTS:
        reports.append(_apply(item))
    failed = False
    for report in reports:
        status = "убит" if report["killed"] else "выжил"
        print(f"{report['name']} {report['file']}: {status} | {report['line']}")
        if report["detail"]:
            print(report["detail"])
        if not report["killed"]:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
