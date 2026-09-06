"""Contract tests for the provider-container probe."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import io
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "bench" / "providers" / "docker" / "probe.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("container_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self):
        self.values = []

    def __call__(self):
        value = __import__("time").perf_counter()
        self.values.append(value)
        return value


class FakeAdapter:
    version = "observed-version"

    def __init__(self, events):
        self.events = events

    def start(self):
        self.events.append("start")

    def navigate(self, url):
        self.events.append(("navigate", url))
        return {
            "status": 200,
            "final_url": url + "#final",
            "body": "<title>Observed</title> expected marker",
            "title": "Observed",
            "redirects": 1,
        }

    def close(self):
        self.events.append("close")


class ProbeTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_warm_opens_blank_before_timer_and_target_exactly_once(self):
        events = []
        clock_values = []

        def clock():
            events.append("clock")
            value = __import__("time").perf_counter()
            clock_values.append(value)
            return value

        result = self.probe.run_probe(
            "playwright",
            "https://target.invalid/path",
            "expected marker",
            mode="warm",
            adapter_factory=lambda _: FakeAdapter(events),
            clock=clock,
            metrics=lambda: (0, 0),
        )

        self.assertEqual(
            events,
            [
                "clock",
                "start",
                "clock",
                ("navigate", "about:blank"),
                "clock",
                ("navigate", "https://target.invalid/path"),
                "clock",
                "close",
            ],
        )
        self.assertEqual(result["startup_ms"], round((clock_values[1] - clock_values[0]) * 1000))
        self.assertEqual(result["elapsed_ms"], round((clock_values[3] - clock_values[2]) * 1000))
        self.assertTrue(result["ok"])
        self.assertTrue(result["sentinel"])

    def test_cold_timer_includes_startup_and_target_is_loaded_once(self):
        events = []
        observed_metrics = self.probe._metrics()
        clock = Clock()
        result = self.probe.run_probe(
            "camoufox",
            "https://target.invalid/",
            "expected marker",
            mode="cold",
            adapter_factory=lambda _: FakeAdapter(events),
            clock=clock,
            metrics=lambda: observed_metrics,
        )

        self.assertEqual(
            events,
            ["start", ("navigate", "https://target.invalid/"), "close"],
        )
        self.assertEqual(result["startup_ms"], round((clock.values[1] - clock.values[0]) * 1000))
        self.assertEqual(result["elapsed_ms"], round((clock.values[2] - clock.values[0]) * 1000))
        self.assertEqual((result["cpu_ms"], result["peak_rss_mb"]), observed_metrics)

    def test_failure_is_normalized_as_json_compatible_result(self):
        class Broken:
            version = "unknown"

            def start(self):
                raise RuntimeError("browser unavailable")

            def close(self):
                pass

        result = self.probe.run_probe(
            "patchright",
            "https://target.invalid/",
            "marker",
            mode="cold",
            adapter_factory=lambda _: Broken(),
            clock=Clock(),
            metrics=lambda: (0, 0),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], None)
        self.assertIn("browser unavailable", result["err"])
        required = {
            "ok", "status", "final_url", "bytes", "sentinel", "challenge",
            "title", "startup_ms", "elapsed_ms", "peak_rss_mb", "cpu_ms", "err",
        }
        self.assertTrue(required.issubset(result))
        json.dumps(result)


class ProbeCliTests(unittest.TestCase):
    def test_unknown_provider_prints_one_error_json_line(self):
        env = dict(os.environ, ABG_PROVIDER="not-a-provider")
        completed = subprocess.run(
            [sys.executable, str(PROBE_PATH), "https://target.invalid/", "marker"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertFalse(payload["ok"])
        self.assertIn("unknown provider", payload["err"])

    def test_completed_probe_failure_still_exits_zero(self):
        probe = load_probe()
        payload = {
            "ok": False, "status": 403, "final_url": "u", "bytes": 1,
            "sentinel": False, "challenge": "access_denied", "title": "",
            "startup_ms": 0, "elapsed_ms": 0, "peak_rss_mb": 0,
            "cpu_ms": 0, "err": "",
        }
        with patch.object(probe, "run_probe", return_value=payload), patch.object(
            sys, "stdout", new_callable=io.StringIO
        ):
            self.assertEqual(probe.main(["u", "s"]), 0)

    def test_provider_stdout_is_redirected_so_stdout_has_one_json_line(self):
        probe = load_probe()
        payload = {
            "ok": False, "status": None, "final_url": "u", "bytes": 0,
            "sentinel": False, "challenge": "none", "title": "",
            "startup_ms": 0, "elapsed_ms": 0, "peak_rss_mb": 0,
            "cpu_ms": 0, "err": "provider noise",
        }

        def noisy(*args, **kwargs):
            print("library diagnostic")
            return payload

        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(probe, "run_probe", side_effect=noisy), patch.object(
            sys, "stdout", stdout
        ), patch.object(sys, "stderr", stderr):
            self.assertEqual(probe.main(["u", "s"]), 0)
        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
        self.assertIn("library diagnostic", stderr.getvalue())


class AdapterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_primp_rejects_an_unrecognized_profile_before_importing_provider(self):
        adapter = self.probe.PrimpAdapter()
        adapter.profile = "chrome_140"
        with self.assertRaisesRegex(ValueError, "unsupported primp profile"):
            adapter.start()

    def test_empty_sentinel_fails_before_adapter_construction(self):
        constructed = []
        result = self.probe.run_probe(
            "curl", "https://target.invalid/", "", mode="cold",
            adapter_factory=lambda provider: constructed.append(provider),
            clock=Clock(), metrics=lambda: (0, 0),
        )
        self.assertEqual(constructed, [])
        self.assertFalse(result["ok"])
        self.assertIn("empty sentinel", result["err"])

    def test_response_byte_count_preserves_non_utf8_transport_size(self):
        normalized = self.probe._result(
            200, "https://target.invalid/", b"\xffmarker", 0
        )
        events = []

        class Adapter(FakeAdapter):
            def navigate(self, url):
                events.append(("navigate", url))
                return normalized

        result = self.probe.run_probe(
            "curl",
            "https://target.invalid/",
            "marker",
            mode="cold",
            adapter_factory=lambda _: Adapter(events),
            clock=Clock(),
            metrics=lambda: (0, 0),
        )
        self.assertEqual(result["bytes"], 7)

    def test_challenge_metadata_does_not_override_sentinel_success(self):
        class Challenged(FakeAdapter):
            def navigate(self, url):
                return {
                    "status": 200, "final_url": url,
                    "body": "<p>Just a moment expected marker</p>",
                    "title": "", "redirects": 0,
                }

        result = self.probe.run_probe(
            "playwright", "https://target.invalid/", "expected marker",
            mode="cold", adapter_factory=lambda _: Challenged([]),
            clock=Clock(), metrics=lambda: (0, 0),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["challenge"], "suspected")

    def test_curl_enables_cookie_engine_for_session_redirects(self):
        captured = []
        completed = subprocess.CompletedProcess(
            [], 0, stdout=b"marker\nABG_CURL_META:200\thttps://final.invalid/\t1\t{}",
            stderr=b"",
        )
        with patch.object(self.probe.subprocess, "run", return_value=completed) as run:
            self.probe.CurlAdapter().navigate("https://target.invalid/")
            captured = run.call_args.args[0]
        self.assertIn("--cookie", captured)
        self.assertEqual(captured[captured.index("--cookie") + 1], "")

    def test_browser_snapshot_waits_for_spa_and_reads_iframe_without_renavigation(self):
        events = []

        class Frame:
            def __init__(self, contents):
                self.contents = iter(contents)

            def content(self):
                value = next(self.contents)
                events.append(("content", value))
                return value

        class Page:
            frames = [Frame(["spa-shell", "spa-shell"]), Frame(["", "marker"])]

            def wait_for_timeout(self, milliseconds):
                events.append(("wait", milliseconds))

        body = self.probe._playwright_body(Page(), "marker")
        self.assertIn("marker", body)
        self.assertEqual(events.count(("wait", 50)), 1)

    def test_pydoll_uses_required_start_options_and_unwraps_nested_cdp_value(self):
        calls = []

        class Awaitable:
            def __init__(self, value):
                self.value = value

            def __await__(self):
                if False:
                    yield None
                return self.value

        class Tab:
            def go_to(self, url, timeout):
                calls.append(("go_to", url, timeout))
                return Awaitable(None)

            def execute_script(self, script, return_by_value=False):
                calls.append(("script", script, return_by_value))
                return Awaitable({
                    "result": {"result": {"value": {
                        "html": "<html><title>CDP</title>marker</html>",
                        "title": "CDP",
                        "url": "https://final.invalid/",
                    }}}
                })

        class ChromiumOptions:
            def __init__(self):
                self.arguments = []

            def add_argument(self, argument):
                self.arguments.append(argument)

        class Chrome:
            def __init__(self, options):
                calls.append(("options", options))

            def start(self):
                return Awaitable(Tab())

            def stop(self):
                return Awaitable(None)

        chromium = types.ModuleType("pydoll.browser.chromium")
        chromium.Chrome = Chrome
        options_module = types.ModuleType("pydoll.browser.options")
        options_module.ChromiumOptions = ChromiumOptions
        browser = types.ModuleType("pydoll.browser")
        browser.__path__ = []
        pydoll = types.ModuleType("pydoll")
        pydoll.__path__ = []
        modules = {
            "pydoll": pydoll,
            "pydoll.browser": browser,
            "pydoll.browser.chromium": chromium,
            "pydoll.browser.options": options_module,
        }
        with patch.dict(sys.modules, modules):
            adapter = self.probe.PydollAdapter()
            adapter.start()
            result = adapter.navigate("https://target.invalid/")
            adapter.close()

        options = calls[0][1]
        self.assertEqual(options.binary_location, "/usr/bin/chromium")
        self.assertIs(options.headless, True)
        self.assertEqual(options.start_timeout, 60)
        # Without these the Debian chromium sandbox refuses to start under
        # --user 1002:1002, and every cell fails on the start timeout.
        self.assertEqual(options.arguments,
                         ["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-gpu", "--disable-dbus"])
        self.assertEqual(calls[1], ("go_to", "https://target.invalid/", 120))
        self.assertEqual(result["final_url"], "https://final.invalid/")
        self.assertEqual(result["title"], "CDP")
        self.assertIn("marker", result["body"])
        self.assertIs(calls[2][2], True)
        # pydoll navigates through CDP go_to() and has no response object.
        self.assertIsNone(result["headers"])

    def test_empty_headers_and_missing_headers_are_distinct(self):
        events = []

        class EmptyHeaders(FakeAdapter):
            def navigate(self, url):
                payload = super().navigate(url)
                payload["headers"] = {}
                return payload

        class MissingHeaders(FakeAdapter):
            def navigate(self, url):
                payload = super().navigate(url)
                payload["headers"] = None
                return payload

        empty = self.probe.run_probe(
            "curl", "https://target.invalid/", "expected marker",
            mode="cold", adapter_factory=lambda _: EmptyHeaders(events),
            clock=Clock(), metrics=lambda: (0, 0),
        )
        missing = self.probe.run_probe(
            "curl", "https://target.invalid/", "expected marker",
            mode="cold", adapter_factory=lambda _: MissingHeaders(events),
            clock=Clock(), metrics=lambda: (0, 0),
        )
        self.assertEqual(empty["headers"], {})
        self.assertIsNone(missing["headers"])
        self.assertNotEqual(json.dumps(empty["headers"]), json.dumps(missing["headers"]))
        self.assertIn("challenge_markers", empty)
        self.assertIn("challenge_markers", missing)

    def test_curl_parses_header_json_as_last_write_out_field(self):
        header_json = '{\n  "cf-mitigated":\t"challenge"\n}'
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout=(
                b"marker body"
                + b"\nABG_CURL_META:200\thttps://final.invalid/\t1\t"
                + header_json.encode()
            ),
            stderr=b"",
        )
        with patch.object(self.probe.subprocess, "run", return_value=completed) as run:
            result = self.probe.CurlAdapter().navigate("https://target.invalid/")
            write_out = run.call_args.args[0][run.call_args.args[0].index("--write-out") + 1]
        self.assertEqual(result["headers"]["cf-mitigated"], "challenge")
        self.assertEqual(result["body"], "marker body")
        self.assertTrue(write_out.endswith("%{header_json}"))
        self.assertEqual(write_out.count("%{header_json}"), 1)

    def test_curl_cffi_and_primp_pass_response_headers(self):
        class Response:
            status_code = 200
            url = "https://final.invalid/"
            content = b"marker"
            history = ()
            headers = {"Cf-Mitigated": "challenge"}

        curl_cffi = types.ModuleType("curl_cffi")
        requests_mod = types.ModuleType("curl_cffi.requests")
        requests_mod.get = lambda *args, **kwargs: Response()
        curl_cffi.requests = requests_mod
        with patch.dict(sys.modules, {
            "curl_cffi": curl_cffi,
            "curl_cffi.requests": requests_mod,
        }):
            cffi_result = self.probe.CurlCffiAdapter().navigate("https://target.invalid/")
        self.assertEqual(cffi_result["headers"]["cf-mitigated"], "challenge")

        class Client:
            def get(self, url):
                return Response()

        primp = self.probe.PrimpAdapter()
        primp.client = Client()
        primp_result = primp.navigate("https://target.invalid/")
        self.assertEqual(primp_result["headers"]["cf-mitigated"], "challenge")

    def test_playwright_family_uses_goto_headers_or_none(self):
        class Frame:
            def content(self):
                return "<html>marker</html>"

        class Page:
            url = "https://final.invalid/"
            frames = [Frame()]

            def __init__(self, response):
                self._response = response

            def goto(self, url, wait_until="load", timeout=0):
                return self._response

            def title(self):
                return "Observed"

        class Response:
            status = 200
            headers = {"cf-mitigated": "challenge"}

        for adapter_cls in (
            self.probe.PlaywrightAdapter,
            self.probe.PatchrightAdapter,
            self.probe.CamoufoxAdapter,
        ):
            with self.subTest(adapter=adapter_cls.__name__):
                adapter = adapter_cls()
                adapter.page = Page(Response())
                adapter.sentinel = "marker"
                present = adapter.navigate("https://target.invalid/")
                self.assertEqual(present["headers"]["cf-mitigated"], "challenge")
                adapter.page = Page(None)
                missing = adapter.navigate("https://target.invalid/")
                self.assertIsNone(missing["headers"])


class DockerDescriptorTests(unittest.TestCase):
    def dockerfile(self, provider):
        return (PROBE_PATH.parent / f"Dockerfile.{provider}").read_text()

    def test_all_seven_images_select_their_adapter_and_copy_common_probe(self):
        providers = (
            "curl", "curl_cffi", "primp", "playwright", "patchright",
            "camoufox", "pydoll",
        )
        for provider in providers:
            with self.subTest(provider=provider):
                text = self.dockerfile(provider)
                self.assertIn(f"ENV ABG_PROVIDER={provider}", text)
                self.assertIn("COPY probe.py /opt/abg/probe.py", text)

    def test_xvfb_images_have_tini_xauth_socket_and_exact_entrypoint_prefix(self):
        for provider in ("patchright", "camoufox"):
            with self.subTest(provider=provider):
                text = self.dockerfile(provider)
                self.assertIn("xvfb xauth tini", text)
                self.assertIn("mkdir -p /tmp/.X11-unix", text)
                self.assertIn("chmod 1777 /tmp/.X11-unix", text)
                self.assertIn(
                    'ENTRYPOINT ["/usr/bin/tini","-g","--","xvfb-run","-a"', text
                )

    def test_playwright_browser_store_is_shared_with_non_root_user(self):
        text = self.dockerfile("playwright")
        self.assertIn("ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright", text)
        self.assertIn("chmod -R a+rX /ms-playwright", text)

    def test_pydoll_installs_and_selects_system_chromium(self):
        text = self.dockerfile("pydoll")
        self.assertIn("chromium ca-certificates", text)
        self.assertNotIn("google-chrome", text)

    def test_browser_images_provide_writable_runtime_home(self):
        for provider in ("playwright", "patchright", "camoufox", "pydoll"):
            with self.subTest(provider=provider):
                text = self.dockerfile(provider)
                self.assertIn("HOME=/opt/home", text)
                self.assertIn("chmod 0777 /opt/home", text)

    def test_camoufox_uses_shared_browser_cache_and_installs_browser_deps(self):
        text = self.dockerfile("camoufox")
        self.assertNotIn("XDG_CACHE_HOME", text)
        self.assertNotIn("CAMOUFOX_CACHE_DIR", text)
        self.assertIn("camoufox[geoip]==0.5.6", text)
        self.assertIn("chmod -R a+rwX /opt/home", text)


if __name__ == "__main__":
    unittest.main()
