"""Deterministic WSGI stand A. No sockets."""

from __future__ import annotations

import gzip
import importlib
import importlib.util
import secrets
import time
from collections.abc import Callable, Iterable
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs

from bench.scenarios import by_id

WSGIApp = Callable[..., Iterable[bytes]]

_HTML = "text/html; charset=utf-8"
_JSON = "application/json; charset=utf-8"


def _brotli_mod():
    spec = importlib.util.find_spec("brotli")
    if spec is None:
        return None
    return importlib.import_module("brotli")


def _header_codings(raw: str) -> set[str]:
    out: set[str] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(";")
        coding = tokens[0].strip().lower()
        if not coding:
            continue
        q = 1.0
        for token in tokens[1:]:
            key, _, value = token.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 1.0
        if q > 0:
            out.add(coding)
    return out


def _int_param(qs: dict[str, list[str]], name: str, default: int) -> int:
    values = qs.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError:
        return default


def _float_param(qs: dict[str, list[str]], name: str, default: float) -> float:
    values = qs.get(name)
    if not values:
        return default
    try:
        return float(values[0])
    except ValueError:
        return default


def _response(
    status: str, body: bytes, extra: list[tuple[str, str]] | None = None, content_type: str = _HTML
) -> tuple[str, list[tuple[str, str]], bytes]:
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
    ]
    if extra:
        headers.extend(extra)
    return status, headers, body


def _ok(
    body: bytes, extra: list[tuple[str, str]] | None = None, content_type: str = _HTML
) -> tuple[str, list[tuple[str, str]], bytes]:
    return _response("200 OK", body, extra, content_type)


def _redirect(location: str) -> tuple[str, list[tuple[str, str]], bytes]:
    body = b""
    return _response("302 Found", body, [("Location", location)])


def _page(inner: str) -> bytes:
    return f"<!DOCTYPE html><html><body>{inner}</body></html>".encode("utf-8")


_STATIC_HTML = _page(f"<p>{by_id('static').sentinel}</p>")
_REDIRECT_FINAL_HTML = _page(f"<p>{by_id('redirect').sentinel}</p>")
_COMPRESSION_HTML = _page(f"<p>{by_id('compression').sentinel}</p>")
_SLOW_HTML = _page(f"<p>{by_id('slow').sentinel}</p>")
_SESSION_START_HTML = _page("<p>session started</p>")
_SESSION_CHECK_HTML = _page(f"<p>{by_id('session').sentinel}</p>")
_ERROR_HTML = _page("<p>deterministic error, no sentinel</p>")
_ERROR_EXPLAIN_HTML = _page(
    "<p>error endpoints omit the sentinel. "
    f"sentinel={by_id('errors').sentinel}</p>"
)
_IFRAME_PARENT_HTML = (
    "<!DOCTYPE html><html><body>"
    '<iframe src="/iframe/child"></iframe>'
    "</body></html>"
).encode("utf-8")
_IFRAME_CHILD_HTML = _page(f"<p>{by_id('iframe').sentinel}</p>")
_SPA_SHELL_HTML = """<!DOCTYPE html>
<html><body>
<div id="root">spa-shell</div>
<script>
fetch('/spa/data').then(function(r){return r.json();}).then(function(d){
  document.getElementById('root').textContent = d.sentinel;
});
</script>
</body></html>
""".encode("utf-8")
_SPA_DATA = f'{{"sentinel":"{by_id("spa").sentinel}"}}'.encode("utf-8")
_JS_HTML = """<!DOCTYPE html>
<html><body>
<div id="root">js-shell</div>
<script>
document.getElementById('root').textContent = 'ABG_TEST_' + 'JS_OK';
</script>
</body></html>
""".encode("utf-8")
_SHADOW_HTML = """<!DOCTYPE html>
<html><body>
<div id="host"></div>
<script>
const host = document.getElementById('host');
const root = host.attachShadow({mode: "closed"});
root.textContent = 'ABG_TEST_' + 'SHADOW_OK';
</script>
</body></html>
""".encode("utf-8")
_BROKEN_JS_HTML = """<!DOCTYPE html>
<html><body>
<div id="root">loaded</div>
<script>
throw new Error('broken');
document.getElementById('root').textContent = 'ABG_TEST_' + 'BROKEN_JS_OK';
</script>
</body></html>
""".encode("utf-8")


def build_app(*, session_store: dict | None = None) -> WSGIApp:
    store = session_store if session_store is not None else {}

    def app(environ, start_response):
        path = environ.get("PATH_INFO") or "/"
        qs = parse_qs(environ.get("QUERY_STRING") or "", keep_blank_values=True)
        status, headers, body = _dispatch(path, qs, environ, store)
        start_response(status, headers)
        return [body]

    return app


def _dispatch(
    path: str,
    qs: dict[str, list[str]],
    environ: dict,
    store: dict,
) -> tuple[str, list[tuple[str, str]], bytes]:
    if path == "/static":
        return _ok(_STATIC_HTML)
    if path == "/redirect":
        return _redirect("/redirect/hop1")
    if path == "/redirect/hop1":
        return _redirect("/redirect/hop2")
    if path == "/redirect/hop2":
        return _redirect("/redirect/final")
    if path == "/redirect/final":
        return _ok(_REDIRECT_FINAL_HTML)
    if path == "/compression":
        return _compression(environ)
    if path == "/js":
        return _ok(_JS_HTML)
    if path == "/spa":
        return _ok(_SPA_SHELL_HTML)
    if path == "/spa/data":
        return _ok(_SPA_DATA, content_type=_JSON)
    if path == "/iframe":
        return _ok(_IFRAME_PARENT_HTML)
    if path == "/iframe/child":
        return _ok(_IFRAME_CHILD_HTML)
    if path == "/shadow":
        return _ok(_SHADOW_HTML)
    if path == "/session/start":
        token = secrets.token_hex(16)
        store[token] = True
        cookie = f"abg_session={token}; Path=/"
        return _ok(_SESSION_START_HTML, [("Set-Cookie", cookie)])
    if path == "/session/check":
        return _session_check(environ, store)
    if path in ("/errors", "/errors/403"):
        return _response("403 Forbidden", _ERROR_HTML)
    if path == "/errors/429":
        return _response("429 Too Many Requests", _ERROR_HTML)
    if path == "/errors/503":
        return _response("503 Service Unavailable", _ERROR_HTML)
    if path == "/errors/explain":
        return _ok(_ERROR_EXPLAIN_HTML)
    if path == "/slow":
        delay = _float_param(qs, "delay", 0.0)
        if delay > 0:
            time.sleep(delay)
        return _ok(_SLOW_HTML)
    if path == "/broken-js":
        return _ok(_BROKEN_JS_HTML)
    if path == "/large-dom":
        n = max(0, _int_param(qs, "nodes", 8))
        nodes = "".join(f'<div class="n" id="n{i}">{i}</div>' for i in range(n))
        html = (
            "<!DOCTYPE html><html><body>"
            f"{nodes}<p>{by_id('large_dom').sentinel}</p>"
            "</body></html>"
        )
        return _ok(html.encode("utf-8"))
    return _response("404 Not Found", _page("<p>not found</p>"))


def _compression(environ: dict) -> tuple[str, list[tuple[str, str]], bytes]:
    body = _COMPRESSION_HTML
    encodings = _header_codings(environ.get("HTTP_ACCEPT_ENCODING", ""))
    extra = [("Vary", "Accept-Encoding")]
    brotli = _brotli_mod()
    if "br" in encodings and brotli is not None:
        compressed = brotli.compress(body)
        extra.append(("Content-Encoding", "br"))
        return _ok(compressed, extra)
    if "gzip" in encodings:
        compressed = gzip.compress(body)
        extra.append(("Content-Encoding", "gzip"))
        return _ok(compressed, extra)
    return _ok(body, extra)


def _session_check(environ: dict, store: dict) -> tuple[str, list[tuple[str, str]], bytes]:
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
    except CookieError:
        cookies = SimpleCookie()
    morsel = cookies.get("abg_session")
    token = morsel.value if morsel is not None else ""
    if token and store.get(token):
        return _ok(_SESSION_CHECK_HTML)
    return _response("401 Unauthorized", _page("<p>unauthorized</p>"))
