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
     'old': '                if rc != 0:\n                    failure = FailureReason.provider_error',
     'new': '                if rc != 0:\n                    raise RuntimeError(stderr)',
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
     'old': 'decisions=selection',
     'new': 'decisions=None',
     'test': 'tests.test_report_build.ReportBuildTests.test_threshold_changes_coverage_decision',
     'assert': "self.assertNotIn('incremental 1/2 = 0.5000', low)"},
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
        "old": '        haystack = _decisive_title(text).lower() if name == "body_just_a_moment" else lowered\n',
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
    {'name': '53',
     'file': 'bench/providers/docker/probe.py',
     'old': '    "body_captcha": ASSUMED,',
     'new': '    "body_captcha": CF_INTERSTITIAL,',
     'test': 'tests.test_detect.RuleProvenanceTests.test_exact_provenance_of_the_one_unmeasured_rule',
     'assert': 'self.assertEqual(self.probe.RULE_PROVENANCE["body_captcha"], "assumed")'},
    {'name': '54',
     'file': 'bench/providers/docker/probe.py',
     'old': 'CF_INTERSTITIAL = "fixture:cf_interstitial_200body_403.html"',
     'new': 'CF_INTERSTITIAL = "fixture:renamed_since.html"',
     'test': 'tests.test_detect.RuleProvenanceTests.test_measured_rules_name_a_fixture_that_exists',
     'assert': 'self.assertTrue((FIXTURES / origin.split(":", 1)[1]).is_file(), origin)'},
    {'name': '55',
     'file': 'bench/providers/docker/probe.py',
     'old': '        haystack = _decisive_title(text).lower() if name == "body_just_a_moment" else lowered',
     'new': '        haystack = _title(text).lower() if name == "body_just_a_moment" else lowered',
     'test': 'tests.test_detect.DecisiveTitleTests.test_inert_title_never_decides',
     'assert': 'self.assertEqual(self.probe.detect_challenge(200, {}, body), ("none", ()))'},
    {'name': '56',
     'file': 'bench/providers/docker/probe.py',
     'old': '    if not snapshots or "closest" not in snapshots:\n'
            '        return None',
     'new': '    if payload.get("status") == 200:\n'
            '        return ("false-snapshot", "20260906171542")\n'
            '    if not snapshots or "closest" not in snapshots:\n'
            '        return None',
     'test': 'tests.test_entrances.EntranceProbeTests.test_empty_archive_at_http_200_is_not_a_snapshot',
     'assert': 'self.assertIsNone(got)'},
    {'name': '57',
     'file': 'bench/report/coverage.py',
     'old': '        if record.error_type != FailureReason.not_measured:',
     'new': '        if True:',
     'test': 'tests.test_entrances.EntranceCoverageTests.test_unmeasured_only_cell_is_excluded',
     'assert': 'self.assertEqual(rows[0].total_cells, 1)'},
    {'name': '58',
     'file': 'bench/runner/execute.py',
     'old': 'records.append(_record(item, provider, cell, env, None, '
            'FailureReason.not_measured))',
     'new': 'records.append(_record(item, provider, cell, env, None, '
            'FailureReason.provider_error))',
     'test': 'tests.test_entrances.EntranceExecutionTests.test_missing_rss_is_explicitly_unmeasured',
     'assert': 'self.assertEqual(records[0].error_type, '
               'FailureReason.not_measured)'},
    {'name': '59',
     'file': 'bench/runner/execute.py',
     'old': "            if item.cell.startswith('scenario:') or (provider.name != "
            "'wayback' and not entrance_url):",
     'new': '            if False:',
     'test': 'tests.test_entrances.EntranceExecutionTests.test_missing_rss_never_launches',
     'assert': 'self.assertEqual(launcher.calls, [])'},
    {'name': '60',
     'file': 'bench/runner/record.py',
     'old': '        entrance_age_hours=raw["entrance_age_hours"],',
     'new': '        entrance_age_hours=raw["entrance_age_hours"] or 0.0,',
     'test': 'tests.test_entrances.AgeRecordTests.test_unknown_age_roundtrip',
     'assert': 'self.assertIsNone(got.entrance_age_hours)'},
    {'name': '61',
     'file': 'bench/providers/docker/probe.py',
     'old': '        response["entrance_age_hours"] = _age_hours(published, '
            'self.now)',
     'new': '        response["entrance_age_hours"] = _age_hours(self.now, '
            'self.now)',
     'test': 'tests.test_entrances.EntranceProbeTests.test_wayback_fetches_snapshot_and_uses_timestamp_age',
     'assert': "self.assertAlmostEqual(result['entrance_age_hours'], 8 + 44 / 60 + "
               '18 / 3600)'},
    {'name': '62',
     'file': 'bench/providers/docker/probe.py',
     'old': '_age_hours(max(dates), self.now) if dates else None',
     'new': '_age_hours(min(dates), self.now) if dates else None',
     'test': 'tests.test_entrances.EntranceProbeTests.test_rss_raw_xml_sentinel_and_latest_pubdate',
     'assert': "self.assertEqual(result['entrance_age_hours'], 1.0)"},
    {'name': '63',
     'file': 'bench/providers/docker/probe.py',
     'old': '_age_hours(max(dates), self.now) if dates else None',
     'new': '_age_hours(max(dates), self.now) if dates else 0.0',
     'test': 'tests.test_entrances.EntranceProbeTests.test_rss_without_pubdate_has_unknown_age',
     'assert': "self.assertIsNone(result['entrance_age_hours'])"},
    {'name': '64',
     'file': 'bench/runner/execute.py',
     'old': "        entrance_age_hours=payload.get('entrance_age_hours'),",
     'new': '        entrance_age_hours=None,',
     'test': 'tests.test_entrances.EntranceExecutionTests.test_configured_rss_uses_feed_url_and_preserves_age',
     'assert': 'self.assertEqual(records[0].entrance_age_hours, 3.9)'},
    {'name': '65',
     'file': 'bench/report/build.py',
     'old': '            not_measured = record.error_type == '
            'FailureReason.not_measured',
     'new': '            not_measured = False',
     'test': 'tests.test_entrances.EntranceReportTests.test_unmeasured_never_becomes_numeric_failure_or_metric',
     'assert': "self.assertIn('| rss | не измерено |', text)"},
    {'name': '66',
     'file': 'bench/report/build.py',
     'old': '                if record.entrance_age_hours is not None:',
     'new': '                if record.entrance_age_hours:',
     'test': 'tests.test_entrances.EntranceReportTests.test_median_age_excludes_unknown_and_includes_zero',
     'assert': "self.assertIn('| wayback | 2.00 |', text)"},
    {'name': '67',
     'file': 'bench/runner/execute.py',
     'old': '            url = entrance_url or url',
     'new': '            url = url',
     'test': 'tests.test_entrances.EntranceExecutionTests.test_configured_rss_uses_feed_url_and_preserves_age',
     'assert': 'self.assertEqual(launcher.calls[0][0][-4:], [FEED, SENTINEL, '
               "'--mode', 'cold'])"},
    {'name': '68',
     'file': 'bench/providers/docker/probe.py',
     'old': '    request = Request(url, headers={"User-Agent": ENTRANCE_USER_AGENT})\n'
            '    try:\n'
            '        response = urlopen(request, timeout=120)',
     'new': '    try:\n'
            '        response = urlopen(url, timeout=120)',
     'test': 'tests.test_entrances.EntranceProbeTests.test_entrance_requests_carry_a_browser_user_agent',
     'assert': 'self.assertEqual(agent, self.probe.ENTRANCE_USER_AGENT)'},
    {'name': '69',
     'file': 'bench/providers/docker/probe.py',
     'old': '            if published.tzinfo is not None:\n'
            '                dates.append(published)',
     'new': '            dates.append(published)',
     'test': 'tests.test_entrances.EntranceProbeTests.test_naive_pubdate_gives_no_age',
     'assert': "self.assertTrue(result['ok'])"},
    {'name': '70',
     'file': 'bench/providers/docker/probe.py',
     'old': 'not isinstance(closest.get(key), str) or not closest[key]',
     'new': 'not isinstance(closest.get(key), str)',
     'test': 'tests.test_entrances.EntranceProbeTests.test_empty_snapshot_fields_are_rejected',
     'assert': 'with self.assertRaises(ValueError):'},
    {'name': '71',
     'file': 'bench/providers/docker/probe.py',
     'old': '        if discovery["status"] >= 400:',
     'new': '        if discovery["status"] > 400:',
     'test': 'tests.test_entrances.EntranceProbeTests.test_status_400_is_a_measured_refusal',
     'assert': "self.assertEqual(result['status'], 400)"},
    {'name': '72',
     'file': 'bench/providers/docker/probe.py',
     'old': '    return max(0.0, (now - published).total_seconds() / 3600)',
     'new': '    return (now - published).total_seconds() / 3600',
     'test': 'tests.test_entrances.EntranceProbeTests.test_future_snapshot_age_is_clamped',
     'assert': 'self.assertEqual(self.probe._age_hours(NOW + timedelta(hours=5), NOW), 0.0)'},
    {'name': '73',
     'file': 'bench/egress.py',
     'old': '    if mode & 0o077:\n        raise PermissionError("credentials file is group- or world-accessible")\n',
     'new': '',
     'test': 'tests.test_egress.LoadProfilesTests.test_permissions_wider_than_0600_are_refused',
     'assert': 'with self.assertRaises((PermissionError, ValueError)) as ctx:'},
    {'name': '74',
     'file': 'bench/egress.py',
     'old': '    url = profiles.get(name)\n    if not url:\n        return None\n    return url',
     'new': '    url = profiles.get(name)\n    return url',
     'test': 'tests.test_egress.LoadProfilesTests.test_missing_profile_and_empty_url_are_none',
     'assert': 'self.assertIsNone(profile_url(profiles, "gold"))'},
    {'name': '75',
     'file': 'bench/providers/registry.py',
     'old': "        argv.extend(['--env', proxy_env])",
     'new': "        argv.extend(['--env', proxy_env + '='])",
     'test': 'tests.test_registry.RegistryTests.test_proxy_env_is_name_only_never_the_value',
     'assert': "self.assertEqual(argv[argv.index('--env') + 1], 'ABG_PROXY')"},
    {'name': '76',
     'file': 'bench/runner/execute.py',
     'old': '            _record(item, by_name(item.provider), cells[item.cell], env, None,\n'
            '                    FailureReason.not_measured)',
     'new': '            _record(item, by_name(item.provider), cells[item.cell], env, None,\n'
            '                    FailureReason.provider_error)',
     'test': 'tests.test_execute.ExecuteTests.test_missing_egress_profile_is_not_measured_and_does_not_launch',
     'assert': 'self.assertEqual(records[0].error_type, FailureReason.not_measured)'},
    {'name': '77',
     'file': 'bench/runner/execute.py',
     'old': '    if egress is not None and not proxy_url:\n',
     'new': '    if False and egress is not None and not proxy_url:\n',
     'test': 'tests.test_execute.ExecuteTests.test_missing_egress_profile_is_not_measured_and_does_not_launch',
     'assert': 'self.assertEqual(launcher.calls, [])'},
    {'name': '78',
     'file': 'bench/runner/execute.py',
     'old': '                if rc in (125, 126, 127):\n'
            '                    failure = FailureReason.environment_error',
     'new': '                if rc in (125, 126):\n'
            '                    failure = FailureReason.environment_error',
     'test': 'tests.test_execute.ExecuteTests.test_docker_environment_exit_codes_are_environment_error',
     'assert': 'self.assertEqual(records[0].error_type, expected)'},
    {'name': '79',
     'file': 'bench/escalate.py',
     'old': '    elif reason is FailureReason.environment_error:\n'
            '        step = Step.investigate\n',
     'new': '    elif reason is FailureReason.environment_error:\n'
            '        step = Step.give_up\n',
     'test': 'tests.test_escalate.NextStepTests.test_environment_error_is_investigate',
     'assert': 'self.assertIs('},
    {'name': '80',
     'file': 'bench/providers/docker/probe.py',
     'old': '    if parsed.password is not None:\n'
            '        settings["password"] = unquote(parsed.password)\n'
            '    return settings',
     'new': '    if parsed.password is not None:\n'
            '        settings["password"] = unquote(parsed.password)\n'
            '    return {"server": url}',
     'test': 'tests.test_probe.ProxyWiringTests.test_playwright_proxy_splits_userinfo',
     'assert': 'self.assertEqual(got, {'},
    {'name': '81',
     'file': 'bench/providers/docker/probe.py',
     'old': '        if proxy:\n'
            '            env = os.environ.copy()\n'
            '            env["ALL_PROXY"] = proxy\n'
            '            run_kwargs["env"] = env\n',
     'new': '        if proxy:\n'
            '            env = os.environ.copy()\n'
            '            env["ALL_PROXY"] = proxy\n'
            '            run_kwargs["env"] = env\n'
            '            command.extend(["--proxy", proxy])\n',
     'test': 'tests.test_probe.AdapterContractTests.test_adapters_honor_abg_proxy_and_direct_when_unset',
     'assert': 'self.assertNotIn("--proxy", command)'},
    {'name': '82',
     'file': 'bench/providers/docker/probe.py',
     'old': '    return _USERINFO_URL.sub(r"\\1***@", text)',
     'new': '    return text',
     'test': 'tests.test_probe.ProxyWiringTests.test_redact_strips_userinfo_and_leaves_plain_text',
     'assert': 'self.assertNotIn("pass", text)'},
    {'name': '83',
     'file': 'bench/runner/record.py',
     'old': '        if item.name not in raw and item.default is MISSING',
     'new': '        if item.name not in raw',
     'test': 'tests.test_record.RecordTests.test_missing_optional_fields_take_defaults',
     'assert': 'self.assertTrue(loaded)'},
    {'name': '84',
     'file': 'bench/runner/execute.py',
     'old': '                _record(item, by_name(item.provider), cells[item.cell], env, None,\n'
            '                        FailureReason.environment_error)',
     'new': '                _record(item, by_name(item.provider), cells[item.cell], env, None,\n'
            '                        FailureReason.not_measured)',
     'test': 'tests.test_execute.EgressTests.test_wide_permission_skip_is_environment_error',
     'assert': 'self.assertEqual(records[0].error_type, FailureReason.environment_error)'},
    {'name': '85',
     'file': 'bench/egress.py',
     'old': '    if mode & 0o077:',
     'new': '    if mode != 0o600:',
     'test': 'tests.test_egress.LoadProfilesTests.test_owner_read_only_0400_is_accepted',
     'assert': 'self.assertEqual(load_profiles(path)["gold"], PROXY_URL)'},
    {'name': '86',
     'file': 'bench/providers/docker/probe.py',
     'old': '            launch_options["proxy"] = playwright_proxy(proxy)',
     'new': '            if self.package == "playwright":\n'
            '                launch_options["proxy"] = playwright_proxy(proxy)',
     'test': 'tests.test_probe.ProxyWiringTests.test_both_playwright_packages_get_proxy',
     'assert': 'self.assertEqual(launched["patchright"]["proxy"], expected)'},
    {'name': '87',
     'file': 'bench/runner/execute.py',
     'old': "            if had_proxy:\n"
            "                os.environ['ABG_PROXY'] = previous_proxy\n"
            "            else:\n"
            "                os.environ.pop('ABG_PROXY', None)",
     'new': "            os.environ.pop('ABG_PROXY', None)",
     'test': 'tests.test_execute.EgressTests.test_existing_proxy_env_is_restored',
     'assert': "self.assertEqual(os.environ.get('ABG_PROXY'), 'keep-me')"},
    {'name': '88',
     'file': 'bench/runner/execute.py',
     'old': '                if rc in (125, 126, 127):',
     'new': '                if rc >= 125:',
     'test': 'tests.test_execute.EgressTests.test_killed_container_is_not_environment_error',
     'assert': 'self.assertEqual(records[0].error_type, FailureReason.provider_error)'},
    {'name': '89',
     'file': 'bench/egress.py',
     'old': '        url = body.get("url", "")',
     'new': '        url = body["url"]',
     'test': 'tests.test_probe.ProxyWiringTests.test_result_without_url_key',
     'assert': 'self.assertTrue(loaded)'},
    {'name': '90',
     'file': 'bench/providers/docker/probe.py',
     'old': 'r"([a-z][a-z0-9+.\\-]*://)([^/@\\s\'\\"]+)@"',
     'new': 'r"(https?://)([^/@\\s\'\\"]+)@"',
     'test': 'tests.test_probe.ProxyWiringTests.test_redact_covers_any_proxy_scheme',
     'assert': 'self.assertNotIn("pass", cleaned)'},
    {'name': '91',
     'file': 'bench/providers/docker/probe.py',
     'old': '    if ":" in host:\n        host = f"[{host}]"\n',
     'new': '',
     'test': 'tests.test_probe.ProxyWiringTests.test_playwright_proxy_keeps_ipv6_brackets',
     'assert': 'self.assertEqual(settings["server"], "http://[fd00::1]:8080")'},
    {'name': '92',
     'file': 'bench/report/select.py',
     'old': '    return sorted(names, key=key)',
     'new': '    return [provider.name for provider in PROVIDERS if provider.name in names]',
     'test': 'tests.test_select.CanonicalOrderTests.test_order_comes_from_tier_cpu_name_not_registry_rows',
     'assert': 'self.assertEqual(canonical_order(records), ["rss", "wayback", "curl"])'},
    {'name': '93',
     'file': 'bench/report/select.py',
     'old': '    for provider in order:',
     'new': '    for provider in dict.fromkeys(record.provider for record in records):',
     'test': 'tests.test_select.OrderIndependenceTests.test_equivalent_coverage_keeps_cheaper_regardless_of_record_order',
     'assert': 'self.assertEqual(forward, backward)'},
    {'name': '94',
     'file': 'bench/report/select.py',
     'old': '    if not records:\n        return {}',
     'new': '    if not records:\n        return {provider.name: (True, "vacuous") for provider in PROVIDERS}',
     'test': 'tests.test_select.EmptySetTests.test_empty_records_are_empty_results',
     'assert': 'self.assertEqual(keep_set([]), {})'},
    {'name': '95',
     'file': 'bench/report/render.py',
     'old': '            keep, reason = pair[0], pair[1]',
     'new': '            keep, reason = keep_cov, reason_cov',
     'test': 'tests.test_select.ReportSelectionTests.test_report_keeps_rss_and_drops_curl',
     'assert': 'self.assertNotIn("исключить", rows[0])'},
    {'name': '96',
     'file': 'bench/report/select.py',
     'old': '    if age_kept is None or age_candidate is None:\n        return False',
     'new': '    if age_kept is None or age_candidate is None:\n        return True',
     'test': 'tests.test_select.AgeSemanticsTests.test_unknown_age_does_not_cover_known',
     'assert': 'self.assertTrue(decisions["wayback"][0], decisions["wayback"])'},
    {'name': '97',
     'file': 'bench/report/select.py',
     'old': '            if held and any(_comparable(other, age, age_tolerance_hours) for other in held for age in ages):',
     'new': '            if held:',
     'test': 'tests.test_select.RegressionTests.test_fresh_provider_kept_when_stale_is_cheaper',
     'assert': 'self.assertTrue(decisions["rss"][0], decisions["rss"])'},
    {'name': '98',
     'file': 'bench/report/select.py',
     'old': '        if not record.success:\n            continue',
     'new': '        if False:\n            continue',
     'test': 'tests.test_select.NotMeasuredTests.test_only_not_measured_is_not_kept',
     'assert': 'self.assertFalse(decisions["rss"][0], decisions["rss"])'},
    {'name': '99',
     'file': 'bench/report/select.py',
     'old': '    return age_kept <= age_candidate + tolerance',
     'new': '    return age_kept >= age_candidate - tolerance',
     'test': 'tests.test_select.RegressionTests.test_fresh_provider_kept_when_stale_is_cheaper',
     'assert': 'self.assertTrue(decisions["rss"][0], decisions["rss"])'},
    {'name': '100',
     'file': 'bench/report/select.py',
     'old': '        return (tier_by.get(name, float("inf")), cpu, name)',
     'new': '        return (tier_by.get(name, float("inf")), cpu)',
     'test': 'tests.test_select.CanonicalOrderTests.test_name_breaks_tier_and_cpu_tie',
     'assert': 'self.assertEqual(canonical_order(records), ["curl", "wayback"])'},
    {'name': '101',
     'file': 'bench/report/select.py',
     'old': '        for cell in sorted(cells):',
     'new': '        for cell in cells:',
     'test': 'tests.test_select.OrderIndependenceTests.test_two_useful_cells_keep_reason_byte_identical',
     'assert': 'self.assertEqual(forward, backward)'},
    {'name': '102',
     'file': 'bench/report/select.py',
     'old': '                kept_ages[cell].extend(ages)',
     'new': '                kept_ages[cell].extend(age for age in ages if age is not None)',
     'test': 'tests.test_select.AgeSemanticsTests.test_repeat_unknown_and_known_still_cover_unknown',
     'assert': 'self.assertFalse(decisions["rss"][0], decisions["rss"])'},
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
