"""Чекер M27: локальный релей прокси для браузерных ступеней (без сети наружу).

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m27_proxy_relay.py      ->  печатает `ok`

Браузер подменяется (sys.modules), релей настоящий: чекер ходит в него
сокетом по 127.0.0.1, а вместо внешнего прокси поднимает свой поддельный
upstream на 127.0.0.1 и сверяет, что релей ему прислал. Каждый отказ
сверяется с ПРИЧИНОЙ (текст err), пароль ищется во всём, что видно наружу.
"""
import base64
import contextlib
import importlib.util
import io
import json
import os
import re
import socket
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gateway import oneshot  # noqa: E402
from tests.probe_m9_transport import _probe_payload  # noqa: E402

URL = "https://example.invalid/"
SECRET = "s3cr@t"
ENC = "s3cr%40t"
BASIC = "Proxy-Authorization: Basic " + base64.b64encode(f"user1:{SECRET}".encode()).decode()
RELAY_SERVER = re.compile(r"^http://127\.0\.0\.1:(\d+)$")
FAILURES = []


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: ожидалось {expected!r}, получено {actual!r}")


def load_probe():
    path = ROOT / "bench" / "providers" / "docker" / "probe.py"
    spec = importlib.util.spec_from_file_location("m27_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROBE = load_probe()


# --- one-shot ---------------------------------------------------------------

def invoke(args, environ):
    calls = []

    def spawn(command, env=None, **kwargs):
        calls.append((list(command), dict(env)))
        proc = Mock(pid=4242, returncode=0)
        proc.communicate.return_value = (json.dumps(_probe_payload(
            status=403, final_url=URL, html="<html></html>", text="")), "")
        return proc

    base = {k: v for k, v in os.environ.items() if k not in ("ABG_PROXY", "ABG_EGRESS_PROXY")}
    out, err = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, {**base, **environ}, clear=True), patch.object(
            oneshot.subprocess, "Popen", side_effect=spawn), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = oneshot.main(args)
    return rc, out.getvalue(), err.getvalue(), calls


def oneshot_side():
    for scheme in ("socks5", "socks5h", "SOCKS5"):
        rc, out, err, calls = invoke([URL], {"ABG_PROXY": f"{scheme}://user1:{ENC}@s.invalid:1080"})
        check(f"{scheme} с паролем и браузерами: rc/stderr", (rc, err), (1, ""))
        try:
            routes = [(a["provider"], a["egress_profile"]) for a in json.loads(out)["attempts"]]
        except (ValueError, KeyError, TypeError):
            routes = out[:200]
        check(f"{scheme} с паролем: все три ступени через прокси", routes,
              [("curl_cffi", "explicit"), ("patchright", "explicit"), ("scrapling", "explicit")])
        check(f"{scheme} с паролем: ABG_PROXY ступеней", [env.get("ABG_PROXY") for _, env in calls],
              [f"socks5h://user1:{ENC}@s.invalid:1080"] * 3)
        blob = out + err + json.dumps([c for c, _ in calls])
        if SECRET in blob or ENC in blob:
            FAILURES.append(f"{scheme} с паролем: пароль в stdout/stderr/argv")
    rc, out, err, calls = invoke([URL, "--proxy", f"socks5://user1:{ENC}@s.invalid:1080"], {})
    check("--proxy с паролем по-прежнему отказ", (rc, out, err, len(calls)),
          (2, "", '{"error": "proxy_credentials_in_argv"}\n', 0))


# --- поддельный upstream ----------------------------------------------------

class Upstream:
    """Один слушающий сокет на 127.0.0.1; handler(conn, log) отвечает за протокол."""

    def __init__(self, handler):
        self.handler = handler
        self.log = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        conn.settimeout(5)
        try:
            self.handler(conn, self.log)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()


def read_head_rest(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


def read_head(conn):
    return read_head_rest(conn)[0]


def recv_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


def http_upstream(connect_status=200):
    def handler(conn, log):
        head, rest = read_head_rest(conn)
        log.append(head)
        length = [int(line.split(":", 1)[1]) for line in head.split("\r\n")
                  if line.lower().startswith("content-length:")]
        if length:
            log.append(("body", rest + recv_exact(conn, length[0] - len(rest))))
        if head.startswith("CONNECT "):
            if connect_status != 200:
                conn.sendall(f"HTTP/1.1 {connect_status} No\r\nProxy-Authenticate: Basic "
                             f"realm=\"x\"\r\nContent-Length: 0\r\n\r\n".encode())
                return
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            conn.sendall(recv_exact(conn, 4).upper())
        else:
            if connect_status != 200:
                conn.sendall(b"HTTP/1.1 407 No\r\nProxy-Authenticate: Basic realm=\"x\"\r\n"
                             b"Content-Length: 0\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
    return Upstream(handler)


def socks_upstream(auth_ok=True):
    def handler(conn, log):
        version, count = recv_exact(conn, 2)
        methods = recv_exact(conn, count)
        log.append(("methods", version, methods))
        if 2 not in methods:
            conn.sendall(b"\x05\xff")
            return
        conn.sendall(b"\x05\x02")
        ver, ulen = recv_exact(conn, 2)
        user = recv_exact(conn, ulen)
        plen = recv_exact(conn, 1)[0]
        password = recv_exact(conn, plen)
        log.append(("auth", ver, user, password))
        conn.sendall(b"\x01\x00" if auth_ok else b"\x01\x01")
        if not auth_ok:
            return
        head = recv_exact(conn, 4)
        if head[3] == 3:
            name = recv_exact(conn, recv_exact(conn, 1)[0])
        else:
            name = recv_exact(conn, {1: 4, 4: 16}.get(head[3], 0))
        port = int.from_bytes(recv_exact(conn, 2), "big")
        log.append(("connect", head[:4], name, port))
        conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        first = recv_exact(conn, 4)
        if first == b"ping":
            conn.sendall(b"PING")
            return
        log.append(("head", (first.decode("latin-1") + read_head(conn)).split("\r\n")))
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
    return Upstream(handler)


# --- браузер-подделка -------------------------------------------------------

def browser_modules():
    runtime = Mock()
    sync_playwright = Mock()
    sync_playwright.return_value.start.return_value = runtime
    session = MagicMock()
    modules = {
        "patchright.sync_api": types.SimpleNamespace(sync_playwright=sync_playwright),
        "scrapling.fetchers": types.SimpleNamespace(StealthySession=session),
    }
    return modules, runtime, session


def launched_proxy(adapter_name, runtime, session):
    if adapter_name == "patchright":
        return runtime.chromium.launch.call_args.kwargs.get("proxy")
    return session.call_args.kwargs.get("proxy")


def relay_port(label, proxy, upstream_port):
    keys = sorted(proxy) if isinstance(proxy, dict) else proxy
    check(f"{label}: Chromium получает только server", keys, ["server"])
    match = RELAY_SERVER.match(proxy.get("server", "")) if isinstance(proxy, dict) else None
    if match is None or int(match.group(1)) == upstream_port:
        FAILURES.append(f"{label}: server не релей на 127.0.0.1: {proxy!r}")
        return None
    return int(match.group(1))


def talk(port, payload, expect):
    with socket.create_connection(("127.0.0.1", port), 5) as conn:
        conn.settimeout(5)
        conn.sendall(payload)
        data = b""
        while len(data) < len(expect):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        return data


def threads_settle(baseline):
    deadline = time.monotonic() + 5
    while threading.active_count() > baseline and time.monotonic() < deadline:
        time.sleep(0.05)
    return threading.active_count()


def relay_side():
    for adapter_name in ("patchright", "scrapling"):
        up = http_upstream()
        baseline = threading.active_count()
        modules, runtime, session = browser_modules()
        proxy = f"http://user1:{ENC}@127.0.0.1:{up.port}"
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"ABG_PROXY": proxy}):
            adapter = PROBE.make_adapter(adapter_name)
            adapter.start()
            label = f"{adapter_name} http"
            port = relay_port(label, launched_proxy(adapter_name, runtime, session), up.port)
            if adapter_name == "patchright":
                check(f"{label}: WebRTC флаг", runtime.chromium.launch.call_args.kwargs.get("args"),
                      ["--webrtc-ip-handling-policy=disable_non_proxied_udp"])
                page = runtime.chromium.launch.return_value.new_page.return_value
                check(f"{label}: без CDP-обработчика", (page.context.new_cdp_session.called,
                                                        page.route.called), (False, False))
            else:
                check(f"{label}: block_webrtc", session.call_args.kwargs.get("block_webrtc"), True)
            if port is not None:
                got = talk(port, b"CONNECT a.example:443 HTTP/1.1\r\nHost: a.example:443\r\n\r\nping",
                           b"HTTP/1.1 200 Connection established\r\n\r\nPING")
                check(f"{label}: CONNECT-туннель", (got.split(b"\r\n", 1)[0][:12], got[-4:]),
                      (b"HTTP/1.1 200", b"PING"))
                heads = [e for e in up.log if isinstance(e, str)]
                head = heads[-1] if heads else ""
                lines = head.split("\r\n")
                check(f"{label}: CONNECT наверх", (lines[0], BASIC in lines),
                      ("CONNECT a.example:443 HTTP/1.1", True))
                got = talk(port, b"GET http://b.example/x?y=1 HTTP/1.1\r\nHost: b.example\r\n"
                                 b"Proxy-Connection: keep-alive\r\n"
                                 b"Proxy-Authorization: Basic Zm9vOmJhcg==\r\n\r\n",
                           b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                check(f"{label}: plain HTTP ответ", got, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                heads = [e for e in up.log if isinstance(e, str)]
                head = heads[-1] if heads else ""
                lines = [line.lower() for line in head.split("\r\n")]
                check(f"{label}: plain HTTP наверх", (
                    head.split("\r\n")[0], BASIC in head.split("\r\n"),
                    "proxy-authorization: basic zm9vomjhcg==" in lines,
                    any(line.startswith("proxy-connection:") for line in lines),
                    "connection: close" in lines),
                    ("GET http://b.example/x?y=1 HTTP/1.1", True, False, False, True))
                got = talk(port, b"POST http://b.example/form HTTP/1.1\r\nHost: b.example\r\n"
                                 b"Content-Length: 9\r\n\r\nfield=abc",
                           b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                bodies = [e[1] for e in up.log if isinstance(e, tuple) and e[0] == "body"]
                check(f"{label}: тело POST дошло наверх", (got[-2:], bodies[-1:]),
                      (b"hi", [b"field=abc"]))
            adapter.close()
            if port is not None:
                try:
                    socket.create_connection(("127.0.0.1", port), 1).close()
                    FAILURES.append(f"{label}: порт релея принимает после close")
                except OSError:
                    pass
            check(f"{label}: потоки релея завершились", threads_settle(baseline) <= baseline, True)
        up.close()

    for scheme in ("socks5", "socks5h"):
        up = socks_upstream()
        modules, runtime, session = browser_modules()
        with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"ABG_PROXY": f"{scheme}://user1:{ENC}@127.0.0.1:{up.port}"}):
            adapter = PROBE.make_adapter("patchright")
            adapter.start()
            label = f"patchright {scheme}"
            port = relay_port(label, launched_proxy("patchright", runtime, session), up.port)
            if port is not None:
                got = talk(port, b"CONNECT a.example:443 HTTP/1.1\r\nHost: a.example:443\r\n\r\nping",
                           b"HTTP/1.1 200 Connection established\r\n\r\nPING")
                check(f"{label}: CONNECT через SOCKS5", (got.split(b"\r\n", 1)[0][:12], got[-4:]),
                      (b"HTTP/1.1 200", b"PING"))
                auth = [e for e in up.log if e[0] == "auth"]
                connect = [e for e in up.log if e[0] == "connect"]
                check(f"{label}: RFC 1929", auth[:1], [("auth", 1, b"user1", SECRET.encode())])
                check(f"{label}: имя резолвит прокси", connect[:1],
                      [("connect", b"\x05\x01\x00\x03", b"a.example", 443)])
                got = talk(port, b"GET http://b.example:8000/p?q=1 HTTP/1.1\r\nHost: b.example:8000\r\n"
                                 b"Proxy-Connection: keep-alive\r\n\r\n",
                           b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                check(f"{label}: plain HTTP ответ", got, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
                connect = [e for e in up.log if e[0] == "connect"]
                check(f"{label}: plain HTTP через SOCKS5", connect[-1:],
                      [("connect", b"\x05\x01\x00\x03", b"b.example", 8000)])
                heads = [e[1] for e in up.log if e[0] == "head"]
                lines = [line.lower() for line in heads[-1]] if heads else []
                check(f"{label}: запрос в origin-form без Proxy-*", (
                    heads[-1][0] if heads else None,
                    any(line.startswith("proxy-") for line in lines), "connection: close" in lines),
                    ("GET /p?q=1 HTTP/1.1", False, True))
            adapter.close()
        up.close()

    no_creds = (("http://127.0.0.1:9", {"server": "http://127.0.0.1:9"}),
                ("socks5h://127.0.0.1:9", {"server": "socks5://127.0.0.1:9"}))
    for proxy, expected in no_creds:
        for adapter_name in ("patchright", "scrapling"):
            modules, runtime, session = browser_modules()
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {"ABG_PROXY": proxy}):
                adapter = PROBE.make_adapter(adapter_name)
                adapter.start()
                check(f"{adapter_name} без кредов {proxy}: прокси как прежде",
                      launched_proxy(adapter_name, runtime, session), expected)
                adapter.close()


def failing_probe(proxy, connect):
    """run_probe с patchright, чей goto ходит через релей и падает, как Chromium."""
    modules, runtime, session = browser_modules()
    page = runtime.chromium.launch.return_value.new_page.return_value

    def goto(url, **kwargs):
        server = runtime.chromium.launch.call_args.kwargs["proxy"]["server"]
        port = int(server.rsplit(":", 1)[1])
        talk(port, connect, b"HTTP/1.1 502")
        raise RuntimeError("net::ERR_TUNNEL_CONNECTION_FAILED at " + url)

    page.goto.side_effect = goto
    with patch.dict(sys.modules, modules), patch.dict(os.environ, {"ABG_PROXY": proxy}):
        return PROBE.run_probe("patchright", URL, None, mode="cold", content_only=True,
                               include_content=True)


def failure_side():
    connect = b"CONNECT a.example:443 HTTP/1.1\r\nHost: a.example:443\r\n\r\n"
    up = http_upstream(connect_status=407)
    proxy = f"http://user1:{ENC}@127.0.0.1:{up.port}"
    modules, runtime, session = browser_modules()
    with patch.dict(sys.modules, modules), patch.dict(os.environ, {"ABG_PROXY": proxy}):
        adapter = PROBE.make_adapter("patchright")
        adapter.start()
        port = int(runtime.chromium.launch.call_args.kwargs["proxy"]["server"].rsplit(":", 1)[1])
        got = talk(port, connect, b"HTTP/1.1 502")
        check("407 наверху: Chromium получает 502", got[:12], b"HTTP/1.1 502")
        got = talk(port, b"GET http://b.example/ HTTP/1.1\r\nHost: b.example\r\n\r\n", b"HTTP/1.1 502")
        check("407 на plain HTTP: Chromium получает 502, а не 407", got[:12], b"HTTP/1.1 502")
        adapter.close()
    payload = failing_probe(proxy, connect)
    check("407: причина в err", payload.get("err"),
          "ProxyRelayError: upstream proxy rejected credentials (HTTP 407)")
    up.close()

    up = socks_upstream(auth_ok=False)
    payload = failing_probe(f"socks5h://user1:{ENC}@127.0.0.1:{up.port}", connect)
    check("SOCKS5 auth: причина в err", payload.get("err"),
          "ProxyRelayError: upstream proxy rejected credentials (SOCKS5)")
    up.close()

    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    payload = failing_probe(f"http://user1:{ENC}@127.0.0.1:{dead_port}", connect)
    check("прокси недоступен: причина в err", payload.get("err"),
          "ProxyRelayError: upstream proxy unreachable")

    up = Upstream(lambda conn, log: conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n"))
    payload = failing_probe(f"https://user1:{ENC}@127.0.0.1:{up.port}", connect)
    check("https-прокси без TLS: причина в err", payload.get("err"),
          "ProxyRelayError: upstream proxy TLS failed")
    up.close()

    up = http_upstream()
    payload = failing_probe(f"http://user1:{ENC}@127.0.0.1:{up.port}", connect)
    check("туннель открыт, Chromium упал сам: err Chromium", (payload.get("err") or "")[:40],
          "RuntimeError: net::ERR_TUNNEL_CONNECTION")
    up.close()

    for label, value in (("payload", json.dumps(payload)),):
        if SECRET in value or ENC in value:
            FAILURES.append(f"{label}: пароль прокси")


def main():
    for part in (oneshot_side, relay_side, failure_side):
        try:
            part()
        except Exception as exc:  # A crash is a failed check, not a pass.
            FAILURES.append(f"{part.__name__}: исключение {type(exc).__name__}: {exc}")
    if FAILURES:
        print("\n".join(FAILURES))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
