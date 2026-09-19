"""Kill each M7 mutant at its own assertion and restore source bytes in finally."""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEST_PREFIX = "tests.test_gateway_engine.EngineTests."
MUTANTS = (
    {
        "name": "entrance freshness boundary",
        "old": "and reply.age_hours <= request.max_age_hours)",
        "new": "and reply.age_hours < request.max_age_hours)",
        "test": TEST_PREFIX + "test_entrance_age_equal_to_limit_is_accepted",
        "assert": 'self.assertEqual(out.provider, "rss")',
    },
    {
        "name": "browser route",
        "old": 'if decision is Step.browser:\n            purpose = "browser"',
        "new": 'if decision is Step.browser:\n            purpose = "egress"',
        "test": TEST_PREFIX + "test_browser_fills_missing_content",
        "assert": 'self.assertEqual(fetcher.routes, [("curl", "direct"), ("patchright", "direct")])',
    },
    {
        "name": "egress route",
        "old": 'elif decision is Step.change_egress:\n            purpose = "egress"',
        "new": 'elif decision is Step.change_egress:\n            purpose = "browser"',
        "test": TEST_PREFIX + "test_blocked_http_changes_egress_without_browser",
        "assert": 'self.assertEqual(fetcher.routes, [("curl", "direct"), ("curl", "gold")])',
    },
    {
        "name": "exhausted budget",
        "old": "if remaining <= 0:",
        "new": "if remaining < 0:",
        "test": TEST_PREFIX + "test_budget_at_zero_prevents_next_attempt",
        "assert": "self.assertEqual(len(fetcher.calls), 1)",
    },
    {
        "name": "egress state",
        "old": "egress_changed=egress_changed)",
        "new": "egress_changed=False)",
        "test": TEST_PREFIX + "test_second_block_needs_human_without_trying_another_profile",
        "assert": "self.assertEqual(out.step, Step.human)",
    },
    {
        "name": "formatter decimal clipping",
        "path": "gateway/format_html.py",
        "old": "self.feed(_clip_oversized_charrefs(html))",
        "new": "self.feed(html)",
        "test": "tests.test_gateway_format.FormatTests.test_markdown_oversized_decimal_reference",
        "assert": "self.fail(f'oversized decimal reference raised ValueError: {exc}')",
    },
    {
        "name": "formatter leading zeros",
        "path": "gateway/format_html.py",
        "old": 'digits = match.group(1).lstrip("0") or "0"',
        "new": "digits = match.group(1)",
        "test": "tests.test_gateway_format.FormatTests.test_markdown_decimal_reference_leading_zeros",
        "assert": "self.assertEqual(render_content(obj, 'markdown'), 'A')",
    },
    {
        "name": "formatter seven digit boundary",
        "path": "gateway/format_html.py",
        "old": "if len(digits) >= 8:",
        "new": "if len(digits) >= 7:",
        "test": "tests.test_gateway_format.FormatTests.test_markdown_seven_digit_unicode_reference",
        "assert": "self.assertEqual(render_content(obj, 'markdown'), '\\U0010fffd')",
    },
    {
        "name": "formatter reference semicolon",
        "path": "gateway/format_html.py",
        "old": 'return "&#" + digits + match.group(2)',
        "new": 'return "&#" + digits',
        "test": "tests.test_gateway_format.FormatTests.test_markdown_reference_semicolon_separates_following_digit",
        "assert": "self.assertEqual(render_content(obj, 'markdown'), 'A6')",
    },
    {
        "name": "formatter requires hash in numeric reference",
        "path": "gateway/format_html.py",
        "old": '_DECIMAL_CHARREF = re.compile(r"&#([0-9]+)(;?)")',
        "new": '_DECIMAL_CHARREF = re.compile(r"&#?([0-9]+)(;?)")',
        "test": "tests.test_gateway_format.FormatTests.test_markdown_escapes_ampersand_without_hash",
        "assert": "self.assertEqual(render_content(obj, 'markdown'), r'\\&65;6')",
    },
    {
        "name": "formatter preserves empty numeric reference",
        "path": "gateway/format_html.py",
        "old": 'return _DECIMAL_CHARREF.sub(replace, text)',
        "new": 'return _DECIMAL_CHARREF.sub(replace, text).replace("&#;", "\\ufffd")',
        "test": "tests.test_gateway_format.FormatTests.test_markdown_escapes_empty_numeric_reference",
        "assert": "self.assertEqual(render_content(obj, 'markdown'), r'\\&\\#;')",
    },
    {
        "name": "worker preserves check failure cause",
        "path": "tests/deployed_m12b.py",
        "old": "value = {'internal_error': 'worker_check', 'cause': str(exc)}",
        "new": "value = {'internal_error': 'worker_failure'}",
        "test": "tests.test_deployed_m12b.WorkerTests.test_api_http_error_preserves_status",
        "assert": "self.assertEqual(result, expected)",
    },
    {
        "name": "worker caller reports failure cause",
        "path": "tests/deployed_m12b.py",
        "old": "raise CheckError(redact(error))",
        "new": "raise CheckError('worker_internal_error')",
        "test": "tests.test_deployed_m12b.WorkerTests.test_worker_call_reports_failure_cause",
        "assert": "self.assertEqual(results, expected)",
    },
)


def _run_test(test_id: str) -> tuple[int, str]:
    # -B prevents writes; a fresh cache prefix also prevents reading stale pyc
    # files for same-size mutations made within the same timestamp tick.
    with tempfile.TemporaryDirectory(prefix="gateway-mutant-pycache-") as cache:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
            "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0", "PYTHONPYCACHEPREFIX": cache,
        }
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", test_id],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
    return proc.returncode, proc.stdout + proc.stderr


def _assertion_frame(item: dict[str, str]) -> str:
    module, class_name, method = item["test"].rsplit(".", 2)
    path = ROOT / (module.replace(".", "/") + ".py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    test = next(node for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name == method)
    lines = source.splitlines()
    matches = [index + 1 for index in range(test.lineno - 1, test.end_lineno)
               if lines[index].strip() == item["assert"]]
    if len(matches) != 1:
        raise ValueError(f"expected one designated assertion in {item['test']}: {matches}")
    return f'  File "{path}", line {matches[0]}, in {method}\n    {item["assert"]}\n'


def _apply(item: dict[str, str]) -> bool:
    path = ROOT / item.get("path", "gateway/engine.py")
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    source = original.decode("utf-8")
    try:
        rc_clean, out_clean = _run_test(item["test"])
        if rc_clean != 0:
            print(f"{item['name']}: clean test is not green\n{out_clean}")
            return False
        count = source.count(item["old"])
        if count != 1:
            print(f"{item['name']}: fragment occurs {count} times, expected 1")
            return False
        frame = _assertion_frame(item)
        path.write_text(source.replace(item["old"], item["new"], 1), encoding="utf-8")
        rc_mutant, output = _run_test(item["test"])
        method = item["test"].rsplit(".", 1)[1]
        killed = (rc_mutant == 1 and "FAILED (failures=1)" in output
                  and f"FAIL: {method} (" in output and frame in output)
        if killed:
            print(f"{item['name']}: killed | {item['test']} | {item['assert']}")
        else:
            print(f"{item['name']}: NOT killed at designated assertion, rc={rc_mutant}\n{output}")
        return killed
    finally:
        path.write_bytes(original)
        restored = path.read_bytes()
        if restored != original or hashlib.sha256(restored).hexdigest() != digest:
            raise RuntimeError(f"source restoration failed: {path}")


def main() -> int:
    results = [_apply(item) for item in MUTANTS]
    print(f"Gateway mutants killed: {sum(results)}/{len(results)}; source restored")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
