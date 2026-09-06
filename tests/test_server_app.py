"""WSGI stand A, invoked in-process with no sockets."""

from __future__ import annotations

import gzip
import io
import time
import unittest
from http.cookies import SimpleCookie

from bench.scenarios import SCENARIOS, by_id
from bench.server.app import build_app


def call(app, path: str, query: str = "", extra_headers: dict[str, str] | None = None):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_NAME": "stand",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "SCRIPT_NAME": "",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "CONTENT_LENGTH": "0",
    }
    if extra_headers:
        for key, value in extra_headers.items():
            environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured: list[tuple[str, list[tuple[str, str]]]] = []

    def start_response(status, headers, exc_info=None):
        captured.append((status, list(headers)))

    body = b"".join(app(environ, start_response))
    status, headers = captured[0]
    return int(status.split()[0]), {key: value for key, value in headers}, body


class ServerAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = build_app()

    def test_every_scenario_path_is_routed(self) -> None:
        for item in SCENARIOS:
            code, _, _ = call(self.app, item.path)
            self.assertNotEqual(code, 404, item.id)

    def test_static_html_contains_sentinel(self) -> None:
        code, _, body = call(self.app, "/static")
        self.assertEqual(code, 200)
        self.assertIn(by_id("static").sentinel, body.decode("utf-8"))

    def test_js_raw_html_has_no_sentinel(self) -> None:
        _, _, body = call(self.app, "/js")
        raw_html = body.decode("utf-8")
        js_sentinel = by_id("js").sentinel
        self.assertNotIn(js_sentinel, raw_html)
        self.assertIn("<script>", raw_html)

    def test_spa_raw_html_has_no_sentinel(self) -> None:
        _, _, shell = call(self.app, "/spa")
        self.assertNotIn(by_id("spa").sentinel, shell.decode("utf-8"))
        _, _, data = call(self.app, "/spa/data")
        self.assertIn(by_id("spa").sentinel, data.decode("utf-8"))

    def test_iframe_parent_has_no_sentinel(self) -> None:
        _, _, parent = call(self.app, "/iframe")
        self.assertNotIn(by_id("iframe").sentinel, parent.decode("utf-8"))
        _, _, child = call(self.app, "/iframe/child")
        self.assertIn(by_id("iframe").sentinel, child.decode("utf-8"))

    def test_shadow_raw_html_has_no_sentinel(self) -> None:
        _, _, body = call(self.app, "/shadow")
        html = body.decode("utf-8")
        self.assertNotIn(by_id("shadow").sentinel, html)
        self.assertIn('attachShadow({mode: "closed"})', html)

    def test_broken_js_raw_html_has_no_sentinel(self) -> None:
        _, _, body = call(self.app, "/broken-js")
        html = body.decode("utf-8")
        self.assertNotIn(by_id("broken_js").sentinel, html)
        self.assertIn("throw", html)

    def test_redirect_chain_is_three_302_then_sentinel(self) -> None:
        code, headers, _ = call(self.app, "/redirect")
        self.assertEqual(code, 302)
        code, headers, _ = call(self.app, headers["Location"])
        self.assertEqual(code, 302)
        code, headers, _ = call(self.app, headers["Location"])
        self.assertEqual(code, 302)
        code, _, body = call(self.app, headers["Location"])
        self.assertEqual(code, 200)
        self.assertIn(by_id("redirect").sentinel, body.decode("utf-8"))

    def test_gzip_body_matches_identity(self) -> None:
        _, _, identity = call(self.app, "/compression")
        code, headers, body = call(
            self.app, "/compression", extra_headers={"Accept-Encoding": "gzip"}
        )
        self.assertEqual(code, 200)
        self.assertEqual(headers.get("Content-Encoding"), "gzip")
        self.assertEqual(gzip.decompress(body), identity)
        self.assertIn(by_id("compression").sentinel, gzip.decompress(body).decode("utf-8"))

    def test_gzip_q0_is_not_compressed(self) -> None:
        _, _, identity = call(self.app, "/compression")
        code, headers, body = call(
            self.app,
            "/compression",
            extra_headers={"Accept-Encoding": "gzip;q=0, identity"},
        )
        self.assertNotEqual(headers.get("Content-Encoding"), "gzip")
        self.assertEqual(code, 200)
        self.assertEqual(body, identity)

    def test_br_is_not_served_without_brotli(self) -> None:
        try:
            import brotli  # noqa: F401
        except ImportError:
            code, headers, body = call(
                self.app, "/compression", extra_headers={"Accept-Encoding": "br"}
            )
            self.assertEqual(code, 200)
            self.assertNotEqual(headers.get("Content-Encoding"), "br")
            self.assertIn(by_id("compression").sentinel, body.decode("utf-8"))

    def test_session_check_without_cookie_is_401(self) -> None:
        code, _, body = call(self.app, "/session/check")
        self.assertEqual(code, 401)
        self.assertNotIn(by_id("session").sentinel, body.decode("utf-8"))

    def test_session_check_with_cookie_returns_sentinel(self) -> None:
        store: dict = {}
        app = build_app(session_store=store)
        code, headers, _ = call(app, "/session/start")
        self.assertEqual(code, 200)
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        token = cookie["abg_session"].value
        code, _, body = call(
            app, "/session/check", extra_headers={"Cookie": f"abg_session={token}"}
        )
        self.assertEqual(code, 200)
        self.assertIn(by_id("session").sentinel, body.decode("utf-8"))

    def test_session_store_is_injected(self) -> None:
        app_a = build_app(session_store={})
        app_b = build_app(session_store={})
        _, headers, _ = call(app_a, "/session/start")
        cookie = SimpleCookie()
        cookie.load(headers["Set-Cookie"])
        token = cookie["abg_session"].value
        code, _, _ = call(
            app_b, "/session/check", extra_headers={"Cookie": f"abg_session={token}"}
        )
        self.assertEqual(code, 401)

    def test_error_403(self) -> None:
        code, _, body = call(self.app, "/errors/403")
        self.assertEqual(code, 403)
        self.assertNotIn(by_id("errors").sentinel, body.decode("utf-8"))

    def test_error_429(self) -> None:
        code, _, body = call(self.app, "/errors/429")
        self.assertEqual(code, 429)
        self.assertNotIn(by_id("errors").sentinel, body.decode("utf-8"))

    def test_error_503(self) -> None:
        code, _, body = call(self.app, "/errors/503")
        self.assertEqual(code, 503)
        self.assertNotIn(by_id("errors").sentinel, body.decode("utf-8"))

    def test_error_explain_has_sentinel(self) -> None:
        code, _, body = call(self.app, "/errors/explain")
        self.assertEqual(code, 200)
        self.assertIn(by_id("errors").sentinel, body.decode("utf-8"))

    def test_slow_default_delay_is_zero(self) -> None:
        started = time.perf_counter()
        code, _, body = call(self.app, "/slow")
        elapsed = time.perf_counter() - started
        self.assertEqual(code, 200)
        self.assertLess(elapsed, 0.5)
        self.assertIn(by_id("slow").sentinel, body.decode("utf-8"))

    def test_large_dom_default_is_small(self) -> None:
        _, _, body = call(self.app, "/large-dom")
        html = body.decode("utf-8")
        self.assertIn(by_id("large_dom").sentinel, html)
        self.assertLess(html.count('class="n"'), 50)

    def test_large_dom_nodes_from_query(self) -> None:
        _, _, body = call(self.app, "/large-dom", query="nodes=12")
        self.assertEqual(body.decode("utf-8").count('class="n"'), 12)


if __name__ == "__main__":
    unittest.main()
