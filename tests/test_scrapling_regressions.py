"""The twelve coverage gaps identified by the independent M8 mutation audit."""

from contextlib import contextmanager
import sys
import types
import unittest
from unittest.mock import patch

from bench.providers.registry import PROVIDERS
from tests.test_probe import load_probe


REQUEST_URL = "https://target.invalid/"


def page(**overrides):
    fields = dict(status=200, url="https://final.invalid/", body=b"marker",
                  headers={}, history=())
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


@contextmanager
def session_modules(response, init, events):
    """Observe the adapter's real session calls; assertions stay in each test."""
    class Session:
        def __init__(self, **kwargs):
            init.update(kwargs)

        def __enter__(self):
            events.append("enter")
            return self

        def fetch(self, url, **kwargs):
            events.append("fetch")
            return response

        def __exit__(self, *args):
            events.append("exit")

    fetchers = types.ModuleType("scrapling.fetchers")
    fetchers.StealthySession = Session
    scrapling = types.ModuleType("scrapling")
    scrapling.fetchers = fetchers
    with patch.dict(sys.modules, {"scrapling": scrapling, "scrapling.fetchers": fetchers}):
        yield


class ScraplingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def navigate(self, response):
        adapter = self.probe.ScraplingAdapter()
        adapter.session = types.SimpleNamespace(fetch=lambda url, **kwargs: response)
        return adapter.navigate(REQUEST_URL)

    def start_options(self):
        init = {}
        with session_modules(page(), init, []):
            adapter = self.probe.ScraplingAdapter()
            try:
                adapter.start()
            finally:
                adapter.close()
        return init

    def test_scrapling_calls_body(self):
        class CallableBody:
            calls = 0

            def body(self):
                self.calls += 1
                return "Привет".encode("utf-8")

        response = CallableBody()
        result = self.navigate(response)
        self.assertEqual(response.calls, 1)
        self.assertEqual(result["body"], "Привет")
        self.assertEqual(result["bytes"], 12)

    def test_scrapling_encodes_text_body(self):
        error = None
        result = None
        try:
            result = self.navigate(page(body="Привет"))
        except Exception as exc:
            # AttributeError from an unconverted str is an assertion failure
            # about this contract, not an incidental unittest error.
            error = exc
        self.assertIsNone(error)
        self.assertEqual(result["body"], "Привет")
        self.assertEqual(result["bytes"], 12)

    def test_scrapling_none_body_is_empty(self):
        result = self.navigate(page(body=None))
        self.assertEqual(result["body"], "")
        self.assertEqual(result["bytes"], 0)

    def test_scrapling_counts_redirects(self):
        result = self.navigate(page(history=[object(), object()]))
        self.assertEqual(result["redirects"], 2)

    def test_scrapling_missing_history_is_empty(self):
        for missing in (False, True):
            with self.subTest(missing_attribute=missing):
                response = page(history=None)
                if missing:
                    del response.history
                error = None
                result = None
                try:
                    result = self.navigate(response)
                except Exception as exc:
                    # Both missing and explicit None must navigate successfully.
                    error = exc
                self.assertIsNone(error)
                self.assertEqual(result["redirects"], 0)

    def test_scrapling_preserves_status(self):
        for status in (201, 403):
            result = self.navigate(page(status=status))
            self.assertEqual(result["status"], status)
        with session_modules(page(status=403, body=b"marker"), {}, []):
            result = self.probe.run_probe(
                "scrapling", REQUEST_URL, "marker", mode="cold",
                adapter_factory=lambda _: self.probe.ScraplingAdapter(),
                metrics=lambda: (0, 0),
            )
        self.assertTrue(result["sentinel"])
        self.assertEqual(result["status"], 403)
        self.assertFalse(result["ok"])

    def test_scrapling_empty_url_uses_request_url(self):
        for final_url in (None, ""):
            with self.subTest(final_url=final_url):
                result = self.navigate(page(url=final_url))
                self.assertEqual(result["final_url"], REQUEST_URL)

    def test_probe_provider_names_match_registry(self):
        self.assertIn("scrapling", self.probe.PROVIDERS)
        self.assertEqual(self.probe.PROVIDERS, {provider.name for provider in PROVIDERS})

    def test_scrapling_session_browser_options(self):
        init = self.start_options()
        self.assertIs(init["real_chrome"], True)

    def test_scrapling_disables_google_search(self):
        init = self.start_options()
        self.assertIs(init["google_search"], False)

    def test_scrapling_session_timeout(self):
        init = self.start_options()
        self.assertEqual(init["timeout"], 120_000)

    def test_scrapling_enters_session_before_fetch(self):
        events = []
        with session_modules(page(), {}, events):
            adapter = self.probe.ScraplingAdapter()
            try:
                adapter.start()
                adapter.navigate(REQUEST_URL)
            finally:
                adapter.close()
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual(events, ["enter", "fetch", "exit"])


if __name__ == "__main__":
    unittest.main()
