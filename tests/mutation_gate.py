"""Prove the suite kills the retained M1 and additional M2 mutants. Restore files in finally."""

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
    {
        "name": "7",
        "file": "bench/report/coverage.py",
        "old": "    total = len(all_cells)",
        "new": "    total = len(holders)",
        "test": "tests.test_coverage.CoverageTests.test_total_cells_includes_unsolved",
        "assert": "self.assertEqual(rows[0].total_cells, 2)",
    },
    {
        "name": "8",
        "file": "bench/report/coverage.py",
        "old": "        solved = by_provider.get(provider, set())",
        "new": "        solved = by_provider[provider]",
        "test": "tests.test_coverage.CoverageTests.test_provider_without_successes_is_zero_not_missing",
        "assert": "rows = incremental(",
    },
    {
        "name": "9",
        "file": "bench/report/coverage.py",
        "old": "    all_cells: set[str] = set()",
        "new": "    all_cells: set[str] = {records[0].cell}",
        "test": "tests.test_coverage.CoverageTests.test_incremental_empty_records",
        "assert": 'rows = incremental([], ["curl"])',
    },
    {
        "name": "10",
        "file": "bench/report/coverage.py",
        "old": "    ratio = (row.incremental / row.total_cells) if row.total_cells else 0.0",
        "new": "    ratio = row.incremental / row.total_cells",
        "test": "tests.test_coverage.CoverageTests.test_keep_decision_zero_total_cells",
        "assert": "keep, reason = keep_decision(row)",
    },
    {
        "name": "11",
        "file": "bench/runner/record.py",
        "old": '    return json.dumps(asdict(record), ensure_ascii=False) + "\\n"',
        "new": "    return json.dumps(asdict(record), ensure_ascii=False)",
        "test": "tests.test_record.RecordTests.test_two_jsonl_lines_are_two_records",
        "assert": "self.assertEqual(len(lines), 2)",
    },
    {
        "name": "12",
        "file": "bench/runner/record.py",
        "old": (
            "def to_jsonl_line(record: RunRecord) -> str:\n"
            "    validate(record)\n"
            '    return json.dumps(asdict(record), ensure_ascii=False) + "\\n"'
        ),
        "new": (
            "def to_jsonl_line(record: RunRecord) -> str:\n"
            '    return json.dumps(asdict(record), ensure_ascii=False) + "\\n"'
        ),
        "test": "tests.test_record.RecordTests.test_to_jsonl_rejects_unknown_mode",
        "assert": "with self.assertRaises(ValueError) as ctx:",
    },
    {
        "name": "13",
        "file": "bench/runner/record.py",
        "old": "    validate(record)\n    return record",
        "new": "    return record",
        "test": "tests.test_record.RecordTests.test_from_jsonl_rejects_unknown_mode",
        "assert": "with self.assertRaises(ValueError) as ctx:",
    },
    {
        "name": "14",
        "file": "bench/runner/record.py",
        "old": '        target=raw["target"],',
        "new": "        target=None,",
        "test": "tests.test_record.RecordTests.test_roundtrip_filled_target",
        "assert": 'self.assertEqual(got.target, "bizprofile.net")',
    },
    {
        "name": "15",
        "file": "bench/runner/record.py",
        "old": '        error_type=FailureReason(raw["error_type"]),',
        "new": "        error_type=FailureReason.none,",
        "test": "tests.test_record.RecordTests.test_roundtrip_failure_with_reason",
        "assert": "self.assertEqual(got.error_type, FailureReason.http_403)",
    },
    {
        "name": "16",
        "file": "bench/models.py",
        "old": "    if result.status is not None and 500 <= result.status <= 599:",
        "new": "    if result.status is not None and 500 < result.status <= 599:",
        "test": "tests.test_models.EvaluateTests.test_status_500_is_http_5xx",
        "assert": "self.assertEqual(reason, FailureReason.http_5xx)",
    },
    {
        "name": "17",
        "file": "bench/models.py",
        "old": "    if result.status is not None and 500 <= result.status <= 599:",
        "new": "    if result.status is not None and 500 <= result.status < 599:",
        "test": "tests.test_models.EvaluateTests.test_status_599_is_http_5xx",
        "assert": "self.assertEqual(reason, FailureReason.http_5xx)",
    },
    {'name': '18',
     'file': 'bench/providers/registry.py',
     'old': "    argv = ['docker', 'run', '--rm', '--user', '1002:1002']",
     'new': "    argv = ['docker', 'run', '--rm']",
     'test': 'tests.test_registry.RegistryTests.test_nonroot_and_no_mount',
     'assert': "self.assertIn('--user', argv)"},
    {'name': '19',
     'file': 'bench/runner/matrix.py',
     'old': "            if provider.kind == 'browser':",
     'new': "            if provider.kind in ('browser', 'http'):",
     'test': 'tests.test_matrix.MatrixTests.test_http_has_no_warm',
     'assert': "self.assertNotIn(('curl', 'warm'), {(p.provider, p.mode) for p in plan})"},
    {'name': '20',
     'file': 'bench/runner/execute.py',
     'old': '            if rc != 0:\n                failure = FailureReason.provider_error',
     'new': '            if rc != 0:\n                raise RuntimeError(stderr)',
     'test': 'tests.test_execute.ExecuteTests.test_failed_exit_is_a_record',
     'assert': "records = execute_plan(self.plan(), launcher=FakeLauncher((1, '', 'boom')), cells=CELLS, env={})"},
    {'name': '21',
     'file': 'bench/providers/registry.py',
     'old': 'json.loads(candidates[-1])',
     'new': 'json.loads(candidates[0])',
     'test': 'tests.test_registry.RegistryTests.test_last_json_line',
     'assert': "self.assertEqual(got, {'ok': True})"},
    {'name': '22',
     'file': 'bench/runner/environment.py',
     'old': "else 'unknown'",
     'new': "else '127.0.0.1'",
     'test': 'tests.test_environment.EnvironmentTests.test_missing_is_unknown',
     'assert': "self.assertEqual(result, dict.fromkeys(('date', 'kernel', 'docker_version', 'egress_ip', 'asn'), "
               "'unknown'))"},
    {'name': '23',
     'file': 'bench/report/build.py',
     'old': '        records = read_records(source)',
     'new': '        records = list(read_records(source))',
     'test': 'tests.test_report_build.ReportBuildTests.test_passes_a_stream_to_coverage',
     'assert': "self.assertTrue(observed['iterator'])"},
    {'name': '24',
     'file': 'bench/runner/execute.py',
     'old': '            sleep(pause_s)',
     'new': '            sleep(0)',
     'test': 'tests.test_execute.ExecuteTests.test_pause_before_repeated_host_including_failed_requests',
     'assert': "self.assertEqual(events, ['run', 'run', 20, 'run'])"},
    {'name': '25',
     'file': 'bench/runner/execute.py',
     'old': "        argv.extend(['--mode', item.mode])",
     'new': "        argv.extend(['--mode', 'cold'])",
     'test': 'tests.test_execute.ExecuteTests.test_modes_and_local_network',
     'assert': "self.assertEqual(argv[-2:], ['--mode', mode])"},
    {'name': '26',
     'file': 'bench/runner/execute.py',
     'old': "        network = 'host' if item.cell.startswith('scenario:') else None",
     'new': "        network = 'host'",
     'test': 'tests.test_execute.ExecuteTests.test_target_argv_has_no_network_option',
     'assert': "self.assertNotIn('--network', target_argv)"},
    {'name': '27',
     'file': 'bench/runner/execute.py',
     'old': "                            subprocess.run(['docker', 'rm', '--force', cid], timeout=30,\n"
            "                                           capture_output=True, stdin=subprocess.DEVNULL)",
     'new': '                            pass',
     'test': 'tests.test_execute.DockerLauncherTests.test_timeout_removes_container_from_cidfile',
     'assert': "self.assertEqual(calls[1:], [['docker', 'rm', '--force', 'test-container-id']])"},
    {'name': '28',
     'file': 'bench/report/build.py',
     'old': 'threshold=threshold',
     'new': 'threshold=0.05',
     'test': 'tests.test_report_build.ReportBuildTests.test_threshold_changes_coverage_decision',
     'assert': 'self.assertIn(expected, text)'},
    {'name': '29',
     'file': 'bench/runner/execute.py',
     'old': "        if item.mode not in ('cold', 'warm'):\n"
            "            raise ValueError(f'invalid mode: {item.mode}')\n",
     'new': '',
     'test': 'tests.test_execute.ExecuteTests.test_invalid_mode_in_manual_plan_fails_before_launch',
     'assert': "with self.assertRaisesRegex(ValueError, 'invalid mode'):"},
    {'name': '30',
     'file': 'bench/runner/execute.py',
     'old': ' or timeout <= 0',
     'new': '',
     'test': 'tests.test_execute.ExecuteTests.test_nonpositive_timeout_fails_before_launch',
     'assert': "with self.assertRaisesRegex(ValueError, 'timeout must be positive'):"},
    {'name': '31',
     'file': 'bench/runner/execute.py',
     'old': '    if len({item.run_id for item in plan}) != len(plan):\n'
            "        raise ValueError('duplicate run IDs')\n",
     'new': '',
     'test': 'tests.test_execute.ExecuteTests.test_duplicate_run_ids_in_manual_plan_fail_before_launch',
     'assert': "with self.assertRaisesRegex(ValueError, 'duplicate run IDs'):"},
    {'name': '32',
     'file': 'bench/providers/docker/probe.py',
     'old': '        for flag in ("--no-sandbox", "--disable-dev-shm-usage",\n'
            '                     "--disable-gpu", "--disable-dbus"):\n'
            '            options.add_argument(flag)\n',
     'new': '',
     'test': 'tests.test_probe.AdapterContractTests.'
             'test_pydoll_uses_required_start_options_and_unwraps_nested_cdp_value',
     'assert': 'self.assertEqual(options.arguments,'},
    {'name': '33',
     'file': 'bench/providers/docker/probe.py',
     'old': '    if header_verdict is not None:\n'
            '        return header_verdict, tuple(header_names + body_names + captcha_names)\n',
     'new': '    if False:\n'
            '        return header_verdict, tuple(header_names + body_names + captcha_names)\n',
     'test': 'tests.test_detect.DetectChallengeTests.test_cf_mitigated_header_outranks_clean_body',
     'assert': 'self.assertEqual(verdict, "suspected")'},
    {'name': '34',
     'file': 'bench/providers/docker/probe.py',
     'old': '        status_verdict = "access_denied"',
     'new': '        status_verdict = "suspected"',
     'test': 'tests.test_detect.DetectChallengeTests.test_bare_403_is_access_denied_not_suspected',
     'assert': 'self.assertEqual(verdict, "access_denied")'},
    {'name': '35',
     'file': 'bench/providers/docker/probe.py',
     'old': '        return "suspected", tuple(body_names + captcha_names)',
     'new': '        return "suspected", ()',
     'test': 'tests.test_detect.DetectChallengeTests.test_interstitial_fixture_is_suspected_with_named_rules',
     'assert': 'self.assertGreaterEqual(len(markers), 3)'},
    {'name': '36',
     'file': 'bench/escalate.py',
     'old': '    elif reason is FailureReason.content_missing:\n'
            '        if kind is ChallengeType.none:\n'
            '            step = Step.browser\n'
            '        else:\n'
            '            step = Step.change_egress\n',
     'new': '    elif reason is FailureReason.content_missing:\n'
            '        step = Step.browser\n',
     'test': 'tests.test_escalate.NextStepTests.test_content_missing_with_challenge_changes_egress',
     'assert': 'self.assertIs('},
    {'name': '37',
     'file': 'bench/escalate.py',
     'old': '    if egress_changed and step is Step.change_egress:\n'
            '        return Step.human\n',
     'new': '',
     'test': 'tests.test_escalate.NextStepTests.test_changed_egress_becomes_human',
     'assert': 'self.assertIs('},
    {'name': '38',
     'file': 'bench/providers/docker/probe.py',
     'old': '        header_map = _normalize_headers(json.loads(header_json))',
     'new': '        header_map = {}',
     'test': 'tests.test_probe.AdapterContractTests.test_curl_parses_header_json_as_last_write_out_field',
     'assert': 'self.assertEqual(result["headers"]["cf-mitigated"], "challenge")'},
    {'name': '39',
     'file': 'bench/providers/docker/probe.py',
     'old': '    if header_verdict is not None:\n'
            '        return header_verdict, tuple(header_names + body_names + captcha_names)\n'
            '    if body_enough:\n'
            '        return "suspected", tuple(body_names + captcha_names)\n',
     'new': '    if body_enough:\n'
            '        return "suspected", tuple(body_names + captcha_names)\n'
            '    if header_verdict is not None:\n'
            '        return header_verdict, tuple(header_names + body_names + captcha_names)\n',
     'test': 'tests.test_detect.DetectChallengeTests.test_interactive_header_outranks_body_markers',
     'assert': 'self.assertEqual(verdict, "interactive")'},
    {
        "name": "40",
        "file": "bench/providers/docker/probe.py",
        "old": '    ("body_cf_challenges_host", "challenges.cloudflare.com"),\n',
        "new": "",
        "test": "tests.test_detect.DetectChallengeTests.test_body_cf_challenges_host_is_named_with_title",
        "assert": 'self.assertIn("body_cf_challenges_host", markers)',
    },
    {
        "name": "41",
        "file": "bench/providers/docker/probe.py",
        "old": '    ("body_cf_chl_opt", "cf_chl_opt"),\n',
        "new": "",
        "test": "tests.test_detect.DetectChallengeTests.test_body_cf_chl_opt_is_named_with_title",
        "assert": 'self.assertIn("body_cf_chl_opt", markers)',
    },
    {
        "name": "42",
        "file": "bench/providers/docker/probe.py",
        "old": '    ("body_cf_chl", "__cf_chl"),\n',
        "new": "",
        "test": "tests.test_detect.DetectChallengeTests.test_body_cf_chl_is_named_with_title",
        "assert": 'self.assertIn("body_cf_chl", markers)',
    },
    {
        "name": "43",
        "file": "bench/providers/docker/probe.py",
        "old": '    ("body_cf_challenge_platform", "/cdn-cgi/challenge-platform"),\n',
        "new": "",
        "test": "tests.test_detect.DetectChallengeTests.test_body_cf_challenge_platform_is_named_with_title",
        "assert": 'self.assertIn("body_cf_challenge_platform", markers)',
    },
    {
        "name": "44",
        "file": "bench/providers/docker/probe.py",
        "old": '    body_enough = "body_just_a_moment" in body_names or len(decisive_body) >= 2',
        "new": '    body_enough = "body_just_a_moment" in body_names or len(decisive_body) >= 1',
        "test": "tests.test_detect.DetectChallengeTests.test_single_body_cf_challenges_host_is_not_suspected",
        "assert": 'self.assertEqual(verdict, "none")',
    },
    {
        "name": "45",
        "file": "bench/providers/docker/probe.py",
        "old": '        haystack = _title(text).lower() if name == "body_just_a_moment" else lowered\n',
        "new": "        haystack = lowered\n",
        "test": "tests.test_detect.DetectChallengeTests.test_just_a_moment_in_body_prose_is_not_a_challenge",
        "assert": 'self.assertEqual(verdict, "none")',
    },
    {
        "name": "46",
        "file": "bench/providers/docker/probe.py",
        "old": "    if captcha_names and captcha_confirmed:\n",
        "new": "    if captcha_names:\n",
        "test": "tests.test_detect.DetectChallengeTests.test_lone_captcha_attribute_is_none_but_named",
        "assert": 'self.assertEqual(verdict, "none")',
    },
    {
        "name": "47",
        "file": "bench/escalate.py",
        "old": "    elif reason is FailureReason.challenge_suspected:\n"
             "        step = Step.change_egress\n",
        "new": "    elif reason is FailureReason.challenge_suspected:\n"
             "        step = Step.browser\n",
        "test": "tests.test_escalate.NextStepTests.test_challenge_suspected_changes_egress",
        "assert": "self.assertIs(",
    },
    {
        "name": "48",
        "file": "bench/escalate.py",
        "old": "    if egress_changed and step is Step.change_egress:\n"
             "        return Step.human\n",
        "new": "    if egress_changed and step is Step.change_egress and reason is FailureReason.content_missing:\n"
             "        return Step.human\n",
        "test": "tests.test_escalate.NextStepTests.test_changed_egress_http_403_becomes_human",
        "assert": "self.assertIs(",
    },
    {
        "name": "49",
        "file": "bench/providers/docker/probe.py",
        "old": '    ("body_noindex_nofollow", "noindex,nofollow"),\n',
        "new": '    ("body_noindex_nofollow", "noindex,nofollow-absent"),\n',
        "test": "tests.test_detect.DetectChallengeTests.test_supporting_noindex_is_named_on_interstitial",
        "assert": 'self.assertIn("body_noindex_nofollow", markers)',
    },
    {
        "name": "50",
        "file": "bench/providers/docker/probe.py",
        "old": '        return "captcha", tuple(body_names + captcha_names)',
        "new": '        return "captcha", ()',
        "test": "tests.test_detect.DetectChallengeTests.test_captcha_with_403_is_captcha_and_named",
        "assert": 'self.assertIn("body_captcha", markers)',
    },
    {
        "name": "51",
        "file": "bench/escalate.py",
        "old": "    elif reason is FailureReason.javascript_required:\n"
             "        if kind is ChallengeType.none:\n"
             "            step = Step.browser\n"
             "        else:\n"
             "            step = Step.change_egress\n",
        "new": "    elif reason is FailureReason.javascript_required:\n"
             "        if kind is ChallengeType.none:\n"
             "            step = Step.browser\n"
             "        else:\n"
             "            step = Step.browser\n",
        "test": "tests.test_escalate.NextStepTests.test_javascript_required_with_challenge_changes_egress",
        "assert": "self.assertIs(",
    },
    {
        "name": "52",
        "file": "bench/providers/docker/probe.py",
        "old": "        return status_verdict, tuple(body_names + captcha_names + status_names)",
        "new": "        return status_verdict, tuple(status_names)",
        "test": "tests.test_detect.DetectChallengeTests.test_single_body_marker_on_403_keeps_rule_name",
        "assert": 'self.assertIn("body_cf_challenges_host", markers)',
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
