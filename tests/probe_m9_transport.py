"""Independent probe for M9 transport contract."""

from __future__ import annotations

import importlib
import json
import math
import os
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from bench.escalate import Step
from bench.models import FailureReason, FetchResult
from bench.runner.execute import DockerLauncher, execute_plan
from bench.runner.matrix import PlanItem
from bench.runner.record import to_jsonl_line
try:
    from bench.runner.execute import fetch_page as _fetch_page
except Exception as exc:  # pragma: no cover
    _fetch_page = None
    _FETCH_PAGE_IMPORT_ERROR = exc
else:
    _FETCH_PAGE_IMPORT_ERROR = None
fetch_page = _fetch_page
from gateway.engine import run as gateway_run
from gateway.models import GatewayRequest, PlanStep

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "bench" / "providers" / "docker" / "probe.py"


def _load_probe():
    # Preserve package context so a documented sibling content helper can use
    # relative imports; no dependence on the implementation's private layout.
    return importlib.import_module("bench.providers.docker.probe")


def _body_bytes(body) -> int:
    if isinstance(body, bytes):
        return len(body)
    if isinstance(body, str):
        return len(body.encode("utf-8"))
    return 0


def _probe_payload(**changes):
    html = changes.pop("html", "<html><body>probe-ok</body></html>")
    text = changes.pop("text", "probe-ok")
    value = dict(
        ok=True,
        status=200,
        final_url="https://final.invalid/",
        bytes=_body_bytes(html),
        sentinel=True,
        challenge="none",
        title="",
        startup_ms=0,
        elapsed_ms=1,
        peak_rss_mb=0.1,
        cpu_ms=0,
        err=None,
        provider_version="probe-test",
        redirects=0,
        headers={},
        entrance_age_hours=None,
        html=html,
        text=text,
        challenge_markers=[],
    )
    value.update(changes)
    return value


def _extract_mount(argv: str) -> dict[str, object]:
    result = {"source": None, "target": None, "readonly": False}
    if "type=bind" in argv.split(","):
        fields = dict(chunk.split("=", 1) for chunk in argv.split(",") if "=" in chunk)
        if fields.get("type") != "bind":
            return result
        result["source"] = fields.get("source") or fields.get("src")
        result["target"] = fields.get("target") or fields.get("dst") or fields.get("destination")
        result["readonly"] = any(
            part in {"readonly", "ro", "readonly=true", "readonly=1"}
            for part in argv.split(",")
        )
        return result
    if ":" in argv:
        items = argv.split(":")
        if len(items) >= 2:
            result["source"] = items[0]
            result["target"] = items[1]
            options = set(",".join(items[2:]).split(","))
            result["readonly"] = "ro" in options
    return result


def _mounts(argv: list[str]) -> list[dict[str, object]]:
    mounts = []
    for index, token in enumerate(argv):
        if token in {"-v", "--volume"} and index + 1 < len(argv):
            mounts.append(_extract_mount(argv[index + 1]))
        elif token == "--mount" and index + 1 < len(argv):
            mounts.append(_extract_mount(argv[index + 1]))
        elif token.startswith("--volume="):
            mounts.append(_extract_mount(token.split("=", 1)[1]))
        elif token.startswith("--mount="):
            mounts.append(_extract_mount(token.split("=", 1)[1]))
    return [mount for mount in mounts if mount and mount["source"]]


def _is_probe_mount(candidate: str | Path) -> bool:
    path = Path(candidate).resolve()
    if path.is_file():
        return path == PROBE_PATH
    if not path.is_dir():
        return False
    return path == PROBE_PATH.parent and (path / "probe.py").resolve() == PROBE_PATH


def _budget_argument(argv):
    values = []
    for index, token in enumerate(argv):
        if token == "--budget-ms" and index + 1 < len(argv):
            values.append(argv[index + 1])
        elif token.startswith("--budget-ms="):
            values.append(token.split("=", 1)[1])
    return values


def _capture_adapter(body):
    class Adapter:
        version = "probe-test"

        def __init__(self):
            self.events = []

        def start(self):
            self.events.append("start")

        def navigate(self, url: str):
            self.events.append(("navigate", url))
            return {
                "status": 200,
                "final_url": url + "#final",
                "body": body,
                "title": "Observed",
                "redirects": 0,
            }

        def close(self):
            self.events.append("close")

    return Adapter()


class ProbeLauncher:
    def __init__(self, *results):
        self.results = iter(results)
        self.calls = []

    def run(self, argv, timeout, *, env=None):
        self.calls.append((list(argv), timeout, None if env is None else dict(env)))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


try:
    from gateway.fetch import BenchFetcher
except Exception as exc:  # pragma: no cover
    BenchFetcher = None
    _FETCH_IMPORT_ERROR = exc
else:
    _FETCH_IMPORT_ERROR = None


def _require_fetch_api(testcase: unittest.TestCase):
    if _fetch_page is None or BenchFetcher is None:
        reasons = []
        if _fetch_page is None:
            reasons.append(f"bench.runner.execute: {_FETCH_PAGE_IMPORT_ERROR}")
        if BenchFetcher is None:
            reasons.append(f"gateway.fetch: {_FETCH_IMPORT_ERROR}")
        testcase.fail("gateway fetch API is unavailable: " + "; ".join(reasons))
    return _fetch_page


class ProbeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = _load_probe()

    def test_run_probe_content_controlled_by_include_content_flag(self):
        body = (
            "<html><body>sentinel-one ✨ marker-αβγ &copy; "
            "<script>script-only</script>"
            "<style>color:red</style>"
            "<template>template-only</template>"
            "tail-ω</body></html>"
        )
        result = self.probe.run_probe(
            "curl", "https://target.invalid/", "sentinel-one",
            mode="cold",
            adapter_factory=lambda _: _capture_adapter(body),
            clock=lambda: 100,
            metrics=lambda: (0, 0),
            include_content=False,
        )
        self.assertNotIn("html", result)
        self.assertNotIn("text", result)

        result = self.probe.run_probe(
            "curl", "https://target.invalid/", "sentinel-one",
            mode="cold",
            adapter_factory=lambda _: _capture_adapter(body),
            clock=lambda: 101,
            metrics=lambda: (0, 0),
            include_content=True,
        )
        self.assertEqual(result["html"], body)
        self.assertIn("sentinel-one", result["text"])
        self.assertIn("marker-αβγ", result["text"])
        self.assertIn("©", result["text"])
        self.assertIn("tail-ω", result["text"])
        self.assertNotIn("script-only", result["text"])
        self.assertNotIn("color:red", result["text"])
        self.assertNotIn("template-only", result["text"])
        self.assertNotIn("<", result["text"])
        legacy = self.probe.run_probe(
            "curl", "https://target.invalid/", "sentinel-one", mode="cold",
            adapter_factory=lambda _: _capture_adapter(body), metrics=lambda: (0, 0),
        )
        self.assertNotIn("html", legacy)
        self.assertNotIn("text", legacy)

    def test_run_probe_exception_has_empty_content_and_timeout_classification(self):
        class BrokenAdapter:
            def start(self):
                raise TimeoutError("oracle timeout")

            def close(self):
                pass

        result = self.probe.run_probe(
            "curl", "https://target.invalid/", "marker", mode="cold",
            adapter_factory=lambda _: BrokenAdapter(), metrics=lambda: (0, 0),
            include_content=True, budget_ms=125,
        )
        self.assertEqual(result["html"], "")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["err"], "timeout")
        self.assertFalse(result["ok"])

    def test_run_probe_warm_mode_navigates_to_blank_first(self):
        adapter = _capture_adapter("<html><body>marker</body></html>")
        self.probe.run_probe(
            "curl", "https://target.invalid/", "marker",
            mode="warm",
            adapter_factory=lambda _: adapter,
            clock=lambda: 120,
            metrics=lambda: (0, 0),
            include_content=True,
        )
        self.assertIn(("navigate", "about:blank"), adapter.events)
        self.assertIn(("navigate", "https://target.invalid/"), adapter.events)


class ProbeContractTests(unittest.TestCase):
    def test_legacy_execute_plan_accepts_bodyless_protocol_without_content_in_record(self):
        payload = _probe_payload()
        payload.pop("html")
        payload.pop("text")
        launcher = ProbeLauncher((0, json.dumps(payload), ""))
        records = execute_plan(
            [PlanItem("curl", "target:oracle", "cold", 0)],
            launcher=launcher,
            cells={"target:oracle": {"url": "https://example.invalid/", "sentinel": "probe-ok"}},
            env={},
        )
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success)
        wire = to_jsonl_line(records[0])
        self.assertNotIn("html", json.loads(wire))
        self.assertNotIn("text", json.loads(wire))
        self.assertNotIn("--include-content", launcher.calls[0][0])


class FetchPageTests(unittest.TestCase):
    def setUp(self):
        _require_fetch_api(self)

    def test_fetch_page_returns_real_html_text_and_urls(self):
        payload = _probe_payload(
            status=200,
            final_url="https://final.invalid/page",
            html="<html><body>unicode ✨ &copy; marker</body></html>",
            text="unicode ✨ © marker",
            elapsed_ms=73, startup_ms=12, cpu_ms=7, peak_rss_mb=4.25,
            redirects=2, challenge="suspected",
        )
        launcher = ProbeLauncher((0, json.dumps(payload), ""))
        result, age_hours = fetch_page(
            "curl",
            url="https://example.invalid/page",
            sentinel="marker",
            budget_ms=1000,
            launcher=launcher,
        )
        self.assertIsInstance(result, FetchResult)
        self.assertIsNone(age_hours)
        self.assertEqual(result.error_type, FailureReason.none)
        self.assertEqual(result.html, payload["html"])
        self.assertEqual(result.text, payload["text"])
        self.assertEqual(result.requested_url, "https://example.invalid/page")
        self.assertEqual(result.final_url, payload["final_url"])
        self.assertEqual(result.provider, "curl")
        self.assertEqual(result.provider_version, "probe-test")
        for field in ("elapsed_ms", "startup_ms", "cpu_ms", "peak_rss_mb", "redirects", "challenge", "status"):
            self.assertEqual(getattr(result, field), payload[field])
        self.assertEqual(result.bytes_received, payload["bytes"])
        self.assertEqual(len(launcher.calls), 1)

    def test_fetch_page_rejects_missing_or_non_string_content(self):
        cases = []
        payload = _probe_payload()
        payload = dict(payload)
        payload.pop("html")
        payload.pop("text")
        cases.append(payload)
        payload = _probe_payload(html=123, text=None)
        cases.append(payload)
        payload = _probe_payload(html="text", text=123)
        cases.append(payload)
        for key in ("html", "text"):
            payload = _probe_payload()
            del payload[key]
            cases.append(payload)
        for payload_case in cases:
            with self.subTest(payload=payload_case):
                launcher = ProbeLauncher((0, json.dumps(payload_case), ""))
                result, _ = fetch_page(
                    "curl",
                    url="https://example.invalid/page",
                    sentinel="marker",
                    budget_ms=500,
                    launcher=launcher,
                )
                self.assertEqual(result.error_type, FailureReason.provider_error)
                self.assertEqual(result.html, "")
                self.assertEqual(result.text, "")

    def test_fetch_page_rejects_invalid_metric_or_enum_payload(self):
        payloads = [
            _probe_payload(challenge="invalid"),
            _probe_payload(bytes=-1),
            _probe_payload(elapsed_ms=math.nan),
            _probe_payload(status=700),
            _probe_payload(sentinel=1),
            _probe_payload(ok="true"),
            _probe_payload(entrance_age_hours=-1),
            _probe_payload(cpu_ms=True),
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                launcher = ProbeLauncher((0, json.dumps(payload), ""))
                result, _ = fetch_page(
                    "curl",
                    url="https://example.invalid/page",
                    sentinel="marker",
                    budget_ms=500,
                    launcher=launcher,
                )
                self.assertEqual(result.error_type, FailureReason.provider_error)
                self.assertEqual(result.html, "")
                self.assertEqual(result.text, "")

    def test_fetch_page_classifies_exit_codes_and_timeout(self):
        payload = _probe_payload()
        for rc, expected in (
            (125, FailureReason.environment_error),
            (126, FailureReason.environment_error),
            (127, FailureReason.environment_error),
            (1, FailureReason.provider_error),
        ):
            launcher = ProbeLauncher((rc, json.dumps(payload), ""))
            result, _ = fetch_page(
                "curl",
                url="https://example.invalid/page",
                sentinel="marker",
                budget_ms=100,
                launcher=launcher,
            )
            self.assertEqual(result.error_type, expected, msg=f"rc={rc}")
            self.assertEqual((result.html, result.text), ("", ""))
            self.assertEqual(len(launcher.calls), 1)
        timeout_launcher = ProbeLauncher(subprocess.TimeoutExpired("docker", 1))
        timed_out, _ = fetch_page(
            "curl",
            url="https://example.invalid/page",
            sentinel="marker",
            budget_ms=100,
            launcher=timeout_launcher,
        )
        self.assertEqual(timed_out.error_type, FailureReason.timeout)
        self.assertEqual((timed_out.html, timed_out.text), ("", ""))

    def test_fetch_page_honors_probe_errors_and_rejects_malformed_json(self):
        cases = [
            (json.dumps(_probe_payload(err="timeout")), FailureReason.timeout),
            (json.dumps(_probe_payload(err="connection_error")), FailureReason.connection_error),
            (json.dumps(_probe_payload(err="oracle-unknown-error")), FailureReason.provider_error),
            ("not-json", FailureReason.provider_error),
            (json.dumps(_probe_payload()) + "\n{broken", FailureReason.provider_error),
        ]
        for stdout, expected in cases:
            with self.subTest(stdout=stdout):
                launcher = ProbeLauncher((0, stdout, "oracle-stderr"))
                result, _ = fetch_page("curl", url="https://example.invalid/",
                                      sentinel="probe-ok", budget_ms=125, launcher=launcher)
                self.assertEqual(result.error_type, expected)
                self.assertEqual((result.html, result.text), ("", ""))
                self.assertNotIn("oracle-stderr", repr(result))
                self.assertNotIn("oracle-unknown-error", repr(result))
        launcher = ProbeLauncher(TimeoutError("oracle-timeout"))
        result, _ = fetch_page("curl", url="https://example.invalid/",
                              sentinel="probe-ok", budget_ms=125, launcher=launcher)
        self.assertEqual(result.error_type, FailureReason.timeout)

    def test_fetch_page_rejects_invalid_budget_before_launch(self):
        payload = _probe_payload()
        for budget in (0, -1, True, 12.5):
            with self.subTest(budget=budget):
                launcher = ProbeLauncher((0, json.dumps(payload), ""))
                with self.assertRaises(ValueError):
                    fetch_page(
                        "curl",
                        url="https://example.invalid/page",
                        sentinel="marker",
                        budget_ms=budget,
                        launcher=launcher,
                    )
                self.assertEqual(launcher.calls, [])

    def test_fetch_page_rejects_invalid_request_inputs(self):
        payload = _probe_payload()
        checks = [
            ("provider", "missing-provider", "https://example.invalid/page"),
            ("url", "curl", "bad-url"),
            ("url-userinfo", "curl", "https://user:pass@example.invalid/"),
            ("url-scheme", "curl", "ftp://example.invalid/"),
        ]
        for label, provider, url in checks:
            with self.subTest(label=label):
                launcher = ProbeLauncher((0, json.dumps(payload), ""))
                with self.assertRaises(ValueError) as raised:
                    fetch_page(
                        provider,
                        url=url,
                        sentinel="marker",
                        budget_ms=100,
                        launcher=launcher,
                    )
                self.assertEqual(launcher.calls, [])
                self.assertNotIn(url, str(raised.exception))
                self.assertNotIn("user:pass", str(raised.exception))
        launcher = ProbeLauncher()
        with self.assertRaises(ValueError):
            fetch_page("curl", url="https://example.invalid/", sentinel="",
                       budget_ms=100, launcher=launcher)
        self.assertEqual(launcher.calls, [])

    def test_fetch_page_subsecond_budget_roundtrip_and_budget_argument(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
        fetch_page(
            "curl",
            url="https://example.invalid/page",
            sentinel="marker",
            budget_ms=125,
            launcher=launcher,
        )
        argv, timeout, _ = launcher.calls[0]
        self.assertAlmostEqual(timeout, 0.125, places=12)
        budget_values = _budget_argument(argv)
        self.assertEqual(len(launcher.calls), 1)
        self.assertEqual(len(budget_values), 1)
        self.assertGreater(int(budget_values[0]), 0)
        self.assertLessEqual(int(budget_values[0]), 125)
        self.assertIn("--include-content", argv)
        mode = argv[argv.index("--mode") + 1] if "--mode" in argv else "cold"
        self.assertEqual(mode, "cold")

    def test_fetch_page_probe_mount_is_cwd_independent_and_absolute(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload(html="ok", text="ok")), ""))
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as workdir:
            os.chdir(workdir)
            try:
                fetch_page(
                    "curl",
                    url="https://example.invalid/page",
                    sentinel="marker",
                    budget_ms=250,
                    launcher=launcher,
                )
            finally:
                os.chdir(cwd)
        mounts = _mounts(launcher.calls[0][0])
        probe_mounts = [mount for mount in mounts if _is_probe_mount(mount["source"])]
        self.assertEqual(len(probe_mounts), 1, f"expected one probe mount, got: {mounts}")
        mount = probe_mounts[0]
        source = str(mount["source"])
        target = str(mount["target"])
        self.assertTrue(os.path.isabs(source))
        self.assertTrue(mount["readonly"])
        if Path(source).resolve() == PROBE_PATH:
            self.assertEqual(target, "/opt/abg/probe.py")
        else:
            self.assertEqual(target.rstrip("/"), "/opt/abg")
            self.assertTrue(Path(source).is_dir())
            self.assertTrue((Path(source) / "probe.py").exists())


class DockerLauncherTests(unittest.TestCase):
    def test_dockerlauncher_forwards_subprocess_env_and_accepts_legacy_call(self):
        command = ["docker", "run", "abg-curl:m2", "https://example.invalid", "marker"]
        result = subprocess.CompletedProcess(command, 0, "", "")
        with patch("subprocess.run") as run:
            run.return_value = result
            launcher = DockerLauncher()
            env = {"ABG_PROXY": "http://proxy.invalid"}
            launcher.run(command, timeout=1, env=env)
            _, called_kwargs = run.call_args
            self.assertIn("env", called_kwargs)
            self.assertEqual(called_kwargs["env"], env)
        with patch("subprocess.run") as run:
            run.return_value = result
            launcher = DockerLauncher()
            launcher.run(command, 1)
            _, called_kwargs = run.call_args
            legacy_env = called_kwargs.get("env")
            if legacy_env is not None:
                self.assertEqual(legacy_env, dict(os.environ))


class BenchFetcherTests(unittest.TestCase):
    def setUp(self):
        _require_fetch_api(self)

    def test_rss_without_entrance_without_entrance_url_is_not_measured(self):
        launcher = ProbeLauncher()
        fetcher = BenchFetcher(
            url="https://example.invalid/rss",
            sentinel="M9_SENTINEL",
            entrances={},
            profiles={},
            launcher=launcher,
        )
        reply = fetcher(PlanStep("rss", "direct", "entrance"), 200)
        self.assertEqual(reply.result.error_type, FailureReason.not_measured)
        self.assertEqual(reply.result.requested_url, "https://example.invalid/rss")
        self.assertEqual(reply.result.final_url, "https://example.invalid/rss")
        self.assertIsNone(reply.age_hours)
        self.assertEqual(launcher.calls, [])

    def test_unknown_egress_profile_does_not_launch(self):
        launcher = ProbeLauncher()
        fetcher = BenchFetcher(
            url="https://example.invalid/page",
            sentinel="M9_SENTINEL",
            profiles={"gold": "http://proxy"},
            launcher=launcher,
        )
        reply = fetcher(PlanStep("curl", "silver", "egress"), 200)
        self.assertEqual(reply.result.error_type, FailureReason.not_measured)
        self.assertEqual(reply.result.requested_url, "https://example.invalid/page")
        self.assertEqual(reply.result.final_url, "https://example.invalid/page")
        self.assertIsNone(reply.age_hours)
        self.assertEqual(launcher.calls, [])

    def test_wayback_uses_request_url_and_passes_real_fields(self):
        payload = _probe_payload(
            html="<p>M9_SENTINEL archive-marker-ω</p>",
            text="M9_SENTINEL archive-marker-ω",
            final_url="https://web.archive.org/web/20260101120000/https://example.invalid/page",
            entrance_age_hours=1.25,
        )
        launcher = ProbeLauncher(
            (0, json.dumps(payload), ""),
        )
        fetcher = BenchFetcher(
            url="https://example.invalid/page",
            sentinel="M9_SENTINEL",
            entrances={},
            profiles={},
            launcher=launcher,
        )
        reply = fetcher(PlanStep("wayback", "direct", "entrance"), 200)
        self.assertEqual(reply.age_hours, 1.25)
        self.assertEqual(reply.result.requested_url, "https://example.invalid/page")
        self.assertEqual(
            reply.result.final_url,
            "https://web.archive.org/web/20260101120000/https://example.invalid/page",
        )
        self.assertEqual(reply.result.error_type, FailureReason.none)
        self.assertEqual(len(launcher.calls), 1)
        self.assertIn("https://example.invalid/page", launcher.calls[0][0])
        self.assertEqual(reply.result.html, payload["html"])
        self.assertEqual(reply.result.text, payload["text"])

    def test_instance_copies_profiles_and_entrances_and_keeps_requested_url(self):
        entrances = {"rss": "https://feed.invalid/original"}
        profiles = {"gold": "http://gold.invalid:8080"}
        payload = _probe_payload(entrance_age_hours=2.5)
        launcher = ProbeLauncher(*[(0, json.dumps(payload), "")] * 3)
        fetcher = BenchFetcher("https://example.invalid/page", "probe-ok",
                               entrances=entrances, profiles=profiles, launcher=launcher,
                               network="host")
        other = BenchFetcher("https://example.invalid/other", "probe-ok", launcher=launcher)
        entrances["rss"] = "https://feed.invalid/changed"
        profiles["gold"] = "http://changed.invalid:8080"
        reply = fetcher(PlanStep("rss", "gold", "entrance"), 200)
        argv, _, env = launcher.calls[0]
        self.assertIn("https://feed.invalid/original", argv)
        self.assertNotIn("https://feed.invalid/changed", argv)
        self.assertEqual((env or {}).get("ABG_PROXY"), "http://gold.invalid:8080")
        self.assertEqual(reply.result.requested_url, "https://example.invalid/page")
        self.assertEqual(reply.result.final_url, payload["final_url"])
        self.assertEqual(reply.age_hours, 2.5)
        self.assertTrue("--network=host" in argv or
                        ("--network" in argv and argv[argv.index("--network") + 1] == "host"))
        missing = other(PlanStep("curl", "gold", "egress"), 200)
        self.assertEqual(missing.result.error_type, FailureReason.not_measured)
        self.assertEqual(len(launcher.calls), 1)

    def test_fetch_page_missing_entrance_or_profile_does_not_launch(self):
        for provider, extra in (("rss", {}), ("curl", {"egress": ("gold", None)})):
            with self.subTest(provider=provider):
                launcher = ProbeLauncher()
                result, age = fetch_page(provider, url="https://example.invalid/",
                                         sentinel="probe-ok", budget_ms=125,
                                         launcher=launcher, **extra)
                self.assertEqual(result.error_type, FailureReason.not_measured)
                self.assertIsNone(age)
                self.assertEqual(launcher.calls, [])

    def test_gateway_run_treats_sentinel_match_403_as_failure(self):
        launcher = ProbeLauncher(
            (0, json.dumps(_probe_payload(
                ok=False,
                status=403,
                html="<html><body>M9_SENTINEL</body></html>",
                text="M9_SENTINEL",
            )), ""),
        )
        fetcher = BenchFetcher(
            url="https://example.invalid/page",
            sentinel="M9_SENTINEL",
            launcher=launcher,
        )
        out = gateway_run(
            GatewayRequest(
                url="https://example.invalid/page",
                sentinel="M9_SENTINEL",
                budget_ms=1000,
            ),
            fetcher,
        )
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.http_403)
        self.assertEqual(out.step, Step.change_egress)
        self.assertEqual(len(launcher.calls), 1)


class BenchFetcherConcurrencyTests(unittest.TestCase):
    def setUp(self):
        _require_fetch_api(self)

    def test_concurrent_calls_do_not_mutate_environ_and_do_not_expose_proxies_in_argv(self):
        profiles = {
            "gold": "http://user:pass@gold-proxy:8080",
            "silver": "http://user:pass@silver-proxy:8080",
        }
        results = (
            (0, json.dumps(_probe_payload()), ""),
            (0, json.dumps(_probe_payload()), ""),
            (0, json.dumps(_probe_payload()), ""),
        )
        lock = threading.Lock()
        barrier = threading.Barrier(3)
        observed_barrier = threading.Barrier(3)
        observed_environ = []
        observed_calls = {}
        observed_argv = {}
        thread_results = []
        thread_errors = []

        class BarrierLauncher(ProbeLauncher):
            def run(self, argv, timeout, *, env=None):
                try:
                    barrier.wait(timeout=1.0)
                except Exception as exc:
                    with lock:
                        thread_errors.append(exc)
                    raise
                with lock:
                    name = threading.current_thread().name
                    observed_environ.append(dict(os.environ))
                    observed_calls[name] = None if env is None else dict(env)
                    observed_argv[name] = list(argv)
                observed_barrier.wait(timeout=2)
                return super().run(argv, timeout, env=env)

        launcher = BarrierLauncher(*results)
        fetcher = BenchFetcher(
            url="https://example.invalid/page",
            sentinel="M9_SENTINEL",
            profiles=profiles,
            launcher=launcher,
        )

        previous = os.environ.get("ABG_PROXY")
        os.environ["ABG_PROXY"] = "http://global.proxy:8080"
        expected_environ = dict(os.environ)
        try:
            def run_profile(profile):
                try:
                    thread_results.append((profile, fetcher(PlanStep("curl", profile, "egress"), 500).result.error_type))
                except Exception as exc:
                    thread_errors.append((profile, exc))

            def run_direct():
                try:
                    thread_results.append(("direct", fetcher(PlanStep("curl", "direct", "http"), 500).result.error_type))
                except Exception as exc:
                    thread_errors.append(("direct", exc))

            direct = threading.Thread(name="direct", target=run_direct, daemon=True)
            profile = threading.Thread(name="gold", target=run_profile, args=("gold",), daemon=True)
            silver = threading.Thread(name="silver", target=run_profile, args=("silver",), daemon=True)
            direct.start()
            profile.start()
            silver.start()
            direct.join(timeout=2)
            profile.join(timeout=2)
            silver.join(timeout=2)
            after_environ = dict(os.environ)
        finally:
            if previous is None:
                os.environ.pop("ABG_PROXY", None)
            else:
                os.environ["ABG_PROXY"] = previous

        self.assertFalse(thread_errors, thread_errors)
        self.assertFalse(direct.is_alive())
        self.assertFalse(profile.is_alive())
        self.assertFalse(silver.is_alive())
        self.assertEqual(len(launcher.calls), 3)
        self.assertCountEqual([item[1] for item in thread_results], [FailureReason.none] * 3)
        self.assertEqual(len(observed_environ), 3)
        for observed in observed_environ:
            self.assertEqual(observed, expected_environ)
        self.assertEqual(after_environ, expected_environ)
        self.assertEqual(set(observed_calls), {"direct", "gold", "silver"})
        self.assertNotIn("ABG_PROXY", observed_calls["direct"] or {})
        self.assertNotIn("ABG_PROXY", observed_argv["direct"])
        self.assertNotIn("--env=ABG_PROXY", observed_argv["direct"])
        for profile_name in profiles:
            self.assertEqual(
                (observed_calls[profile_name] or {}).get("ABG_PROXY"),
                profiles[profile_name],
            )
            argv = observed_argv[profile_name]
            self.assertTrue(
                "--env=ABG_PROXY" in argv or any(
                    token in {"--env", "-e"} and argv[index + 1:index + 2] == ["ABG_PROXY"]
                    for index, token in enumerate(argv)
                ), "profile must pass ABG_PROXY by name to Docker",
            )
        for call in launcher.calls:
            argv = call[0]
            self.assertFalse(any("user:pass@" in part for part in argv))
            self.assertFalse(any(part.startswith("ABG_PROXY=") for part in argv))
            self.assertFalse(any("ABG_PROXY=" in part for part in argv))


if __name__ == "__main__":
    unittest.main()
