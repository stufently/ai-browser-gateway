"""Contract tests for the provider-container probe."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import io
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from bench.egress import load_profiles


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
                    "body": (
                        "<html><head><title>Just a moment...</title></head>"
                        "<body><p>expected marker</p></body></html>"
                    ),
                    "title": "", "redirects": 0,
                }

        result = self.probe.run_probe(
            "playwright", "https://target.invalid/", "expected marker",
            mode="cold", adapter_factory=lambda _: Challenged([]),
            clock=Clock(), metrics=lambda: (0, 0),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["challenge"], "suspected")

    def test_adapters_honor_abg_proxy_and_direct_when_unset(self):
        proxy = "http://user:pass@proxy.invalid:8080"
        completed = subprocess.CompletedProcess(
            [], 0, stdout=b"marker\nABG_CURL_META:200\thttps://final.invalid/\t1\t{}",
            stderr=b"",
        )

        class Response:
            status_code = 200
            url = "https://final.invalid/"
            content = b"marker"
            history = ()
            headers = {}

        with patch.dict(os.environ):
            os.environ.pop("ABG_PROXY", None)
            with patch.object(self.probe.subprocess, "run", return_value=completed) as run:
                self.probe.CurlAdapter().navigate("https://target.invalid/")
                self.assertNotIn("--proxy", run.call_args.args[0])

        with patch.dict(os.environ, {"ABG_PROXY": proxy}):
            with patch.object(self.probe.subprocess, "run", return_value=completed) as run:
                self.probe.CurlAdapter().navigate("https://target.invalid/")
                command = run.call_args.args[0]
            self.assertNotIn("--proxy", command)
            self.assertFalse(any("pass@" in part for part in command))
            env = run.call_args.kwargs.get("env") or {}
            self.assertEqual(env.get("ALL_PROXY"), proxy)

            captured = {}

            def get(*args, **kwargs):
                captured.update(kwargs)
                return Response()

            curl_cffi = types.ModuleType("curl_cffi")
            requests_mod = types.ModuleType("curl_cffi.requests")
            requests_mod.get = get
            curl_cffi.requests = requests_mod
            with patch.dict(sys.modules, {
                "curl_cffi": curl_cffi,
                "curl_cffi.requests": requests_mod,
            }):
                self.probe.CurlCffiAdapter().navigate("https://target.invalid/")
            self.assertEqual(captured.get("proxy"), proxy)

            primp_kwargs = {}

            class Client:
                def __init__(self, **kwargs):
                    primp_kwargs.update(kwargs)

                def get(self, url):
                    return Response()

            primp_mod = types.ModuleType("primp")
            primp_mod.Client = Client
            adapter = self.probe.PrimpAdapter()
            with patch.dict(sys.modules, {"primp": primp_mod}):
                adapter.start()
            self.assertEqual(primp_kwargs.get("proxy"), proxy)
            self.assertEqual(primp_kwargs.get("impersonate"), "chrome")

    def test_browser_adapters_pass_proxy_server_on_launch(self):
        proxy = "http://user:pass@proxy.invalid:8080"
        launched = {}

        class Browser:
            def new_page(self):
                return object()

            def close(self):
                pass

        class Chromium:
            def launch(self, **kwargs):
                launched["playwright"] = kwargs
                return Browser()

        class Runtime:
            chromium = Chromium()

            def start(self):
                return self

            def stop(self):
                pass

        class SyncApi:
            def start(self):
                return Runtime()

        def sync_playwright():
            return SyncApi()

        playwright_mod = types.ModuleType("playwright")
        sync_mod = types.ModuleType("playwright.sync_api")
        sync_mod.sync_playwright = sync_playwright
        playwright_mod.sync_api = sync_mod
        patchright_mod = types.ModuleType("patchright")
        patchright_sync = types.ModuleType("patchright.sync_api")
        patchright_sync.sync_playwright = sync_playwright
        patchright_mod.sync_api = patchright_sync

        class Camoufox:
            def __init__(self, **kwargs):
                launched["camoufox"] = kwargs

            def __enter__(self):
                return Browser()

            def __exit__(self, *args):
                return None

        camoufox_mod = types.ModuleType("camoufox")
        camoufox_sync = types.ModuleType("camoufox.sync_api")
        camoufox_sync.Camoufox = Camoufox
        camoufox_mod.sync_api = camoufox_sync

        with patch.dict(os.environ, {"ABG_PROXY": proxy}), patch.dict(sys.modules, {
            "playwright": playwright_mod,
            "playwright.sync_api": sync_mod,
            "patchright": patchright_mod,
            "patchright.sync_api": patchright_sync,
            "camoufox": camoufox_mod,
            "camoufox.sync_api": camoufox_sync,
        }):
            expected = self.probe.playwright_proxy(proxy)
            self.probe.PlaywrightAdapter().start()
            self.assertEqual(launched["playwright"].get("proxy"), expected)
            self.probe.PatchrightAdapter().start()
            self.probe.CamoufoxAdapter().start()
            self.assertEqual(launched["camoufox"].get("proxy"), expected)

    def test_pydoll_adds_proxy_server_argument_when_set(self):
        proxy = "http://user:pass@proxy.invalid:8080"
        captured = {}

        class Awaitable:
            def __init__(self, value):
                self.value = value

            def __await__(self):
                if False:
                    yield None
                return self.value

        class ChromiumOptions:
            def __init__(self):
                self.arguments = []

            def add_argument(self, argument):
                self.arguments.append(argument)

        class Chrome:
            def __init__(self, options):
                captured["options"] = options

            def start(self):
                return Awaitable(object())

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
        with patch.dict(os.environ, {"ABG_PROXY": proxy}), patch.dict(sys.modules, modules):
            adapter = self.probe.PydollAdapter()
            adapter.start()
        self.assertIn("--proxy-server=" + proxy, captured["options"].arguments)

    def test_entrance_fetch_uses_proxy_handler_when_set(self):
        proxy = "http://user:pass@proxy.invalid:8080"
        opened = {}

        class FakeOpener:
            def open(self, request, timeout=120):
                opened["request"] = request
                opened["timeout"] = timeout

                class Resp:
                    status = 200
                    headers = {}

                    def geturl(self):
                        return "https://example.invalid/"

                    def read(self):
                        return b"<rss></rss>"

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return None

                return Resp()

        fake = FakeOpener()
        with patch.dict(os.environ, {"ABG_PROXY": proxy}):
            with patch.object(self.probe, "build_opener", return_value=fake) as build:
                self.probe._fetch_entrance("https://example.invalid/")
        self.assertEqual(build.call_count, 1)
        handler = build.call_args.args[0]
        self.assertEqual(handler.proxies.get("http"), proxy)
        self.assertEqual(handler.proxies.get("https"), proxy)
        self.assertEqual(opened["timeout"], 120)

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


class ScraplingAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def _fake_modules(self, session_cls):
        fetchers = types.ModuleType("scrapling.fetchers")
        fetchers.StealthySession = session_cls
        scrapling = types.ModuleType("scrapling")
        scrapling.fetchers = fetchers
        return {"scrapling": scrapling, "scrapling.fetchers": fetchers}

    def test_scrapling_requests_cloudflare_solver(self):
        captured = {}

        class Page:
            status = 200
            url = "https://final.invalid/"
            body = b"<html>marker</html>"
            headers = {"cf-mitigated": "challenge"}
            history = ()

        class Session:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *args):
                captured["closed"] = True

            def fetch(self, url, **kwargs):
                captured["fetch"] = (url, kwargs)
                return Page()

        with patch.dict(sys.modules, self._fake_modules(Session)):
            adapter = self.probe.ScraplingAdapter()
            adapter.start()
            result = adapter.navigate("https://target.invalid/")
            adapter.close()
        self.assertIs(captured["fetch"][1]["solve_cloudflare"], True)
        self.assertIs(captured["init"]["solve_cloudflare"], True)
        self.assertEqual(captured["init"]["retries"], 1)
        self.assertEqual(captured["fetch"][0], "https://target.invalid/")
        self.assertTrue(captured.get("closed"))

    def test_scrapling_warm_blank_does_not_call_fetch(self):
        captured = {}

        class Page:
            status = 200
            url = "https://final.invalid/"
            body = b"<html>marker</html>"
            headers = {}
            history = ()

        class Session:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def fetch(self, url, **kwargs):
                captured.setdefault("urls", []).append(url)
                if url == "about:blank":
                    raise RuntimeError(f"Failed to get response for {url}")
                return Page()

        with patch.dict(sys.modules, self._fake_modules(Session)):
            result = self.probe.run_probe(
                "scrapling",
                "https://target.invalid/",
                "marker",
                mode="warm",
                adapter_factory=lambda _: self.probe.ScraplingAdapter(),
                clock=Clock(),
                metrics=lambda: (0, 0),
            )
        self.assertNotIn("about:blank", captured.get("urls", []))
        self.assertTrue(result["ok"])
        self.assertTrue(result["sentinel"])

    def _probe_response(self, status, body, headers):
        page = types.SimpleNamespace(
            status=status, url="https://final.invalid/", body=body,
            headers=headers, history=(),
        )

        class Session:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def fetch(self, url, **kwargs):
                return page

        with patch.dict(sys.modules, self._fake_modules(Session)):
            return self.probe.run_probe(
                "scrapling", "https://target.invalid/", mode="cold",
                content_only=True, clock=Clock(), metrics=lambda: (0, 0),
            )

    def test_scrapling_drops_stale_cf_header_on_clean_2xx(self):
        body = (b"<html><title>Directory</title><body>Real content"
                b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
                b"</script></body></html>")
        for status in (200, 204, 299):
            with self.subTest(status=status):
                headers = {"CF-Mitigated": "challenge", "Content-Type": "text/html",
                           "X-Keep": "present"}
                result = self._probe_response(status, body, headers)
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"],
                                 {"content-type": "text/html", "x-keep": "present"})
                self.assertEqual(result["challenge"], "none")
                self.assertEqual(result["challenge_markers"], ["body_cf_challenge_platform"])
                self.assertEqual(headers["CF-Mitigated"], "challenge")

    def test_scrapling_drops_stale_cf_header_with_platform_and_noindex(self):
        body = (b'<html><meta name="robots" content="noindex,nofollow">'
                b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">'
                b'</script></html>')
        headers = {"cf-mitigated": "challenge"}
        result = self._probe_response(200, body, headers)
        self.assertEqual(result["err"], "")
        self.assertEqual(result["headers"], {})
        self.assertEqual(result["challenge"], "none")
        self.assertEqual(result["challenge_markers"],
                         ["body_cf_challenge_platform", "body_noindex_nofollow"])
        self.assertEqual(headers, {"cf-mitigated": "challenge"})

    def test_scrapling_preserves_cf_header_on_non_jsd_platform_path(self):
        for path in (
            "/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=x",
            "/CDN-CGI/CHALLENGE-PLATFORM/H/G/ORCHESTRATE/CHL_PAGE/V1?ray=x",
            "/cdn-cgi/challenge-platform",
            "/cdn-cgi/challenge-platform/scripts/jsd",
            "/cdn-cgi/challenge-platform/scripts/jsd-other/main.js",
        ):
            with self.subTest(path=path):
                body = f'<script src="{path}"></script>'.encode()
                headers = {"cf-mitigated": "challenge"}
                result = self._probe_response(200, body, headers)
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                self.assertEqual(result["challenge"], "suspected")
                self.assertEqual(result["challenge_markers"],
                                 ["header_cf_mitigated", "body_cf_challenge_platform"])
                self.assertEqual(headers, {"cf-mitigated": "challenge"})

    def test_scrapling_preserves_cf_header_on_mixed_platform_paths(self):
        jsd = b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        orchestrate = (b'<script src="/cdn-cgi/challenge-platform/'
                       b'h/g/orchestrate/chl_page/v1?ray=x"></script>')
        for body in (jsd + orchestrate, orchestrate + jsd):
            with self.subTest(body=body):
                result = self._probe_response(200, body, {"cf-mitigated": "challenge"})
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                self.assertEqual(result["challenge"], "suspected")
                self.assertEqual(result["challenge_markers"],
                                 ["header_cf_mitigated", "body_cf_challenge_platform"])

    def test_scrapling_drops_stale_cf_header_with_only_jsd_paths(self):
        scripts = ('<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
                   '<script src="/CDN-CGI/CHALLENGE-PLATFORM/SCRIPTS/JSD/main.js"></script>')
        for body in (scripts, b"\xff" + scripts.encode()):
            with self.subTest(body=body):
                result = self._probe_response(200, body, {"cf-mitigated": "challenge"})
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {})
                self.assertEqual(result["challenge"], "none")
                self.assertEqual(result["challenge_markers"], ["body_cf_challenge_platform"])

    def test_scrapling_preserves_cf_header_with_jsd_and_challenge_strings(self):
        jsd = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        widgets = (
            ('turnstile', '<div class="cf-turnstile" data-sitekey="key"></div>'),
            ('cf-chl', '<div class="cf-chl-container"></div>'),
            ('cf_chl', '<script>window.cf_chl_state = {};</script>'),
            ('challenge-platform', '<div class="challenge-platform"></div>'),
            ('challenges.cloudflare.com',
             '<script src="https://challenges.cloudflare.com/widget.js"></script>'),
            ('cf-challenge', '<div class="cf-challenge"></div>'),
            ('cf-captcha', '<div class="cf-captcha"></div>'),
            ('hcaptcha', '<script src="https://js.hcaptcha.com/1/api.js"></script>'),
            ('recaptcha', '<script src="https://www.google.com/recaptcha/api.js"></script>'),
            ('g-recaptcha', '<div class="g-recaptcha" data-sitekey="key"></div>'),
            ('h-captcha', '<div class="h-captcha" data-sitekey="key"></div>'),
            ('/cdn-cgi/challenge', '<form action="/cdn-cgi/challenge" method="post"></form>'),
            ('CF-TURNSTILE', '<DIV CLASS="CF-TURNSTILE" DATA-SITEKEY="key"></DIV>'),
        )
        for marker, widget in widgets:
            # Unquoted HTML attributes also carry markers, even where the
            # detector's existing quoted-attribute captcha rule does not match.
            for markup in (widget, widget.replace('"', '')):
                html = f'<html><p>Checking your browser</p>{jsd}{markup}</html>'
                for body in (html, b"\xff" + html.encode()):
                    with self.subTest(marker=marker, markup=markup,
                                      body_type=type(body).__name__):
                        headers = {"cf-mitigated": "challenge"}
                        result = self._probe_response(200, body, headers)
                        self.assertEqual(result["err"], "")
                        self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                        self.assertEqual(result["challenge"], "suspected")
                        self.assertIn("header_cf_mitigated", result["challenge_markers"])
                        self.assertEqual(headers, {"cf-mitigated": "challenge"})

    def test_scrapling_drops_stale_cf_header_with_jsd_and_ordinary_words(self):
        body = (b'<html><p>A business challenge: cloudflare integration.</p>'
                b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
                b'</html>')
        result = self._probe_response(200, body, {"cf-mitigated": "challenge"})
        self.assertEqual(result["err"], "")
        self.assertEqual(result["headers"], {})
        self.assertEqual(result["challenge"], "none")
        self.assertEqual(result["challenge_markers"], ["body_cf_challenge_platform"])

    def test_scrapling_preserves_cf_header_on_single_cf_body_marker(self):
        for marker, rule in (("cf_chl_opt", "body_cf_chl_opt"),
                             ("__cf_chl", "body_cf_chl"),
                             ("challenges.cloudflare.com", "body_cf_challenges_host")):
            with self.subTest(marker=marker):
                body = f"<html>{marker}</html>".encode()
                headers = {"cf-mitigated": "challenge"}
                result = self._probe_response(200, body, headers)
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                self.assertEqual(result["challenge"], "suspected")
                self.assertEqual(result["challenge_markers"], ["header_cf_mitigated", rule])
                self.assertEqual(headers, {"cf-mitigated": "challenge"})

    def test_scrapling_preserves_cf_header_outside_2xx(self):
        for status in (None, 199, 300, 403, 429, 500):
            with self.subTest(status=status):
                result = self._probe_response(
                    status, b"<html>Real content</html>", {"cf-mitigated": "challenge"})
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                self.assertEqual(result["challenge"], "suspected")
                self.assertIn("header_cf_mitigated", result["challenge_markers"])

    def test_scrapling_preserves_cf_header_on_2xx_interstitial(self):
        body = (ROOT / "tests/fixtures/cf_interstitial_200body_403.html").read_bytes()
        for value, verdict in (("challenge", "suspected"), ("interactive", "interactive")):
            with self.subTest(value=value):
                result = self._probe_response(200, body, {"cf-mitigated": value})
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], {"cf-mitigated": value})
                self.assertEqual(result["challenge"], verdict)
                self.assertIn("header_cf_mitigated", result["challenge_markers"])

    def test_scrapling_preserves_cf_header_on_2xx_captcha(self):
        for attr in ("src", "class", "id", "name"):
            for extra in ("", '<script src="/cdn-cgi/challenge-platform/jsd.js"></script>'):
                with self.subTest(attr=attr, extra=extra):
                    body = f'<html><input {attr}="captcha">{extra}</html>'.encode()
                    headers = {"cf-mitigated": "challenge"}
                    result = self._probe_response(200, body, headers)
                    self.assertEqual(result["err"], "")
                    self.assertEqual(result["headers"], {"cf-mitigated": "challenge"})
                    self.assertEqual(result["challenge"], "suspected")
                    self.assertIn("body_captcha", result["challenge_markers"])
                    self.assertIn("header_cf_mitigated", result["challenge_markers"])
                    self.assertEqual(headers, {"cf-mitigated": "challenge"})

    def test_scrapling_keeps_missing_and_empty_headers_distinct(self):
        for headers, expected in ((None, None), ({}, {}), ({"cf-mitigated": "challenge"}, {})):
            with self.subTest(headers=headers):
                result = self._probe_response(200, b"<html>Real content</html>", headers)
                self.assertEqual(result["err"], "")
                self.assertEqual(result["headers"], expected)
                self.assertEqual(result["challenge"], "none")

    def test_scrapling_engine_failure_is_normalized_not_raised(self):
        class Boom:
            def __init__(self, **kwargs):
                raise RuntimeError("browser unavailable")

        with patch.dict(sys.modules, self._fake_modules(Boom)):
            result = self.probe.run_probe(
                "scrapling",
                "https://target.invalid/",
                "marker",
                mode="cold",
                adapter_factory=lambda _: self.probe.ScraplingAdapter(),
                clock=Clock(),
                metrics=lambda: (0, 0),
            )
        self.assertFalse(result["ok"])
        self.assertIn("browser unavailable", result["err"])

    def test_scrapling_reports_package_version(self):
        class Page:
            status = 200
            url = "https://final.invalid/"
            body = b"marker"
            headers = {}
            history = ()

        class Session:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def fetch(self, url, **kwargs):
                return Page()

        with patch.dict(sys.modules, self._fake_modules(Session)), patch.object(
            self.probe, "_version", return_value="0.4.15"
        ):
            result = self.probe.run_probe(
                "scrapling",
                "https://target.invalid/",
                "marker",
                mode="cold",
                adapter_factory=lambda _: self.probe.ScraplingAdapter(),
                clock=Clock(),
                metrics=lambda: (0, 0),
            )
        self.assertEqual(result["provider_version"], "0.4.15")

    def test_make_adapter_selects_scrapling(self):
        adapter = None
        try:
            adapter = self.probe.make_adapter("scrapling")
        except ValueError:
            pass
        self.assertIsInstance(adapter, self.probe.ScraplingAdapter)


class ProxyWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def test_redact_covers_any_proxy_scheme(self):
        """socks5 у провайдеров прокси — обычное дело; curl печатает его так же."""
        leaked = "curl: (7) Unsupported proxy scheme for 'socks5://user:pass@h:1080/'"
        cleaned = self.probe.redact(leaked)
        self.assertNotIn("pass", cleaned)
        self.assertIn("socks5://***@h:1080", cleaned)

    def test_playwright_proxy_keeps_ipv6_brackets(self):
        """Без скобок host стал бы fd00, то есть прокси молча оказался бы другим."""
        settings = self.probe.playwright_proxy("http://user:pass@[fd00::1]:8080")
        self.assertEqual(settings["server"], "http://[fd00::1]:8080")

    def test_both_playwright_packages_get_proxy(self):
        proxy = "http://user:pass@proxy.invalid:8080"
        expected = self.probe.playwright_proxy(proxy)
        self.assertEqual(expected["password"], "pass")
        self.assertNotIn("pass@", expected["server"])

        class Browser:
            def new_page(self):
                return object()

        class Runtime:
            def __init__(self, bucket):
                self.bucket = bucket

            @property
            def chromium(self):
                parent = self

                class Chromium:
                    def launch(self, **kwargs):
                        parent.bucket["proxy"] = kwargs.get("proxy")
                        return Browser()

                return Chromium()

            def start(self):
                return self

        launched = {"playwright": {}, "patchright": {}}

        def sync_for(name):
            def sync_playwright():
                class Api:
                    def start(self):
                        return Runtime(launched[name])
                return Api()
            return sync_playwright

        playwright_mod = types.ModuleType("playwright")
        playwright_sync = types.ModuleType("playwright.sync_api")
        playwright_sync.sync_playwright = sync_for("playwright")
        playwright_mod.sync_api = playwright_sync
        patchright_mod = types.ModuleType("patchright")
        patchright_sync = types.ModuleType("patchright.sync_api")
        patchright_sync.sync_playwright = sync_for("patchright")
        patchright_mod.sync_api = patchright_sync
        with patch.dict(os.environ, {"ABG_PROXY": proxy}), patch.dict(sys.modules, {
            "playwright": playwright_mod,
            "playwright.sync_api": playwright_sync,
            "patchright": patchright_mod,
            "patchright.sync_api": patchright_sync,
        }):
            self.probe.PlaywrightAdapter().start()
            self.probe.PatchrightAdapter().start()
        self.assertEqual(launched["playwright"]["proxy"], expected)
        self.assertEqual(launched["patchright"]["proxy"], expected)

    def test_result_without_url_key(self):
        with tempfile.TemporaryDirectory() as box:
            path = Path(box) / "proxies.toml"
            path.write_text("[profile.gold]\nnote = \"no url\"\n", encoding="utf-8")
            os.chmod(path, 0o600)
            loaded = True
            try:
                profiles = load_profiles(path)
            except KeyError:
                loaded = False
            self.assertTrue(loaded)
            self.assertEqual(profiles.get("gold"), "")

    def test_playwright_proxy_splits_userinfo(self):
        got = self.probe.playwright_proxy("http://user:p%40ss@proxy.invalid:8080")
        self.assertEqual(got, {
            "server": "http://proxy.invalid:8080",
            "username": "user",
            "password": "p@ss",
        })
        self.assertEqual(
            self.probe.playwright_proxy("http://proxy.invalid:8080"),
            {"server": "http://proxy.invalid:8080"},
        )

    def test_redact_strips_userinfo_and_leaves_plain_text(self):
        text = self.probe.redact(
            "curl: (5) Unsupported proxy syntax in 'http://user:pass@proxy.invalid:8080/'"
        )
        self.assertNotIn("pass", text)
        self.assertIn("proxy.invalid:8080", text)
        self.assertEqual(
            self.probe.redact("curl: (7) connection refused"),
            "curl: (7) connection refused",
        )


class DockerDescriptorTests(unittest.TestCase):
    def dockerfile(self, provider):
        return (PROBE_PATH.parent / f"Dockerfile.{provider}").read_text()

    def test_all_seven_images_select_their_adapter_and_copy_common_probe(self):
        providers = (
            "curl", "curl_cffi", "primp", "playwright", "patchright",
            "camoufox", "pydoll", "scrapling",
        )
        for provider in providers:
            with self.subTest(provider=provider):
                text = self.dockerfile(provider)
                self.assertIn(f"ENV ABG_PROVIDER={provider}", text)
                self.assertIn("COPY probe.py /opt/abg/probe.py", text)

    def test_xvfb_images_have_tini_xauth_socket_and_exact_entrypoint_prefix(self):
        for provider in ("patchright", "camoufox", "scrapling"):
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
        for provider in ("playwright", "patchright", "camoufox", "pydoll", "scrapling"):
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

    def test_scrapling_pins_fetchers_extra_and_installs_chrome(self):
        text = self.dockerfile("scrapling")
        self.assertIn("scrapling[fetchers]==0.4.15", text)
        self.assertIn("patchright install --with-deps chrome", text)
        self.assertIn("ENV ABG_PROVIDER=scrapling", text)
        self.assertIn("chmod a+rX /opt/abg/probe.py", text)


if __name__ == "__main__":
    unittest.main()
