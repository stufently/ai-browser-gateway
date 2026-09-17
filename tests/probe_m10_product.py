"""Independent probe for the M10 product-entry contract."""

from __future__ import annotations

import importlib
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from unittest.mock import patch

from bench.escalate import Step
from bench.models import ChallengeType, FailureReason, FetchResult
from bench.providers.registry import build_argv, by_name
from bench.runner.execute import fetch_page
from gateway.models import Attempt, GatewayOutcome, PlanStep, ProviderReply

try:
    from bench.runner.execute import fetch_content as _fetch_content
except Exception as exc:  # pragma: no cover
    _fetch_content = None
    _FETCH_CONTENT_IMPORT_ERROR = exc
else:
    _FETCH_CONTENT_IMPORT_ERROR = None
fetch_content = _fetch_content

try:
    from gateway.fetch import ProductFetcher as _ProductFetcher
except Exception as exc:  # pragma: no cover
    _ProductFetcher = None
    _PRODUCT_FETCHER_IMPORT_ERROR = exc
else:
    _PRODUCT_FETCHER_IMPORT_ERROR = None
ProductFetcher = _ProductFetcher

try:
    from gateway.product import ProductRequest as _ProductRequest
    from gateway.product import accept_page as _accept_page
    from gateway.product import plan_product as _plan_product
    from gateway.product import run_product as _run_product
except Exception as exc:  # pragma: no cover
    _ProductRequest = None
    _accept_page = None
    _plan_product = None
    _run_product = None
    _PRODUCT_IMPORT_ERROR = exc
else:
    _PRODUCT_IMPORT_ERROR = None
ProductRequest = _ProductRequest
accept_page = _accept_page
plan_product = _plan_product
run_product = _run_product

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "bench" / "providers" / "docker" / "probe.py"
URL = "https://example.invalid/page"
MARKER = "M10_UNIQUE_MARKER_ω"
VISIBLE = "visible page body"


def _load_probe():
    return importlib.import_module("bench.providers.docker.probe")


def _body_bytes(body) -> int:
    if isinstance(body, bytes):
        return len(body)
    if isinstance(body, str):
        return len(body.encode("utf-8"))
    return 0


def _probe_payload(**changes):
    html = changes.pop("html", f"<html><body>{VISIBLE}</body></html>")
    text = changes.pop("text", VISIBLE)
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


def _has_env_name(argv: list[str], name: str) -> bool:
    joined = argv
    if f"--env={name}" in joined or f"-e={name}" in joined:
        return True
    for index, token in enumerate(joined):
        if token in {"--env", "-e"} and joined[index + 1:index + 2] == [name]:
            return True
    return False


_PROBE_FLAG_ONLY = {"--content-only", "--include-content"}
_PROBE_FLAG_VALUE = {"--mode", "--budget-ms"}


def _probe_cli_positionals(argv: list[str]) -> list[str]:
    """Collect probe positionals after the image using the public CLI grammar."""
    image = by_name("curl").image
    if image not in argv:
        return []
    rest = argv[argv.index(image) + 1:]
    positionals = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in _PROBE_FLAG_ONLY or token.startswith("--content-only=") \
                or token.startswith("--include-content="):
            index += 1
            continue
        if token in _PROBE_FLAG_VALUE:
            index += 2
            continue
        if token.startswith("--mode=") or token.startswith("--budget-ms="):
            index += 1
            continue
        if token.startswith("-") and token != "-":
            index += 1
            continue
        positionals.append(token)
        index += 1
    return positionals


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


def _result(provider="curl", *, status=200, html=None, text=None,
            reason=FailureReason.none, challenge=ChallengeType.none,
            elapsed_ms=7, url=URL):
    if html is None:
        html = f"<html><body>{VISIBLE}</body></html>"
    if text is None:
        text = VISIBLE
    return FetchResult(
        provider=provider, provider_version="probe", requested_url=url,
        final_url=url + "/final", status=status, html=html, text=text,
        elapsed_ms=elapsed_ms, startup_ms=0, cpu_ms=0, peak_rss_mb=0.0,
        bytes_received=len(html.encode() if isinstance(html, str) else b""),
        redirects=0, error_type=reason, challenge=challenge,
    )


def _reply(provider="curl_cffi", *, age=None, **kwargs):
    return ProviderReply(_result(provider, **kwargs), age_hours=age)


class ScriptedFetcher:
    def __init__(self, *replies, costs=None):
        self.replies = replies
        self.costs = list(costs) if costs is not None else [10] * max(len(replies), 1)
        self.calls = []
        self.now = 1000

    def clock(self):
        return self.now

    def __call__(self, step, budget_ms):
        index = len(self.calls)
        self.calls.append((step, budget_ms))
        if index >= len(self.replies):
            raise AssertionError(
                f"unexpected fetch: {step.provider}/{step.egress_profile}/{step.purpose}"
            )
        self.now += self.costs[index] if index < len(self.costs) else 10
        return self.replies[index]

    @property
    def routes(self):
        return [(step.provider, step.egress_profile, step.purpose) for step, _ in self.calls]


def _missing_api_reasons() -> list[str]:
    reasons = []
    if _fetch_content is None:
        reasons.append(f"bench.runner.execute.fetch_content: {_FETCH_CONTENT_IMPORT_ERROR}")
    if _ProductFetcher is None:
        reasons.append(f"gateway.fetch.ProductFetcher: {_PRODUCT_FETCHER_IMPORT_ERROR}")
    if None in (_ProductRequest, _accept_page, _plan_product, _run_product):
        reasons.append(f"gateway.product: {_PRODUCT_IMPORT_ERROR}")
    try:
        build_argv(by_name("curl"), url=URL, sentinel="", content_only=True)
    except TypeError as exc:
        reasons.append(f"registry.build_argv content_only: {exc}")
    probe = _load_probe()
    try:
        probe.run_probe(
            "curl", URL, "", mode="cold",
            adapter_factory=lambda _: _capture_adapter("<p>x</p>"),
            metrics=lambda: (0, 0), content_only=True,
        )
    except TypeError as exc:
        reasons.append(f"probe.run_probe content_only: {exc}")
    return reasons


def _require_product_api(testcase: unittest.TestCase):
    reasons = _missing_api_reasons()
    if reasons:
        testcase.fail("M10 product API is unavailable: " + "; ".join(reasons))
    return fetch_content


def _run(request, fetcher, **kwargs):
    clock = kwargs.pop("clock", fetcher.clock)
    return run_product(request, fetcher, clock=clock, **kwargs)


def _request(**kwargs):
    options = dict(url=URL, budget_ms=1_000)
    options.update(kwargs)
    return ProductRequest(**options)


class ProductApiTests(unittest.TestCase):
    def test_new_public_api_is_present(self):
        _require_product_api(self)
        self.assertTrue(callable(fetch_content))
        self.assertTrue(callable(ProductFetcher))
        self.assertTrue(callable(accept_page))
        self.assertTrue(callable(plan_product))
        self.assertTrue(callable(run_product))
        self.assertTrue(callable(ProductRequest))


class FetchContentTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def test_fetch_content_returns_real_html_text_and_metrics(self):
        html = "<html><body>unicode ✨ unique-content-ω</body></html>"
        payload = _probe_payload(
            html=html, text="unicode ✨ unique-content-ω",
            final_url="https://final.invalid/page", elapsed_ms=73,
            startup_ms=12, cpu_ms=7, peak_rss_mb=4.25, redirects=2,
            challenge="suspected", sentinel=False, ok=True,
        )
        launcher = ProbeLauncher((0, json.dumps(payload), ""))
        result, age = fetch_content(
            "curl", url="https://example.invalid/page", budget_ms=1000, launcher=launcher,
        )
        self.assertIsInstance(result, FetchResult)
        self.assertIsNone(age)
        self.assertEqual(result.error_type, FailureReason.none)
        self.assertEqual(result.html, html)
        self.assertEqual(result.text, payload["text"])
        self.assertEqual(result.requested_url, "https://example.invalid/page")
        self.assertEqual(result.final_url, payload["final_url"])
        self.assertEqual(result.provider, "curl")
        self.assertEqual(result.provider_version, "probe-test")
        self.assertEqual(result.elapsed_ms, 73)
        self.assertEqual(result.bytes_received, payload["bytes"])
        self.assertEqual(len(launcher.calls), 1)

    def test_sentinel_found_true_does_not_replace_missing_body(self):
        payload = _probe_payload(sentinel=True, ok=True)
        del payload["html"]
        del payload["text"]
        launcher = ProbeLauncher((0, json.dumps(payload), ""))
        result, age = fetch_content(
            "curl", url=URL, budget_ms=500, launcher=launcher,
        )
        self.assertEqual(result.error_type, FailureReason.provider_error)
        self.assertEqual((result.html, result.text), ("", ""))
        self.assertIsNone(age)

    def test_fetch_content_uses_content_only_without_fake_sentinel(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload(sentinel=False)), ""))
        fetch_content("curl", url=URL, budget_ms=125, launcher=launcher)
        argv, timeout, _env = launcher.calls[0]
        self.assertIn("--content-only", argv)
        self.assertAlmostEqual(timeout, 0.125, places=12)
        positionals = _probe_cli_positionals(argv)
        self.assertEqual(positionals, [URL])
        self.assertFalse(any(part == "" for part in argv))
        self.assertNotIn("CONTENT_ONLY", argv)
        self.assertNotIn("content-only-sentinel", argv)
        self.assertNotIn("fake-sentinel", argv)

    def test_content_only_cli_grammar_does_not_bind_flag_order(self):
        image = by_name("curl").image
        flag_before_url = ["docker", "run", image, "--content-only", URL, "--budget-ms", "125"]
        url_before_flag = ["docker", "run", image, URL, "--content-only", "--budget-ms", "125"]
        extra_after_flag = ["docker", "run", image, "--content-only", URL, "fake-sentinel"]
        self.assertEqual(_probe_cli_positionals(flag_before_url), [URL])
        self.assertEqual(_probe_cli_positionals(url_before_flag), [URL])
        self.assertEqual(_probe_cli_positionals(extra_after_flag), [URL, "fake-sentinel"])

    def test_legacy_fetch_page_still_rejects_none_and_empty(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
        with self.assertRaises(ValueError):
            fetch_page("curl", url=URL, sentinel=None, budget_ms=100, launcher=launcher)
        with self.assertRaises(ValueError):
            fetch_page("curl", url=URL, sentinel="", budget_ms=100, launcher=launcher)
        self.assertEqual(launcher.calls, [])

    def test_rss_without_entrance_does_not_launch(self):
        launcher = ProbeLauncher()
        result, age = fetch_content("rss", url=URL, budget_ms=200, launcher=launcher)
        self.assertEqual(result.error_type, FailureReason.not_measured)
        self.assertEqual(result.requested_url, URL)
        self.assertIsNone(age)
        self.assertEqual(launcher.calls, [])

    def test_unknown_named_profile_is_not_measured_and_not_direct(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
        result, age = fetch_content(
            "curl", url=URL, budget_ms=200, launcher=launcher, egress=("silver", None),
        )
        self.assertEqual(result.error_type, FailureReason.not_measured)
        self.assertIsNone(age)
        self.assertEqual(launcher.calls, [])

    def test_wayback_without_entrance_uses_requested_url(self):
        payload = _probe_payload(
            html="<p>archive-marker-ω</p>", text="archive-marker-ω",
            final_url="https://web.archive.org/web/20260101120000/" + URL,
            entrance_age_hours=1.25,
        )
        launcher = ProbeLauncher((0, json.dumps(payload), ""))
        result, age = fetch_content("wayback", url=URL, budget_ms=400, launcher=launcher)
        self.assertEqual(age, 1.25)
        self.assertEqual(result.requested_url, URL)
        self.assertEqual(result.final_url, payload["final_url"])
        self.assertEqual(result.html, payload["html"])
        self.assertEqual(len(launcher.calls), 1)
        self.assertIn(URL, launcher.calls[0][0])

    def test_invalid_url_types_and_values_do_not_launch_or_leak(self):
        secret = "https://user:pass@example.invalid/"
        cases = [
            123, True, 1.5, None, [], {}, b"https://example.invalid/",
            "", "ftp://example.invalid/", secret,
            "https://example.invalid/\x07", " https://example.invalid/",
            "https://example.invalid/ ", "https://",
            "https://example.invalid:abc/page",
            "https://example.invalid:70000/page",
            "https://example.invalid:0/page",
        ]
        for url in cases:
            with self.subTest(url=url):
                launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
                with self.assertRaises(ValueError) as raised:
                    fetch_content("curl", url=url, budget_ms=100, launcher=launcher)
                message = str(raised.exception)
                self.assertNotIn("user:pass", message)
                if isinstance(url, str) and url:
                    self.assertNotIn(url, message)
                self.assertEqual(launcher.calls, [])

    def test_invalid_port_is_rejected_before_io(self):
        for url in (
            "https://example.invalid:abc/page",
            "https://example.invalid:70000/page",
            "https://example.invalid:0/page",
        ):
            with self.subTest(url=url):
                launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
                with self.assertRaises(ValueError) as raised:
                    fetch_content("curl", url=url, budget_ms=100, launcher=launcher)
                self.assertNotIn(url, str(raised.exception))
                self.assertNotIn("70000", str(raised.exception))
                self.assertNotIn(":abc", str(raised.exception))
                self.assertEqual(launcher.calls, [])

    def test_budget_bounds_reject_bool_nonfinite_and_out_of_range(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
        for budget in (0, -1, True, False, 12.5, 180_001, 2**31):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    fetch_content("curl", url=URL, budget_ms=budget, launcher=launcher)
                self.assertEqual(launcher.calls, [])
        fetch_content("curl", url=URL, budget_ms=1, launcher=launcher)
        fetch_content(
            "curl", url=URL, budget_ms=180_000,
            launcher=ProbeLauncher((0, json.dumps(_probe_payload()), "")),
        )

    def test_unknown_provider_is_value_error_before_launch(self):
        launcher = ProbeLauncher()
        with self.assertRaises(ValueError) as raised:
            fetch_content("missing-provider", url=URL, budget_ms=100, launcher=launcher)
        self.assertEqual(launcher.calls, [])
        self.assertNotIn("missing-provider", str(raised.exception))

    def test_transport_failures_have_empty_body(self):
        payload = _probe_payload()
        for rc, expected in (
            (125, FailureReason.environment_error),
            (1, FailureReason.provider_error),
        ):
            launcher = ProbeLauncher((rc, json.dumps(payload), ""))
            result, _ = fetch_content("curl", url=URL, budget_ms=100, launcher=launcher)
            self.assertEqual(result.error_type, expected)
            self.assertEqual((result.html, result.text), ("", ""))
        timed = ProbeLauncher(subprocess.TimeoutExpired("docker", 1))
        result, _ = fetch_content("curl", url=URL, budget_ms=100, launcher=timed)
        self.assertEqual(result.error_type, FailureReason.timeout)
        self.assertEqual((result.html, result.text), ("", ""))

    def test_proxy_secret_stays_out_of_argv_and_process_env(self):
        secret = "http://user:s3cret-token@gold.invalid:8080"
        previous = os.environ.get("ABG_PROXY")
        os.environ["ABG_PROXY"] = "http://global.proxy:8080"
        expected_env = dict(os.environ)
        try:
            launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
            fetch_content(
                "curl", url=URL, budget_ms=200, launcher=launcher, egress=("gold", secret),
            )
            argv, _timeout, env = launcher.calls[0]
            self.assertFalse(any("s3cret-token" in part for part in argv))
            self.assertFalse(any("user:s3cret" in part for part in argv))
            self.assertTrue(_has_env_name(argv, "ABG_PROXY"))
            self.assertEqual((env or {}).get("ABG_PROXY"), secret)
            self.assertEqual(dict(os.environ), expected_env)
        finally:
            if previous is None:
                os.environ.pop("ABG_PROXY", None)
            else:
                os.environ["ABG_PROXY"] = previous


class ContentOnlyProbeTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)
        self.probe = _load_probe()

    def test_content_only_returns_real_body_and_false_sentinel(self):
        body = "<html><body>content-only-ω hello</body></html>"
        result = self.probe.run_probe(
            "curl", URL, "", mode="cold",
            adapter_factory=lambda _: _capture_adapter(body),
            metrics=lambda: (0, 0), content_only=True,
        )
        self.assertFalse(result["sentinel"])
        self.assertEqual(result["html"], body)
        self.assertIn("content-only-ω", result["text"])
        self.assertIn("hello", result["text"])

    def test_default_empty_sentinel_is_not_content_only_success(self):
        body = "<html><body>should-not-count</body></html>"
        try:
            result = self.probe.run_probe(
                "curl", URL, "", mode="cold",
                adapter_factory=lambda _: _capture_adapter(body),
                metrics=lambda: (0, 0), include_content=True,
            )
        except ValueError:
            return
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("err"))

    def test_cli_content_only_allows_missing_sentinel(self):
        seen = {}

        def fake_run_probe(*args, **kwargs):
            seen.update(kwargs)
            seen["args"] = args
            return {"ok": False, "err": "", "sentinel": False, "html": "<p>x</p>", "text": "x"}

        with patch.object(self.probe, "run_probe", side_effect=fake_run_probe), \
                patch.object(sys, "stdout"):
            try:
                rc = self.probe.main([URL, "--content-only"])
            except SystemExit as exc:
                self.fail(f"content-only CLI missing: {exc}")
        self.assertEqual(rc, 0)
        self.assertTrue(seen.get("content_only"))

    def test_cli_without_flag_still_requires_sentinel(self):
        with patch.object(sys, "stderr"), self.assertRaises(SystemExit):
            self.probe.main([URL])


class ProductFetcherTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def test_copies_maps_preserves_url_and_age(self):
        entrances = {"rss": "https://feed.invalid/original"}
        profiles = {"gold": "http://gold.invalid:8080"}
        payload = _probe_payload(entrance_age_hours=2.5)
        launcher = ProbeLauncher(*[(0, json.dumps(payload), "")] * 3)
        fetcher = ProductFetcher(
            URL, entrances=entrances, profiles=profiles, launcher=launcher, network="host",
        )
        other = ProductFetcher("https://example.invalid/other", launcher=launcher)
        entrances["rss"] = "https://feed.invalid/changed"
        profiles["gold"] = "http://changed.invalid:8080"
        reply = fetcher(PlanStep("rss", "gold", "entrance"), 200)
        argv, _, env = launcher.calls[0]
        self.assertIn("https://feed.invalid/original", argv)
        self.assertNotIn("https://feed.invalid/changed", argv)
        self.assertEqual((env or {}).get("ABG_PROXY"), "http://gold.invalid:8080")
        self.assertEqual(reply.result.requested_url, URL)
        self.assertEqual(reply.age_hours, 2.5)
        self.assertTrue(
            "--network=host" in argv
            or ("--network" in argv and argv[argv.index("--network") + 1] == "host")
        )
        missing = other(PlanStep("curl_cffi", "gold", "egress"), 200)
        self.assertEqual(missing.result.error_type, FailureReason.not_measured)
        self.assertEqual(len(launcher.calls), 1)

    def test_unknown_profile_does_not_become_direct(self):
        launcher = ProbeLauncher((0, json.dumps(_probe_payload()), ""))
        fetcher = ProductFetcher(URL, profiles={"gold": "http://gold.invalid"}, launcher=launcher)
        reply = fetcher(PlanStep("curl_cffi", "silver", "egress"), 200)
        self.assertEqual(reply.result.error_type, FailureReason.not_measured)
        self.assertEqual(launcher.calls, [])

    def test_rss_without_entrance_does_not_launch(self):
        launcher = ProbeLauncher()
        fetcher = ProductFetcher(URL, launcher=launcher)
        reply = fetcher(PlanStep("rss", "direct", "entrance"), 200)
        self.assertEqual(reply.result.error_type, FailureReason.not_measured)
        self.assertEqual(launcher.calls, [])

    def test_concurrent_calls_isolate_proxy_env(self):
        profiles = {
            "gold": "http://user:pass@gold-proxy:8080",
            "silver": "http://user:pass@silver-proxy:8080",
        }
        lock = threading.Lock()
        barrier = threading.Barrier(3)
        observed_barrier = threading.Barrier(3)
        observed_environ = []
        observed_calls = {}
        observed_argv = {}
        thread_errors = []
        thread_results = []

        class BarrierLauncher(ProbeLauncher):
            def run(self, argv, timeout, *, env=None):
                barrier.wait(timeout=2)
                with lock:
                    name = threading.current_thread().name
                    observed_environ.append(dict(os.environ))
                    observed_calls[name] = None if env is None else dict(env)
                    observed_argv[name] = list(argv)
                observed_barrier.wait(timeout=2)
                return super().run(argv, timeout, env=env)

        launcher = BarrierLauncher(*[(0, json.dumps(_probe_payload()), "")] * 3)
        fetcher = ProductFetcher(URL, profiles=profiles, launcher=launcher)
        previous = os.environ.get("ABG_PROXY")
        os.environ["ABG_PROXY"] = "http://global.proxy:8080"
        expected_environ = dict(os.environ)
        try:
            def run_named(name):
                try:
                    thread_results.append(
                        (name, fetcher(PlanStep("curl_cffi", name, "egress" if name != "direct" else "http"), 500)
                         .result.error_type)
                    )
                except Exception as exc:
                    thread_errors.append((name, exc))

            threads = [
                threading.Thread(name="direct", target=run_named, args=("direct",), daemon=True),
                threading.Thread(name="gold", target=run_named, args=("gold",), daemon=True),
                threading.Thread(name="silver", target=run_named, args=("silver",), daemon=True),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            after = dict(os.environ)
        finally:
            if previous is None:
                os.environ.pop("ABG_PROXY", None)
            else:
                os.environ["ABG_PROXY"] = previous
        self.assertFalse(thread_errors, thread_errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(launcher.calls), 3)
        for observed in observed_environ:
            self.assertEqual(observed, expected_environ)
        self.assertEqual(after, expected_environ)
        self.assertNotIn("ABG_PROXY", observed_calls["direct"] or {})
        self.assertFalse(_has_env_name(observed_argv["direct"], "ABG_PROXY"))
        for profile_name, secret in profiles.items():
            self.assertEqual((observed_calls[profile_name] or {}).get("ABG_PROXY"), secret)
            self.assertTrue(_has_env_name(observed_argv[profile_name], "ABG_PROXY"))
            self.assertFalse(any("user:pass@" in part for part in observed_argv[profile_name]))
        self.assertEqual(len(thread_results), 3)
        self.assertCountEqual(
            [item[0] for item in thread_results],
            ["direct", "gold", "silver"],
        )
        self.assertCountEqual(
            [item[1] for item in thread_results],
            [FailureReason.none] * 3,
        )


class AcceptPageTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def test_error_type_wins_over_status_and_text(self):
        result = _result(status=200, reason=FailureReason.timeout, html=MARKER, text=MARKER)
        ok, reason = accept_page(result, expected_text=MARKER)
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.timeout)

    def test_http_status_mapping(self):
        cases = (
            (403, FailureReason.http_403),
            (429, FailureReason.http_429),
            (500, FailureReason.http_5xx),
            (503, FailureReason.http_5xx),
            (404, FailureReason.content_mismatch),
            (400, FailureReason.content_mismatch),
            (302, FailureReason.content_mismatch),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                ok, reason = accept_page(_result(status=status, html=MARKER, text=MARKER))
                self.assertFalse(ok)
                self.assertEqual(reason, expected)

    def test_none_or_non_int_status_is_provider_error(self):
        for status in (None, "200", 200.0, True):
            with self.subTest(status=status):
                ok, reason = accept_page(_result(status=status, html=MARKER, text=MARKER))
                self.assertFalse(ok)
                self.assertEqual(reason, FailureReason.provider_error)

    def test_url_only_rejects_suspected_and_captcha(self):
        for challenge, expected in (
            (ChallengeType.suspected, FailureReason.challenge_suspected),
            (ChallengeType.captcha, FailureReason.interactive_challenge),
        ):
            with self.subTest(challenge=challenge):
                ok, reason = accept_page(_result(challenge=challenge, html=VISIBLE, text=VISIBLE))
                self.assertFalse(ok)
                self.assertEqual(reason, expected)

    def test_expected_text_confirms_none_suspected_captcha_in_html_or_text(self):
        html_only = _result(html=f"<html>{MARKER}</html>", text=VISIBLE, challenge=ChallengeType.captcha)
        text_only = _result(html="<html>other</html>", text=f"{VISIBLE} {MARKER}",
                            challenge=ChallengeType.suspected)
        both = _result(html=f"<p>{MARKER}</p>", text=MARKER, challenge=ChallengeType.none)
        for result in (html_only, text_only, both):
            with self.subTest(challenge=result.challenge):
                ok, reason = accept_page(result, expected_text=MARKER)
                self.assertTrue(ok)
                self.assertEqual(reason, FailureReason.none)

    def test_expected_text_does_not_override_interactive_or_http_or_error(self):
        cases = [
            _result(challenge=ChallengeType.interactive, html=MARKER, text=MARKER),
            _result(status=403, html=MARKER, text=MARKER),
            _result(status=429, html=MARKER, text=MARKER),
            _result(reason=FailureReason.dns_error, html=MARKER, text=MARKER),
            _result(challenge=ChallengeType.javascript_required, html=MARKER, text=MARKER),
        ]
        expected = [
            FailureReason.interactive_challenge,
            FailureReason.http_403,
            FailureReason.http_429,
            FailureReason.dns_error,
            FailureReason.javascript_required,
        ]
        for result, want in zip(cases, expected):
            with self.subTest(want=want):
                ok, reason = accept_page(result, expected_text=MARKER)
                self.assertFalse(ok)
                self.assertEqual(reason, want)

    def test_expected_text_mismatch_is_content_missing(self):
        ok, reason = accept_page(_result(html=VISIBLE, text=VISIBLE), expected_text=MARKER)
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_missing)

    def test_empty_text_is_content_missing_even_with_html_match(self):
        ok, reason = accept_page(
            _result(html=f"<html>{MARKER}</html>", text="   "), expected_text=MARKER,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_missing)
        ok, reason = accept_page(_result(html="<html>hello</html>", text=""))
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.content_missing)

    def test_url_only_does_not_infer_expected_text_from_url(self):
        body = f"example.invalid page {VISIBLE}"
        ok, reason = accept_page(
            _result(html=f"<html>{body}</html>", text=body, challenge=ChallengeType.captcha),
        )
        self.assertFalse(ok)
        self.assertEqual(reason, FailureReason.interactive_challenge)


class ProductValidationTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def _reject(self, **kwargs):
        fetcher = ScriptedFetcher(_reply())
        ticks = []

        def clock():
            ticks.append(fetcher.clock())
            return ticks[-1]

        with self.assertRaises(ValueError) as raised:
            try:
                request = _request(**kwargs)
            except ValueError:
                raise
            else:
                run_product(request, fetcher, clock=clock)
        self.assertEqual(ticks, [])
        self.assertEqual(fetcher.calls, [])
        return raised.exception

    def test_defaults_and_frozen_request(self):
        request = ProductRequest(URL)
        self.assertEqual(request.max_age_hours, 0.0)
        self.assertIs(request.allow_browser, True)
        self.assertEqual(request.egress_profiles, ())
        self.assertEqual(request.budget_ms, 30_000)
        self.assertIsNone(request.expected_text)
        self.assertTrue(is_dataclass(request))
        with self.assertRaises(FrozenInstanceError):
            request.url = "https://other.invalid/"

    def test_invalid_fields_fail_before_clock_or_fetch(self):
        self._reject(url=123)
        self._reject(url=True)
        self._reject(url=None)
        self._reject(url=[])
        self._reject(url={})
        self._reject(url="https://user:pass@example.invalid/")
        self._reject(budget_ms=True)
        self._reject(budget_ms=0)
        self._reject(budget_ms=180_001)
        self._reject(max_age_hours=True)
        self._reject(max_age_hours=math.nan)
        self._reject(max_age_hours=math.inf)
        self._reject(max_age_hours=-1)
        self._reject(allow_browser=1)
        self._reject(egress_profiles=("direct",))
        self._reject(egress_profiles=("",))
        self._reject(expected_text="")
        self._reject(expected_text="   ")
        self._reject(expected_text=123)
        self._reject(url="https://example.invalid:abc/page")
        self._reject(url="https://example.invalid:70000/page")
        self._reject(url="https://example.invalid:0/page")

    def test_static_messages_omit_input_values(self):
        secret = "https://user:pass@leak.invalid/hidden"
        exc = self._reject(url=secret)
        self.assertNotIn(secret, str(exc))
        self.assertNotIn("user:pass", str(exc))
        self.assertNotIn("leak.invalid", str(exc))
        other = self._reject(url=True)
        self.assertNotIn("True", str(other))
        leaked = self._reject(expected_text=["leaked-expected-text"])
        self.assertNotIn("leaked-expected-text", str(leaked))

    def test_direct_profile_name_is_rejected(self):
        self._reject(egress_profiles=("gold", "direct"))


class ProductPlanTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def test_default_menu_is_http_then_two_browsers(self):
        self.assertEqual(plan_product(_request(allow_browser=True)), (
            PlanStep("curl_cffi", "direct", "http"),
            PlanStep("patchright", "direct", "browser"),
            PlanStep("scrapling", "direct", "browser"),
        ))

    def test_entrances_then_http_browsers_then_egress(self):
        self.assertEqual(
            plan_product(_request(max_age_hours=1, egress_profiles=("gold", "silver"))),
            (
                PlanStep("rss", "direct", "entrance"),
                PlanStep("wayback", "direct", "entrance"),
                PlanStep("curl_cffi", "direct", "http"),
                PlanStep("patchright", "direct", "browser"),
                PlanStep("scrapling", "direct", "browser"),
                PlanStep("curl_cffi", "gold", "egress"),
                PlanStep("curl_cffi", "silver", "egress"),
            ),
        )

    def test_allow_browser_false_keeps_egress_without_inventing_browsers(self):
        self.assertEqual(
            plan_product(_request(allow_browser=False, egress_profiles=("gold",))),
            (
                PlanStep("curl_cffi", "direct", "http"),
                PlanStep("curl_cffi", "gold", "egress"),
            ),
        )


class ProductRunTests(unittest.TestCase):
    def setUp(self):
        _require_product_api(self)

    def test_direct_http_success_keeps_payload_and_trace(self):
        fetcher = ScriptedFetcher(_reply(html=f"<p>{VISIBLE}</p>", text=VISIBLE))
        out = _run(_request(), fetcher)
        self.assertTrue(out.ok)
        self.assertIsInstance(out, GatewayOutcome)
        self.assertEqual(fetcher.routes, [("curl_cffi", "direct", "http")])
        self.assertEqual(out.url, URL)
        self.assertEqual(out.final_url, URL + "/final")
        self.assertEqual(out.html, f"<p>{VISIBLE}</p>")
        self.assertEqual(out.text, VISIBLE)
        self.assertEqual(out.provider, "curl_cffi")
        self.assertEqual(out.error_type, FailureReason.none)
        self.assertEqual(out.step, Step.stop)
        self.assertEqual(out.attempts[0].next_step, Step.stop)
        self.assertIsNone(out.age_hours)
        self.assertEqual(fetcher.calls[0][1], 1_000)

    def test_http_403_walks_patchright_then_scrapling_then_egress(self):
        fetcher = ScriptedFetcher(
            _reply(status=403, html="no", text="no"),
            _reply("patchright", status=403, html="no", text="no"),
            _reply("scrapling", status=403, html="no", text="no"),
            _reply("curl_cffi", html=f"<p>{VISIBLE}</p>", text=VISIBLE),
        )
        out = _run(_request(egress_profiles=("gold", "silver")), fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, "curl_cffi")
        self.assertEqual(fetcher.routes, [
            ("curl_cffi", "direct", "http"),
            ("patchright", "direct", "browser"),
            ("scrapling", "direct", "browser"),
            ("curl_cffi", "gold", "egress"),
        ])
        self.assertEqual(out.attempts[0].next_step, Step.browser)
        self.assertEqual(out.attempts[-1].next_step, Step.stop)

    def test_allow_browser_false_skips_browsers_to_egress(self):
        fetcher = ScriptedFetcher(
            _reply(status=403, html="no", text="no"),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
            _reply("curl_cffi"),
        )
        out = _run(_request(allow_browser=False, egress_profiles=("gold", "silver")), fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(fetcher.routes, [
            ("curl_cffi", "direct", "http"),
            ("curl_cffi", "gold", "egress"),
        ])
        self.assertNotIn("patchright", [route[0] for route in fetcher.routes])
        self.assertNotIn("scrapling", [route[0] for route in fetcher.routes])

    def test_stop_after_first_measured_changed_egress(self):
        fetcher = ScriptedFetcher(
            _reply(status=403, html="no", text="no"),
            _reply("patchright", status=403, html="no", text="no"),
            _reply("scrapling", status=403, html="no", text="no"),
            _reply("curl_cffi", status=403, html="no", text="no"),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(egress_profiles=("gold", "silver")), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.step, Step.human)
        self.assertEqual(out.error_type, FailureReason.http_403)
        self.assertEqual([route[1] for route in fetcher.routes if route[2] == "egress"], ["gold"])
        self.assertEqual((out.html, out.text), ("", ""))
        self.assertEqual(out.final_url, URL)

    def test_not_measured_profile_is_skipped_and_not_an_ip_change(self):
        fetcher = ScriptedFetcher(
            _reply(status=403, html="no", text="no"),
            _reply("curl_cffi", reason=FailureReason.not_measured, html="", text=""),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(allow_browser=False, egress_profiles=("missing", "gold")), fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(fetcher.routes, [
            ("curl_cffi", "direct", "http"),
            ("curl_cffi", "missing", "egress"),
            ("curl_cffi", "gold", "egress"),
        ])
        self.assertIsNone(out.attempts[1].next_step)
        self.assertEqual(out.attempts[1].error_type, FailureReason.not_measured)
        self.assertEqual(out.provider, "curl_cffi")

    def test_only_not_measured_profiles_end_human_not_measured(self):
        fetcher = ScriptedFetcher(
            _reply(status=403, html="no", text="no"),
            _reply("curl_cffi", reason=FailureReason.not_measured, html="", text=""),
        )
        out = _run(_request(allow_browser=False, egress_profiles=("missing",)), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.step, Step.human)
        self.assertEqual(out.error_type, FailureReason.not_measured)

    def test_fresh_entrance_accepted_stale_nan_inf_none_rejected(self):
        fetcher = ScriptedFetcher(_reply("rss", age=0.2, html=VISIBLE, text=VISIBLE))
        out = _run(_request(max_age_hours=1), fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(out.provider, "rss")
        self.assertEqual(out.age_hours, 0.2)
        self.assertEqual(out.step, Step.stop)
        self.assertIn(out.attempts[0].next_step, (None, Step.stop))
        self.assertEqual(len(out.attempts), 1)
        self.assertTrue(out.attempts[0].success)

        fetcher = ScriptedFetcher(
            _reply("rss", age=math.nan, html=VISIBLE, text=VISIBLE),
            _reply("wayback", age=math.inf, html=VISIBLE, text=VISIBLE),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(max_age_hours=1, allow_browser=False), fetcher)
        self.assertEqual(out.provider, "curl_cffi")
        self.assertEqual([attempt.error_type for attempt in out.attempts[:2]],
                         [FailureReason.content_mismatch, FailureReason.content_mismatch])
        self.assertEqual([attempt.next_step for attempt in out.attempts[:2]], [None, None])

        fetcher = ScriptedFetcher(
            _reply("rss", age=None, html=VISIBLE, text=VISIBLE),
            _reply("wayback", age=-0.1, html=VISIBLE, text=VISIBLE),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(max_age_hours=1, allow_browser=False), fetcher)
        self.assertEqual(out.provider, "curl_cffi")
        self.assertEqual(len(fetcher.routes), 3)

        fetcher = ScriptedFetcher(
            _reply("rss", age=1.01, html=VISIBLE, text=VISIBLE),
            _reply("wayback", age=1, html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(max_age_hours=1), fetcher)
        self.assertEqual(out.provider, "wayback")
        self.assertEqual(out.age_hours, 1)

    def test_remaining_budget_shrinks_and_late_success_is_timeout(self):
        fetcher = ScriptedFetcher(
            _reply(html="   ", text="   "),
            _reply("patchright", html=VISIBLE, text=VISIBLE),
            costs=[11, 13],
        )
        out = _run(_request(budget_ms=100), fetcher)
        self.assertEqual([budget for _, budget in fetcher.calls], [100, 89])
        self.assertTrue(out.ok)

        fetcher = ScriptedFetcher(_reply(html=VISIBLE, text=VISIBLE), costs=[101])
        out = _run(_request(budget_ms=100), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.timeout)
        self.assertEqual(out.step, Step.retry_later)
        self.assertFalse(out.attempts[0].success)
        self.assertEqual((out.html, out.text), ("", ""))
        self.assertEqual(out.final_url, URL)

    def test_budget_can_expire_before_first_fetch(self):
        now = [500]

        def clock():
            value = now[0]
            now[0] += 100
            return value

        fetcher = ScriptedFetcher(_reply())
        out = run_product(_request(budget_ms=100), fetcher, clock=clock)
        self.assertEqual(out.error_type, FailureReason.timeout)
        self.assertEqual(out.step, Step.retry_later)
        self.assertEqual(out.attempts, ())
        self.assertEqual(fetcher.calls, [])
        self.assertEqual(out.final_url, URL)
        self.assertGreaterEqual(now[0], 700)

    def test_http_429_skips_browsers_then_human_after_measured_change(self):
        fetcher = ScriptedFetcher(
            _reply(status=429, html="no", text="no"),
            _reply("curl_cffi", status=429, html="no", text="no"),
            _reply("curl_cffi", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(egress_profiles=("gold", "silver")), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.http_429)
        self.assertEqual(out.step, Step.human)
        self.assertEqual(fetcher.routes, [
            ("curl_cffi", "direct", "http"),
            ("curl_cffi", "gold", "egress"),
        ])

    def test_interactive_challenge_is_human_even_with_expected_text(self):
        fetcher = ScriptedFetcher(
            _reply(challenge=ChallengeType.interactive, html=MARKER, text=MARKER),
            _reply("patchright", html=MARKER, text=MARKER),
        )
        out = _run(_request(expected_text=MARKER, egress_profiles=("gold",)), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.interactive_challenge)
        self.assertEqual(out.step, Step.human)
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual((out.html, out.text), ("", ""))

    def test_expected_text_success_keeps_challenge_label_in_trace(self):
        fetcher = ScriptedFetcher(
            _reply(challenge=ChallengeType.captcha, html=f"<p>{MARKER}</p>", text=MARKER),
        )
        out = _run(_request(expected_text=MARKER), fetcher)
        self.assertTrue(out.ok)
        self.assertEqual(out.attempts[0].challenge, ChallengeType.captcha)
        self.assertEqual(out.attempts[0].error_type, FailureReason.none)
        self.assertEqual(out.html, f"<p>{MARKER}</p>")

    def test_content_mismatch_gives_up_without_further_fetch(self):
        fetcher = ScriptedFetcher(
            _reply(status=404, html="missing", text="missing"),
            _reply("patchright", html=VISIBLE, text=VISIBLE),
        )
        out = _run(_request(egress_profiles=("gold",)), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.content_mismatch)
        self.assertEqual(out.step, Step.give_up)
        self.assertEqual(len(fetcher.calls), 1)

    def test_duplicate_profile_pair_is_not_executed_twice(self):
        class RepeatSafeFetcher:
            def __init__(self):
                self.calls = []
                self.now = 1000

            def clock(self):
                return self.now

            def __call__(self, step, budget_ms):
                self.calls.append((step, budget_ms))
                self.now += 10
                if step.purpose == "http":
                    return _reply(status=403, html="no", text="no")
                if step.egress_profile == "missing":
                    return _reply(reason=FailureReason.not_measured, html="", text="")
                if step.egress_profile == "gold":
                    return _reply(html=VISIBLE, text=VISIBLE)
                raise AssertionError(
                    f"unexpected fetch: {step.provider}/{step.egress_profile}/{step.purpose}"
                )

            @property
            def routes(self):
                return [
                    (step.provider, step.egress_profile, step.purpose)
                    for step, _ in self.calls
                ]

        fetcher = RepeatSafeFetcher()
        out = _run(
            _request(allow_browser=False, egress_profiles=("missing", "missing", "gold")),
            fetcher,
        )
        self.assertTrue(out.ok)
        self.assertEqual(
            [route for route in fetcher.routes if route[1] == "missing"],
            [("curl_cffi", "missing", "egress")],
        )
        self.assertEqual(fetcher.routes, [
            ("curl_cffi", "direct", "http"),
            ("curl_cffi", "missing", "egress"),
            ("curl_cffi", "gold", "egress"),
        ])

    def test_fetcher_exception_is_not_masked_as_success(self):
        def broken(step, budget_ms):
            raise RuntimeError("adapter defect")

        with self.assertRaisesRegex(RuntimeError, "adapter defect"):
            run_product(_request(), broken, clock=lambda: 0)

    def test_terminal_timeout_clears_body_and_keeps_original_url(self):
        fetcher = ScriptedFetcher(_reply(reason=FailureReason.timeout, html="<p>interstitial</p>",
                                        text="interstitial"))
        out = _run(_request(egress_profiles=("gold",)), fetcher)
        self.assertFalse(out.ok)
        self.assertEqual(out.error_type, FailureReason.timeout)
        self.assertEqual(out.step, Step.retry_later)
        self.assertEqual((out.html, out.text), ("", ""))
        self.assertEqual(out.url, URL)
        self.assertEqual(out.final_url, URL)
        self.assertIsInstance(out.attempts[0], Attempt)


if __name__ == "__main__":
    unittest.main()
