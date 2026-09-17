"""Prove the suite kills retained M8 scrapling mutants. Restore files in finally."""

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
        "file": "bench/providers/docker/probe.py",
        "old": "    solve_cloudflare = True",
        "new": "    solve_cloudflare = False",
        "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
        "assert": 'self.assertIs(captured["fetch"][1]["solve_cloudflare"], True)',
    },
    {
        "name": "2",
        "file": "bench/providers/docker/probe.py",
        "old": '        self.version = _version("scrapling")',
        "new": '        self.version = "unknown"',
        "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_reports_package_version",
        "assert": 'self.assertEqual(result["provider_version"], "0.4.15")',
    },
    {
        "name": "3",
        "file": "bench/providers/docker/probe.py",
        "old": "        headers = _normalize_headers(getattr(response, \"headers\", None))",
        "new": "        headers = None",
        "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_preserves_cf_header_outside_2xx",
        "assert": 'self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})',
    },
    {
        "name": "4",
        "file": "bench/providers/docker/probe.py",
        "old": '        "scrapling": ScraplingAdapter,\n',
        "new": "",
        "test": "tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling",
        "assert": "self.assertIsInstance(adapter, self.probe.ScraplingAdapter)",
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
