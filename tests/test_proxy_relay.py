"""Локальный релей прокси: настоящий слушатель на 127.0.0.1 против поддельного
внешнего прокси в том же процессе. Без сети наружу и без браузера.

Каждый отказ сверяется с причиной (дословный ответ клиенту или `fatal`) и
парным входом без нарушения, который проходит.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "bench" / "providers" / "docker" / "probe.py"

URL = "https://target.invalid/"
SECRET = "s3cr@t"
ENC = "s3cr%40t"
TOKEN = base64.b64encode(f"user1:{SECRET}".encode()).decode()
BASIC_LINE = f"Proxy-Authorization: Basic {TOKEN}"
RELAY_SERVER = re.compile(r"^http://127\.0\.0\.1:(\d+)$")
CONNECT = b"CONNECT a.example:443 HTTP/1.1\r\nHost: a.example:443\r\n\r\n"
ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"
BAD_GATEWAY = b"HTTP/1.1 502"
BAD_REQUEST = b"HTTP/1.1 400"
GATEWAY_RESPONSE = (b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n"
                    b"Connection: close\r\n\r\n")
INTERIM_100 = b"HTTP/1.1 100 Continue\r\n\r\n"
INTERIM_103 = b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload\r\n\r\n"
PLAIN_REQUEST = b"GET http://b.example/x HTTP/1.1\r\nHost: b.example\r\n\r\n"
PLAIN_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi"
# Границы заданы литералами, а не ссылкой на константу пробы: иначе удвоение
# лимита молча масштабировало бы и тесты. Значение констант зафиксировано
# отдельным тестом ModuleShapeTests.
HEAD_LIMIT = 64 * 1024
RESPONSE_LIMIT = 256 * 1024
REJECTED_HTTP = "upstream proxy rejected credentials (HTTP 407)"
REJECTED_SOCKS = "upstream proxy rejected credentials (SOCKS5)"
UNREACHABLE = "upstream proxy unreachable"
TLS_FAILED = "upstream proxy TLS failed"


def load_probe():
    spec = importlib.util.spec_from_file_location("container_probe_relay", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Upstream:
    """Поддельный внешний прокси: один слушатель на 127.0.0.1, протокол ведёт handler."""

    def __init__(self, handler):
        self.handler = handler
        self.log = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

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


def recv_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


def read_head_rest(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head.decode("latin-1"), rest


def read_eof(conn):
    data = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            return data
        data += chunk


def http_upstream(connect_status=200, plain_status=200, interim=None, connect_interim=None):
    """Поддельный http-прокси: пишет заголовки каждого запроса в log."""
    responses = {
        200: b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi",
        403: b"HTTP/1.1 403 Forbidden\r\nContent-Length: 6\r\n\r\ndenied",
        407: (b"HTTP/1.1 407 Proxy Authentication Required\r\n"
              b"Proxy-Authenticate: Basic realm=\"x\"\r\nContent-Length: 0\r\n\r\n"),
    }

    def handler(conn, log):
        head, rest = read_head_rest(conn)
        log.append(head)
        if head.startswith("CONNECT "):
            if connect_interim:
                conn.sendall(connect_interim)
            if connect_status != 200:
                conn.sendall(responses[connect_status])
                return
            conn.sendall(ESTABLISHED)
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                conn.sendall(chunk.upper())
            return
        lengths = [int(line.split(":", 1)[1]) for line in head.split("\r\n")
                   if line.lower().startswith("content-length:")]
        if lengths:
            log.append(("body", rest + recv_exact(conn, max(0, lengths[0] - len(rest)))))
        if interim:
            conn.sendall(interim)
        conn.sendall(responses[plain_status])

    return Upstream(handler)


def silent_upstream():
    """Поддельный прокси, который принимает TCP и закрывает соединение без ответа."""
    return Upstream(lambda conn, log: log.append("accepted"))


def reset_upstream():
    """Поддельный прокси, который читает запрос и сбрасывает соединение (RST)."""

    def handler(conn, log):
        read_head_rest(conn)  # запрос прочитан: sendall у релея уже прошёл
        log.append("reset")
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    return Upstream(handler)


class CannedUpstream:
    """Подмена сокета внешнего прокси: recv отдаёт заранее нарезанные порции.

    Нужна там, где исход иначе зависел бы от склейки сегментов TCP: порядок и
    состав порций заданы тестом, а не ядром.
    """

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = b""
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        return self.chunks.pop(0) if self.chunks else b""

    def settimeout(self, value):
        pass

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


def make_certificates(directory, san="IP:127.0.0.1", cn="127.0.0.1", leaf="leaf"):
    """CA (если ещё нет) и подписанный им листовой сертификат через openssl.

    Ключи живут только во временном каталоге, в репозиторий не попадают.
    Python 3.14 включает VERIFY_X509_STRICT: CA нужен keyUsage, листу —
    authorityKeyIdentifier. Возвращает None, если openssl в образе нет.
    """
    if shutil.which("openssl") is None:
        return None

    def run(*args):
        proc = subprocess.run(("openssl", *args), cwd=directory, capture_output=True)
        assert proc.returncode == 0, (args[:2], proc.returncode,
                                      proc.stderr.decode(errors="replace")[:400])

    if not (directory / "ca.pem").exists():
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key",
            "-out", "ca.pem", "-days", "2", "-subj", "/CN=relay-test-ca",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    (directory / f"{leaf}.cnf").write_text(
        f"subjectAltName={san}\n"
        "authorityKeyIdentifier=keyid,issuer\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n", encoding="utf-8")
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{leaf}.key",
        "-out", f"{leaf}.csr", "-subj", f"/CN={cn}")
    run("x509", "-req", "-in", f"{leaf}.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
        "-CAcreateserial", "-out", f"{leaf}.crt", "-days", "2", "-extfile", f"{leaf}.cnf")
    return {"ca": str(directory / "ca.pem"), "cert": str(directory / f"{leaf}.crt"),
            "key": str(directory / f"{leaf}.key")}


class TlsUpstream:
    """Поддельный https-прокси на настоящем TLS: handler(tls_conn, log)."""

    def __init__(self, handler, certs):
        self.handler = handler
        self.log = []
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(certs["cert"], certs["key"])
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        conn.settimeout(10)
        try:
            tls = self.context.wrap_socket(conn, server_side=True)
        except (OSError, ValueError):
            conn.close()
            return
        try:
            self.handler(tls, self.log)
        except (OSError, ValueError):
            pass
        finally:
            tls.close()

    def close(self):
        self.sock.close()


def socks_upstream(auth_ok=True, offers_method=True, reply=0x00,
                   bound=b"\x01\x7f\x00\x00\x01\x00\x00"):
    """Поддельный SOCKS5-прокси: пишет приветствие, RFC 1929 и CONNECT в log."""

    def handler(conn, log):
        version, count = recv_exact(conn, 2)
        methods = recv_exact(conn, count)
        log.append(("methods", version, methods))
        if not offers_method or 2 not in methods:
            conn.sendall(b"\x05\xff")
            return
        conn.sendall(b"\x05\x02")
        auth_version, ulen = recv_exact(conn, 2)
        user = recv_exact(conn, ulen)
        plen = recv_exact(conn, 1)[0]
        password = recv_exact(conn, plen)
        log.append(("auth", auth_version, user, password))
        conn.sendall(b"\x01\x00" if auth_ok else b"\x01\x01")
        if not auth_ok:
            return
        head = recv_exact(conn, 4)
        if head[3] == 0x03:
            name = recv_exact(conn, recv_exact(conn, 1)[0])
        else:
            name = recv_exact(conn, {0x01: 4, 0x04: 16}.get(head[3], 0))
        port = int.from_bytes(recv_exact(conn, 2), "big")
        log.append(("connect", head, name, port))
        conn.sendall(b"\x05" + bytes((reply,)) + b"\x00" + bound)
        if reply != 0x00:
            return
        first = recv_exact(conn, 4)
        if first == b"ping":
            conn.sendall(b"PING")
            return
        log.append(("head", (first.decode("latin-1") + read_head_rest(conn)[0]).split("\r\n")))
        conn.sendall(PLAIN_OK)

    return Upstream(handler)


def dead_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RelayCase(unittest.TestCase):
    """Общая оснастка: релей настоящий, браузер и внешний прокси поддельные."""

    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe()

    def proxy_url(self, scheme="http", host="127.0.0.1", port=9, userinfo=f"user1:{ENC}"):
        at = f"{userinfo}@" if userinfo else ""
        return f"{scheme}://{at}{host}:{port}"

    def start_relay(self, upstream_url):
        relay = self.probe._ProxyRelay(upstream_url)
        server = relay.start()
        self.addCleanup(relay.close)
        match = RELAY_SERVER.match(server)
        assert match is not None, server
        return relay, int(match.group(1))

    def upstream(self, factory, scheme="http", **kwargs):
        up = factory(**kwargs)
        self.addCleanup(up.close)
        return up, self.proxy_url(scheme=scheme, port=up.port)

    def talk(self, port, payload, expect):
        """Ответ из exactly len(expect) байт: туннель релей сам не закрывает."""
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

    def talk_eof(self, port, payload):
        """Ответ до закрытия: plain HTTP релей закрывает сразу после ответа."""
        with socket.create_connection(("127.0.0.1", port), 5) as conn:
            conn.settimeout(5)
            conn.sendall(payload)
            return read_eof(conn)

    def browser_modules(self):
        runtime = Mock()
        sync_playwright = Mock()
        sync_playwright.return_value.start.return_value = runtime
        session = MagicMock()
        modules = {
            "playwright.sync_api": types.SimpleNamespace(sync_playwright=sync_playwright),
            "patchright.sync_api": types.SimpleNamespace(sync_playwright=sync_playwright),
            "scrapling.fetchers": types.SimpleNamespace(StealthySession=session),
        }
        return modules, runtime, session

    def launched_proxy(self, adapter_name, runtime, session):
        if adapter_name == "patchright":
            return runtime.chromium.launch.call_args.kwargs.get("proxy")
        return session.call_args.kwargs.get("proxy")


class RelayHttpUpstreamTests(RelayCase):
    """Протокол наверх для http/https-прокси."""

    def test_connect_tunnel_adds_credentials_and_keeps_pipelined_bytes(self):
        up, proxy = self.upstream(http_upstream)
        relay, port = self.start_relay(proxy)
        got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
        self.assertEqual(got, ESTABLISHED + b"PING")
        self.assertEqual(up.log[0].split("\r\n"),
                         ["CONNECT a.example:443 HTTP/1.1", "Host: a.example:443", BASIC_LINE])
        self.assertIsNone(relay.fatal)

    def test_plain_http_request_loses_client_proxy_headers_and_gains_close(self):
        up, proxy = self.upstream(http_upstream)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"GET http://b.example/x?y=1 HTTP/1.1\r\nHost: b.example\r\n"
                                  b"Proxy-Connection: keep-alive\r\n"
                                  b"Proxy-Authorization: Basic Zm9vOmJhcg==\r\n"
                                  b"Accept: */*\r\n\r\n")
        self.assertEqual(got, PLAIN_OK)
        lines = up.log[0].split("\r\n")
        self.assertEqual(lines[0], "GET http://b.example/x?y=1 HTTP/1.1")
        self.assertEqual([line for line in lines
                          if line.lower().startswith("proxy-authorization:")], [BASIC_LINE])
        lowered = [line.lower() for line in lines]
        self.assertEqual([line for line in lowered if line.startswith("connection:")],
                         ["connection: close"])
        self.assertIn("Host: b.example", lines)
        self.assertIn("Accept: */*", lines)
        self.assertFalse(any(line.startswith(("proxy-connection:", "authorization:"))
                             for line in lowered), lines)
        self.assertNotIn(SECRET, up.log[0])
        self.assertIsNone(relay.fatal)

    def test_body_read_with_the_head_reaches_upstream(self):
        up, proxy = self.upstream(http_upstream)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"POST http://b.example/form HTTP/1.1\r\nHost: b.example\r\n"
                                  b"Content-Length: 9\r\n\r\nfield=abc")
        self.assertEqual(got, PLAIN_OK)
        self.assertEqual([entry[1] for entry in up.log if isinstance(entry, tuple)],
                         [b"field=abc"])

    def test_body_sent_after_the_head_reaches_upstream(self):
        up, proxy = self.upstream(http_upstream)
        relay, port = self.start_relay(proxy)
        with socket.create_connection(("127.0.0.1", port), 5) as conn:
            conn.settimeout(5)
            conn.sendall(b"POST http://b.example/form HTTP/1.1\r\nHost: b.example\r\n"
                         b"Content-Length: 9\r\n\r\n")
            time.sleep(0.05)
            conn.sendall(b"field=abc")
            self.assertEqual(read_eof(conn), PLAIN_OK)
        self.assertEqual([entry[1] for entry in up.log if isinstance(entry, tuple)],
                         [b"field=abc"])

    def test_upstream_407_on_connect_is_502_with_reason(self):
        up, proxy = self.upstream(http_upstream, connect_status=407)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertNotIn(b"407", got)
        self.assertEqual(relay.fatal, REJECTED_HTTP)

    def test_upstream_407_on_plain_http_is_502_with_reason(self):
        up, proxy = self.upstream(http_upstream, plain_status=407)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"GET http://b.example/ HTTP/1.1\r\nHost: b.example\r\n\r\n")
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertNotIn(b"407", got)
        self.assertNotIn(b"Proxy-Authenticate", got)
        self.assertEqual(relay.fatal, REJECTED_HTTP)

    def test_target_refusal_on_connect_is_502_without_reason(self):
        up, proxy = self.upstream(http_upstream, connect_status=403)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertIsNone(relay.fatal)

    def test_target_status_passes_through_verbatim(self):
        up, proxy = self.upstream(http_upstream, plain_status=403)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"GET http://b.example/deny HTTP/1.1\r\nHost: b.example\r\n\r\n")
        self.assertEqual(got, b"HTTP/1.1 403 Forbidden\r\nContent-Length: 6\r\n\r\ndenied")
        self.assertIsNone(relay.fatal)

    def test_unreachable_proxy_is_502_with_reason(self):
        relay, port = self.start_relay(self.proxy_url(port=dead_port()))
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertEqual(relay.fatal, UNREACHABLE)

    def test_tls_handshake_failure_is_502_with_reason(self):
        # Слушатель отвечает текстом, поэтому рукопожатие TLS с прокси не проходит.
        up = Upstream(lambda conn, log: conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n"))
        self.addCleanup(up.close)
        relay, port = self.start_relay(self.proxy_url(scheme="https", port=up.port))
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertEqual(relay.fatal, TLS_FAILED)

    def test_interim_1xx_does_not_hide_upstream_407(self):
        up, proxy = self.upstream(http_upstream, plain_status=407, interim=INTERIM_100)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, PLAIN_REQUEST)
        self.assertEqual(got, INTERIM_100 + GATEWAY_RESPONSE)
        self.assertNotIn(b"407", got)
        self.assertNotIn(b"Proxy-Authenticate", got)
        self.assertEqual(relay.fatal, REJECTED_HTTP)

    def test_interim_1xx_before_final_status_reaches_client(self):
        up, proxy = self.upstream(http_upstream, interim=INTERIM_103)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, PLAIN_REQUEST)
        self.assertEqual(got, INTERIM_103 + PLAIN_OK)
        self.assertIsNone(relay.fatal)

    def test_connect_interim_1xx_before_200_opens_tunnel(self):
        up, proxy = self.upstream(http_upstream, connect_interim=INTERIM_100)
        relay, port = self.start_relay(proxy)
        got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
        self.assertEqual(got, ESTABLISHED + b"PING")
        self.assertEqual(up.log[0].split("\r\n")[0], "CONNECT a.example:443 HTTP/1.1")
        self.assertIsNone(relay.fatal)

    def test_connect_interim_1xx_before_407_reports_reason(self):
        up, proxy = self.upstream(http_upstream, connect_status=407,
                                  connect_interim=INTERIM_100)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got, GATEWAY_RESPONSE)
        self.assertNotIn(b"407", got)
        self.assertNotIn(b"Proxy-Authenticate", got)
        self.assertEqual(relay.fatal, REJECTED_HTTP)

    def test_proxy_prelude_after_connect_reaches_client_first(self):
        """Байты, пришедшие вместе с 200 на CONNECT, клиент получает первыми."""
        for interim in (None, INTERIM_100):
            with self.subTest(interim=bool(interim)):
                def handler(conn, log, interim=interim):
                    log.append(read_head_rest(conn)[0])
                    # Всё одной порцией: промежуточный 1xx, 200 и первые байты туннеля.
                    conn.sendall((interim or b"") + ESTABLISHED + b"EARLY")

                up = Upstream(handler)
                self.addCleanup(up.close)
                relay, port = self.start_relay(self.proxy_url(port=up.port))
                got = self.talk_eof(port, CONNECT)
                self.assertEqual(got, ESTABLISHED + b"EARLY")
                self.assertIsNone(relay.fatal)

    def test_response_block_over_limit_is_refused_promptly(self):
        """Граница лимита — сам лимит: без разделителя релей не читает вдвое больше."""
        held = threading.Event()

        def overflow(conn, log):
            read_head_rest(conn)
            conn.sendall(b"X" * (RESPONSE_LIMIT + 100))  # блок без разделителя и без конца
            log.append("sent")
            held.wait(30)

        up = Upstream(overflow)
        self.addCleanup(up.close)
        self.addCleanup(held.set)
        relay, port = self.start_relay(self.proxy_url(port=up.port))
        started = time.monotonic()
        got = self.talk_eof(port, PLAIN_REQUEST)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(got, GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, UNREACHABLE)
        self.assertEqual(up.log, ["sent"])

    def test_response_block_limit_is_chunking_independent(self):
        """Блок ровно в лимит проходит, на байт длиннее — нет, при любом разбиении."""
        prefix = b"HTTP/1.1 503 Server Error\r\nX-Pad: "
        for head_len, accepted in ((RESPONSE_LIMIT, True), (RESPONSE_LIMIT + 1, False)):
            head = prefix + b"a" * (head_len - len(prefix)) + b"\r\n\r\n"
            self.assertEqual(len(head) - 4, head_len)
            for chunk in (1024, 4 * RESPONSE_LIMIT):
                with self.subTest(over=head_len - RESPONSE_LIMIT, chunk=chunk):
                    def handler(conn, log, head=head):
                        read_head_rest(conn)
                        conn.sendall(head + b"tail")

                    up = Upstream(handler)
                    self.addCleanup(up.close)
                    # Размер чтения релея задан явно: порции детерминированы и
                    # не зависят от того, как TCP склеил отправленное прокси.
                    with patch.object(self.probe, "_RELAY_CHUNK", chunk):
                        relay, port = self.start_relay(self.proxy_url(port=up.port))
                        got = self.talk_eof(port, PLAIN_REQUEST)
                    if accepted:
                        self.assertEqual(got, head + b"tail")
                        self.assertIsNone(relay.fatal)
                    else:
                        self.assertEqual(got, GATEWAY_RESPONSE)
                        self.assertEqual(relay.fatal, UNREACHABLE)

    def test_silent_upstream_is_502_with_reason(self):
        """Прокси принял TCP и закрыл соединение: клиенту 502, а не голый обрыв."""
        up, proxy = self.upstream(silent_upstream)
        relay, port = self.start_relay(proxy)
        self.assertEqual(self.talk_eof(port, CONNECT), GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, UNREACHABLE)
        self.assertEqual(self.talk_eof(port, PLAIN_REQUEST), GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, UNREACHABLE)

    def test_reset_before_response_is_502_with_reason(self):
        """Сброс соединения при чтении ответа: 502 и причина, а не тихий обрыв."""
        for payload in (PLAIN_REQUEST, CONNECT):
            with self.subTest(request=payload.split(b" ", 1)[0]):
                up, proxy = self.upstream(reset_upstream)
                relay, port = self.start_relay(proxy)
                self.assertEqual(self.talk_eof(port, payload), GATEWAY_RESPONSE)
                self.assertEqual(relay.fatal, UNREACHABLE)
                self.assertEqual(up.log[-1], "reset")

    def test_client_half_close_does_not_half_close_upstream(self):
        """Полузакрытие направления наверх обрезало бы ответ, который ещё в пути."""
        seen = []

        def handler(conn, log):
            log.append(read_head_rest(conn)[0])
            conn.settimeout(0.5)
            try:
                # EOF здесь означает, что релей сделал shutdown(SHUT_WR) наверх.
                seen.append("eof" if not conn.recv(1) else "data")
            except TimeoutError:
                seen.append("open")
            conn.settimeout(5)
            conn.sendall(PLAIN_OK)

        up = Upstream(handler)
        self.addCleanup(up.close)
        relay, port = self.start_relay(self.proxy_url(port=up.port))
        with socket.create_connection(("127.0.0.1", port), 5) as conn:
            conn.settimeout(5)
            conn.sendall(b"GET http://b.example/x HTTP/1.1\r\nHost: b.example\r\n"
                         b"Content-Length: 0\r\n\r\n")
            conn.shutdown(socket.SHUT_WR)
            self.assertEqual(read_eof(conn), PLAIN_OK)
        self.assertEqual(seen, ["open"])
        self.assertIsNone(relay.fatal)

    def test_non_http_absolute_uri_is_400_and_nothing_goes_upstream(self):
        up, proxy = self.upstream(http_upstream)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"GET ftp://b.example/x HTTP/1.1\r\nHost: b.example\r\n\r\n")
        self.assertEqual(got[:12], BAD_REQUEST)
        self.assertEqual(up.log, [])
        self.assertIsNone(relay.fatal)
        # Парный вход: та же цель схемой http проходит.
        got = self.talk_eof(port, b"GET http://b.example/x HTTP/1.1\r\nHost: b.example\r\n\r\n")
        self.assertEqual(got, PLAIN_OK)
        self.assertEqual(len(up.log), 1)

    def test_request_head_limit_is_chunking_independent(self):
        """Заголовок ровно в лимит проходит, на байт длиннее — 400, при любом разбиении."""
        prefix = b"GET http://b.example/"
        suffix = b" HTTP/1.1\r\nHost: b.example"
        for head_len, expected in ((HEAD_LIMIT, PLAIN_OK), (HEAD_LIMIT + 1, BAD_REQUEST)):
            request = prefix + b"x" * (head_len - len(prefix) - len(suffix)) + suffix + b"\r\n\r\n"
            self.assertEqual(len(request) - 4, head_len)
            for chunk in (1024, 4 * HEAD_LIMIT):
                with self.subTest(over=head_len - HEAD_LIMIT, chunk=chunk):
                    up, proxy = self.upstream(http_upstream)
                    # Размер чтения релея задан явно: порции детерминированы.
                    with patch.object(self.probe, "_RELAY_CHUNK", chunk):
                        relay, port = self.start_relay(proxy)
                        with socket.create_connection(("127.0.0.1", port), 5) as conn:
                            conn.settimeout(5)
                            try:
                                conn.sendall(request)
                            except OSError:
                                pass  # релей отвечает, не дочитав вход сверх лимита
                            self.assertEqual(read_eof(conn)[:12], expected[:12])
                    self.assertEqual(len(up.log), 1 if expected is PLAIN_OK else 0)

    def test_unparseable_connect_response_is_502_with_reason(self):
        """Ответ прокси без строки статуса — сбой прокси, а не отказ цели."""
        def handler(conn, log):
            read_head_rest(conn)
            log.append("garbage")
            conn.sendall(b"NOT-HTTP AT ALL\r\n\r\n")

        up = Upstream(handler)
        self.addCleanup(up.close)
        relay, port = self.start_relay(self.proxy_url(port=up.port))
        self.assertEqual(self.talk_eof(port, CONNECT), GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, UNREACHABLE)
        self.assertEqual(up.log, ["garbage"])

    def test_unparseable_plain_response_is_502_and_not_forwarded(self):
        def handler(conn, log):
            read_head_rest(conn)
            log.append("garbage")
            conn.sendall(b"NOT-HTTP AT ALL\r\n\r\nsecret-body")

        up = Upstream(handler)
        self.addCleanup(up.close)
        relay, port = self.start_relay(self.proxy_url(port=up.port))
        got = self.talk_eof(port, PLAIN_REQUEST)
        self.assertEqual(got, GATEWAY_RESPONSE)
        self.assertNotIn(b"NOT-HTTP", got)
        self.assertNotIn(b"secret-body", got)
        self.assertEqual(relay.fatal, UNREACHABLE)

    def test_connect_prelude_read_with_the_head_is_not_dropped(self):
        """Прелюдия после 200 на CONNECT обязана уйти первой: recv детерминирован."""
        for chunks in ([ESTABLISHED + b"EARLY"],
                       [INTERIM_100 + ESTABLISHED + b"EARLY"],
                       [INTERIM_100, ESTABLISHED + b"EARLY"]):
            with self.subTest(chunks=len(chunks)):
                relay = self.probe._ProxyRelay(self.proxy_url(port=dead_port()))
                port = int(RELAY_SERVER.match(relay.start()).group(1))
                self.addCleanup(relay.close)
                canned = CannedUpstream(chunks)
                with patch.object(relay, "_open_upstream", return_value=canned):
                    got = self.talk_eof(port, CONNECT + b"ping")
                self.assertEqual(got, ESTABLISHED + b"EARLY")
                self.assertEqual(canned.sent.split(b"\r\n\r\n", 1)[1], b"ping")
                self.assertIsNone(relay.fatal)


class RelaySocksUpstreamTests(RelayCase):
    """Протокол наверх для socks5 и socks5h: они обязаны работать одинаково."""

    def test_handshake_sends_decoded_credentials_and_target_name(self):
        for scheme in ("socks5", "socks5h"):
            with self.subTest(scheme=scheme):
                up, proxy = self.upstream(socks_upstream, scheme=scheme)
                relay, port = self.start_relay(proxy)
                got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
                self.assertEqual(got[:12], ESTABLISHED[:12])
                self.assertEqual(up.log[0], ("methods", 5, b"\x02"))
                self.assertEqual(up.log[1], ("auth", 1, b"user1", SECRET.encode()))
                self.assertEqual(up.log[2], ("connect", b"\x05\x01\x00\x03", b"a.example", 443))
                self.assertIsNone(relay.fatal)

    def test_plain_http_becomes_tunnel_and_origin_form_request(self):
        up, proxy = self.upstream(socks_upstream, scheme="socks5h")
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, b"GET http://b.example:8000/p?q=1 HTTP/1.1\r\n"
                                  b"Host: b.example:8000\r\nProxy-Connection: keep-alive\r\n"
                                  b"Proxy-Authorization: Basic Zm9vOmJhcg==\r\n\r\n")
        self.assertEqual(got, PLAIN_OK)
        self.assertEqual([entry for entry in up.log if entry[0] == "connect"][-1],
                         ("connect", b"\x05\x01\x00\x03", b"b.example", 8000))
        lines = [entry[1] for entry in up.log if entry[0] == "head"][-1]
        self.assertEqual(lines[0], "GET /p?q=1 HTTP/1.1")
        lowered = [line.lower() for line in lines]
        self.assertIn("connection: close", lowered)
        self.assertFalse(any(line.startswith(("proxy-", "authorization:")) for line in lowered),
                         lines)
        blob = "\n".join(lines).lower()
        self.assertNotIn(TOKEN.lower(), blob)
        self.assertNotIn(SECRET, blob)
        self.assertIsNone(relay.fatal)

    def test_auth_refusal_is_502_with_reason(self):
        for kwargs in ({"auth_ok": False}, {"offers_method": False}):
            with self.subTest(**kwargs):
                up, proxy = self.upstream(socks_upstream, scheme="socks5", **kwargs)
                relay, port = self.start_relay(proxy)
                got = self.talk_eof(port, CONNECT)
                self.assertEqual(got[:12], BAD_GATEWAY)
                self.assertEqual(relay.fatal, REJECTED_SOCKS)

    def test_target_refusal_is_502_without_reason(self):
        up, proxy = self.upstream(socks_upstream, scheme="socks5", reply=0x05)
        relay, port = self.start_relay(proxy)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got[:12], BAD_GATEWAY)
        self.assertIsNone(relay.fatal)

    def test_reply_with_any_address_type_is_parsed(self):
        bounds = (b"\x01\x7f\x00\x00\x01\x00\x50", b"\x03\x09a.example\x00\x50",
                  b"\x04" + b"\x00" * 16 + b"\x00\x50")
        for bound in bounds:
            with self.subTest(bound=bound[:1]):
                up, proxy = self.upstream(socks_upstream, scheme="socks5", bound=bound)
                relay, port = self.start_relay(proxy)
                got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
                self.assertEqual(got, ESTABLISHED + b"PING")
                self.assertIsNone(relay.fatal)


class RelayConstructorTests(RelayCase):
    """Вход релея: userinfo, схемы и предел кредов SOCKS5."""

    def test_start_returns_loopback_listener_only(self):
        relay = self.probe._ProxyRelay(self.proxy_url())
        server = relay.start()
        self.addCleanup(relay.close)
        match = RELAY_SERVER.match(server)
        self.assertIsNotNone(match, server)
        self.assertEqual(relay._listener.getsockname(), ("127.0.0.1", int(match.group(1))))

    def test_url_without_password_is_not_an_error(self):
        up = http_upstream()
        self.addCleanup(up.close)
        relay, port = self.start_relay(f"http://user1@127.0.0.1:{up.port}")
        self.assertEqual(relay.password, "")
        got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
        self.assertEqual(got, ESTABLISHED + b"PING")
        expected = "Proxy-Authorization: Basic " + base64.b64encode(b"user1:").decode()
        self.assertIn(expected, up.log[0].split("\r\n"))
        self.assertIsNone(relay.fatal)

    def test_socks5_credential_over_255_bytes_is_refused_before_start(self):
        for password in ("u" * 256, "п" * 128):
            with self.subTest(bytes=len(password.encode())):
                with self.assertRaises(self.probe.ProxyRelayError):
                    self.probe._ProxyRelay(f"socks5://user1:{password}@127.0.0.1:1080")
        relay = self.probe._ProxyRelay(f"socks5://user1:{'u' * 255}@127.0.0.1:1080")
        self.addCleanup(relay.close)
        self.assertEqual(relay.password, "u" * 255)
        self.assertIsNotNone(relay.start())

    def test_http_credentials_have_no_length_limit(self):
        relay = self.probe._ProxyRelay(f"http://user1:{'u' * 300}@127.0.0.1:8080")
        self.addCleanup(relay.close)
        self.assertEqual(relay.password, "u" * 300)

    def test_unrelayed_scheme_is_refused(self):
        with self.assertRaises(self.probe.ProxyRelayError):
            self.probe._ProxyRelay("ftp://user1:pw@proxy.invalid:21")
        relay = self.probe._ProxyRelay(self.proxy_url(host="proxy.invalid", port=8080))
        self.addCleanup(relay.close)
        self.assertEqual((relay.host, relay.port), ("proxy.invalid", 8080))


class RelayCloseTests(RelayCase):
    """close(): слушатель, живые соединения и потоки."""

    def test_close_frees_port_and_drops_live_tunnel(self):
        up, proxy = self.upstream(http_upstream)
        baseline = threading.active_count()
        relay = self.probe._ProxyRelay(proxy)
        port = int(RELAY_SERVER.match(relay.start()).group(1))
        self.addCleanup(relay.close)
        conn = socket.create_connection(("127.0.0.1", port), 5)
        conn.settimeout(5)
        conn.sendall(CONNECT)
        self.assertEqual(recv_exact(conn, len(ESTABLISHED)), ESTABLISHED)
        relay.close()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), 1).close()
        self.assertEqual(conn.recv(4096), b"")
        conn.close()
        deadline = time.monotonic() + 5
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), baseline)

    def test_close_is_idempotent(self):
        relay, port = self.start_relay(self.proxy_url(port=dead_port()))
        relay.close()
        relay.close()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), 1).close()

    def test_close_interrupts_a_pending_tls_handshake(self):
        """Зависшее рукопожатие TLS будится: сокет прокси учтён до do_handshake()."""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        baseline = threading.active_count()
        relay = self.probe._ProxyRelay(
            self.proxy_url(scheme="https", port=listener.getsockname()[1]))
        port = int(RELAY_SERVER.match(relay.start()).group(1))
        self.addCleanup(relay.close)
        client = socket.create_connection(("127.0.0.1", port), 5)
        self.addCleanup(client.close)
        client.sendall(CONNECT)
        upstream, _ = listener.accept()
        self.addCleanup(upstream.close)
        upstream.settimeout(10)
        # ClientHello дошёл: поток соединения действительно висит в рукопожатии.
        self.assertTrue(upstream.recv(8))
        started = time.monotonic()
        relay.close()
        elapsed = time.monotonic() - started
        # Без учёта сокета close() выжидает весь свой дедлайн (_RELAY_JOIN_TIMEOUT_S).
        self.assertLess(elapsed, 2.0)
        deadline = time.monotonic() + 5
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), baseline)

    def test_thread_is_started_before_it_is_listed(self):
        """В списке close() не должно быть не стартовавших потоков: join() на таком
        бросает RuntimeError, и слушатель остаётся незакрытым."""
        up, proxy = self.upstream(http_upstream)
        relay = self.probe._ProxyRelay(proxy)
        port = int(RELAY_SERVER.match(relay.start()).group(1))
        self.addCleanup(relay.close)
        intercepted = threading.Event()
        release = threading.Event()
        seen = []
        original_start = threading.Thread.start

        def delayed_start(self_thread, *args, **kwargs):
            # Снимок списка в тот момент, когда start() ещё не отработал.
            seen.append((self_thread.name, self_thread.ident,
                         [entry.name for entry in relay._threads]))
            intercepted.set()
            release.wait(10)
            return original_start(self_thread, *args, **kwargs)

        client = None
        try:
            with patch.object(threading.Thread, "start", delayed_start):
                client = socket.create_connection(("127.0.0.1", port), 5)
                self.assertTrue(intercepted.wait(10))
                release.set()
        finally:
            release.set()
            if client is not None:
                client.close()
        worker = [entry for entry in seen if entry[0] == "proxy-relay-connection"]
        self.assertEqual(len(worker), 1, seen)
        self.assertIsNone(worker[0][1])  # поток ещё не стартовал
        self.assertNotIn("proxy-relay-connection", worker[0][2])

    def test_tls_registration_window_is_supervised(self):
        """Между wrap_socket и регистрацией обёртки сокет ядра должен быть под надзором.

        Обёртка отсоединяет сырой объект (fileno() == -1), поэтому shutdown по нему
        до fd не доходит: без дубликата зависшее в окне рукопожатие не разбудить.
        """
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        relay = self.probe._ProxyRelay(
            self.proxy_url(scheme="https", port=listener.getsockname()[1]))
        port = int(RELAY_SERVER.match(relay.start()).group(1))
        self.addCleanup(relay.close)
        closed = threading.Event()
        watched = []
        real_wrap = ssl.SSLContext.wrap_socket

        def closer():
            try:
                relay.close()
            finally:
                closed.set()

        def wrap_in_window(context_self, sock, *args, **kwargs):
            wrapped = real_wrap(context_self, sock, *args, **kwargs)
            inode = os.fstat(wrapped.fileno()).st_ino
            with relay._lock:
                tracked = list(relay._sockets)
            # В надзоре обязан быть объект на ТОТ ЖЕ сокет ядра (тот же inode).
            watched.append(any(item.fileno() != -1
                               and os.fstat(item.fileno()).st_ino == inode
                               for item in tracked))
            threading.Thread(target=closer, daemon=True).start()
            closed.wait(30)  # close() отрабатывает внутри окна регистрации
            return wrapped

        client = upstream = None
        try:
            with patch.object(ssl.SSLContext, "wrap_socket", wrap_in_window):
                client = socket.create_connection(("127.0.0.1", port), 10)
                client.settimeout(30)
                client.sendall(CONNECT)
                upstream, _ = listener.accept()
                read_eof(client)
                # Прокси молчит и держит соединение до конца проверок: разбудить
                # рукопожатие способен только shutdown дубликата из close().
                self.assertEqual(watched, [True])
                deadline = time.monotonic() + 10
                while (any(t.name == "proxy-relay-connection" for t in threading.enumerate())
                       and time.monotonic() < deadline):
                    time.sleep(0.05)
                self.assertEqual([t.name for t in threading.enumerate()
                                  if t.name == "proxy-relay-connection"], [],
                                 "поток соединения не завершился: рукопожатие не разбужено")
                self.assertEqual(relay.fatal, TLS_FAILED)
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    sock.close()


class BrowserWiringTests(RelayCase):
    """Прокси запуска браузеров и закрытие релея вместе с адаптером."""

    def test_browser_proxy_pairs_relay_with_credentials(self):
        settings, relay = self.probe._browser_proxy(self.proxy_url())
        self.addCleanup(relay.close)
        self.assertEqual(list(settings), ["server"])
        self.assertEqual(settings["server"], f"http://127.0.0.1:{relay._listener.getsockname()[1]}")
        self.assertEqual(relay.password, SECRET)

    def test_browser_proxy_without_userinfo_keeps_native_settings(self):
        for proxy, expected in (("http://proxy.invalid:8080",
                                 {"server": "http://proxy.invalid:8080"}),
                                ("socks5h://proxy.invalid:1080",
                                 {"server": "socks5://proxy.invalid:1080"})):
            with self.subTest(proxy=proxy):
                settings, relay = self.probe._browser_proxy(proxy)
                self.assertIsNone(relay)
                self.assertEqual(settings, expected)

    def test_credentialed_proxy_becomes_relay_for_both_browser_steps(self):
        up, proxy = self.upstream(http_upstream)
        for adapter_name in ("patchright", "scrapling"):
            with self.subTest(adapter=adapter_name):
                modules, runtime, session = self.browser_modules()
                with patch.dict(sys.modules, modules), patch.dict(os.environ,
                                                                  {"ABG_PROXY": proxy}):
                    adapter = self.probe.make_adapter(adapter_name)
                    adapter.start()
                    self.addCleanup(adapter.close)
                    settings = self.launched_proxy(adapter_name, runtime, session)
                    self.assertEqual(list(settings), ["server"])
                    match = RELAY_SERVER.match(settings["server"])
                    self.assertIsNotNone(match, settings)
                    self.assertNotEqual(int(match.group(1)), up.port)
                    self.assertIsNotNone(adapter._relay)
                    self.assertNotIn(SECRET, json.dumps(settings))
                    self.assertNotIn("user1", json.dumps(settings))

    def test_proxy_without_credentials_launches_without_relay_or_cdp(self):
        for adapter_name in ("patchright", "scrapling"):
            for proxy in ("", "http://proxy.invalid:8080", "socks5h://proxy.invalid:1080"):
                with self.subTest(adapter=adapter_name, proxy=proxy or "none"):
                    modules, runtime, session = self.browser_modules()
                    page = runtime.chromium.launch.return_value.new_page.return_value
                    environ = {"ABG_PROXY": proxy} if proxy else {}
                    with patch.dict(sys.modules, modules), patch.dict(os.environ, environ,
                                                                      clear=True):
                        adapter = self.probe.make_adapter(adapter_name)
                        adapter.start()
                        self.addCleanup(adapter.close)
                        expected = self.probe.playwright_proxy(proxy) if proxy else None
                        self.assertEqual(self.launched_proxy(adapter_name, runtime, session),
                                         expected)
                        self.assertIsNone(adapter._relay)
                        self.assertIsNone(adapter.fatal)
                        page.route.assert_not_called()
                        page.context.new_cdp_session.assert_not_called()

    def test_playwright_package_keeps_native_credentials(self):
        modules, runtime, session = self.browser_modules()
        with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"ABG_PROXY": f"http://user1:{ENC}@proxy.invalid:8080"}):
            adapter = self.probe.PlaywrightAdapter()
            adapter.start()
            self.addCleanup(adapter.close)
            self.assertEqual(runtime.chromium.launch.call_args.kwargs["proxy"],
                             {"server": "http://proxy.invalid:8080", "username": "user1",
                              "password": SECRET})
            self.assertIsNone(adapter._relay)
            self.assertIsNone(adapter.fatal)

    def test_webrtc_protection_stays_on_the_relay_path(self):
        flag = "--webrtc-ip-handling-policy=disable_non_proxied_udp"
        for adapter_name in ("patchright", "scrapling"):
            with self.subTest(adapter=adapter_name):
                modules, runtime, session = self.browser_modules()
                with patch.dict(sys.modules, modules), patch.dict(
                        os.environ, {"ABG_PROXY": self.proxy_url()}):
                    adapter = self.probe.make_adapter(adapter_name)
                    adapter.start()
                    self.addCleanup(adapter.close)
                    if adapter_name == "patchright":
                        self.assertEqual(runtime.chromium.launch.call_args.kwargs["args"], [flag])
                    else:
                        self.assertIs(session.call_args.kwargs["block_webrtc"], True)

    def test_relay_is_closed_when_launch_fails(self):
        modules, runtime, session = self.browser_modules()
        runtime.chromium.launch.side_effect = RuntimeError("launch failed")
        with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"ABG_PROXY": self.proxy_url(port=dead_port())}):
            adapter = self.probe.make_adapter("patchright")
            with self.assertRaises(RuntimeError):
                adapter.start()
            server = runtime.chromium.launch.call_args.kwargs["proxy"]["server"]
            port = int(RELAY_SERVER.match(server).group(1))
            adapter.close()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), 1).close()

    def test_relay_is_closed_when_browser_close_raises(self):
        for adapter_name in ("patchright", "scrapling"):
            with self.subTest(adapter=adapter_name):
                modules, runtime, session = self.browser_modules()
                if adapter_name == "patchright":
                    runtime.chromium.launch.return_value.close.side_effect = RuntimeError("x")
                else:
                    session.return_value.__exit__.side_effect = RuntimeError("x")
                with patch.dict(sys.modules, modules), patch.dict(
                        os.environ, {"ABG_PROXY": self.proxy_url(port=dead_port())}):
                    adapter = self.probe.make_adapter(adapter_name)
                    adapter.start()
                    server = self.launched_proxy(adapter_name, runtime, session)["server"]
                    port = int(RELAY_SERVER.match(server).group(1))
                    with self.assertRaises(RuntimeError):
                        adapter.close()
                with self.assertRaises(OSError):
                    socket.create_connection(("127.0.0.1", port), 1).close()


class RunProbeRelayReasonTests(RelayCase):
    """fatal релея становится причиной в err пробы — и при таймауте, и при успехе."""

    RESULT = {"status": 200, "final_url": URL, "body": "<html><body>page text</body></html>",
              "bytes": 5, "title": None, "redirects": 0, "headers": None}

    class Stub:
        version = "stub"

        def __init__(self, result=None, error=None, fatal=None):
            self.result = result
            self.error = error
            self.fatal = fatal
            self.closed = False

        def start(self):
            pass

        def navigate(self, url):
            if self.error is not None:
                raise self.error
            return dict(self.result)

        def close(self):
            self.closed = True

    def probe_with(self, stub, sentinel=None, content_only=True, **kwargs):
        # Хелпер не должен называться run: unittest.TestCase.run — точка входа
        # раннера, и его перекрытие молча снимает весь класс с прогона.
        return self.probe.run_probe(
            "patchright", URL, sentinel, mode="cold", content_only=content_only,
            include_content=True, adapter_factory=lambda _: stub, metrics=lambda: (0, 0),
            **kwargs)

    def test_navigation_failure_keeps_its_own_reason_without_fatal(self):
        stub = self.Stub(error=RuntimeError("net::ERR_TUNNEL_CONNECTION_FAILED"))
        payload = self.probe_with(stub)
        self.assertEqual(payload["err"], "RuntimeError: net::ERR_TUNNEL_CONNECTION_FAILED")
        self.assertIs(payload["ok"], False)
        self.assertTrue(stub.closed)

    def test_navigation_failure_reports_the_proxy_reason(self):
        stub = self.Stub(error=RuntimeError("net::ERR_TUNNEL_CONNECTION_FAILED"),
                         fatal=REJECTED_HTTP)
        payload = self.probe_with(stub)
        self.assertEqual(payload["err"], f"ProxyRelayError: {REJECTED_HTTP}")
        self.assertIs(payload["ok"], False)
        self.assertTrue(stub.closed)

    def test_timeout_reports_the_proxy_reason(self):
        payload = self.probe_with(self.Stub(error=TimeoutError("budget exceeded"), fatal=UNREACHABLE))
        self.assertEqual(payload["err"], f"ProxyRelayError: {UNREACHABLE}")
        paired = self.probe_with(self.Stub(error=TimeoutError("budget exceeded")))
        self.assertEqual(paired["err"], "timeout")

    def test_successful_navigation_with_fatal_reads_as_failure(self):
        payload = self.probe_with(self.Stub(result=self.RESULT, fatal=REJECTED_SOCKS))
        self.assertIs(payload["ok"], False)
        self.assertIsNone(payload["status"])
        self.assertEqual(payload["err"], f"ProxyRelayError: {REJECTED_SOCKS}")
        self.assertEqual((payload["html"], payload["text"]), ("", ""))
        self.assertNotIn("page text", json.dumps(payload))

    def test_successful_navigation_without_fatal_stays_successful(self):
        # В режиме content_only ok всегда false: sentinel не ищется. Успех виден
        # по status/err/html, а пара с sentinel доказывает ok=True без fatal.
        payload = self.probe_with(self.Stub(result=self.RESULT))
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["err"], "")
        self.assertIn("page text", payload["html"])
        passed = self.probe_with(self.Stub(result=self.RESULT), sentinel="page text",
                                 content_only=False)
        self.assertIs(passed["ok"], True)
        self.assertEqual(passed["err"], "")
        spoiled = self.probe_with(self.Stub(result=self.RESULT, fatal=REJECTED_SOCKS),
                                  sentinel="page text", content_only=False)
        self.assertIs(spoiled["ok"], False)
        self.assertIsNone(spoiled["status"])
        self.assertEqual(spoiled["err"], f"ProxyRelayError: {REJECTED_SOCKS}")

    def test_fatal_hides_the_proxy_url_of_the_underlying_error(self):
        stub = self.Stub(error=RuntimeError(f"dial {self.proxy_url()} failed"), fatal=UNREACHABLE)
        blob = json.dumps(self.probe_with(stub))
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(ENC, blob)
        self.assertIn(f"ProxyRelayError: {UNREACHABLE}", blob)

    def test_adapter_publishes_relay_reason_end_to_end(self):
        up = http_upstream(connect_status=407)
        self.addCleanup(up.close)
        modules, runtime, session = self.browser_modules()
        page = runtime.chromium.launch.return_value.new_page.return_value

        def goto(url, **kwargs):
            server = runtime.chromium.launch.call_args.kwargs["proxy"]["server"]
            self.talk_eof(int(RELAY_SERVER.match(server).group(1)), CONNECT)
            raise RuntimeError("net::ERR_TUNNEL_CONNECTION_FAILED at " + url)

        page.goto.side_effect = goto
        with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"ABG_PROXY": f"http://user1:{ENC}@127.0.0.1:{up.port}"}):
            payload = self.probe.run_probe("patchright", URL, None, mode="cold",
                                           content_only=True, include_content=True,
                                           metrics=lambda: (0, 0))
        self.assertEqual(payload["err"], f"ProxyRelayError: {REJECTED_HTTP}")
        self.assertIs(payload["ok"], False)
        blob = json.dumps(payload)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(ENC, blob)


class RelayTlsUpstreamTests(RelayCase):
    """Настоящий TLS до https-прокси: сертификат генерируется openssl во временный
    каталог и передаётся через SSL_CERT_FILE, как это делает стенд M27."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._box = tempfile.TemporaryDirectory()
        box = Path(cls._box.name)
        cls.certs = make_certificates(box)
        # Тот же CA, но имя в SAN не совпадает с адресом прокси: для проверки
        # сравнения имени, которое отключается вместе с проверкой цепочки.
        cls.other_host_certs = None if cls.certs is None else make_certificates(
            box, san="DNS:proxy.invalid", cn="proxy.invalid", leaf="other")

    @classmethod
    def tearDownClass(cls):
        cls._box.cleanup()

    def setUp(self):
        if self.certs is None:
            self.skipTest("openssl в образе нет: настоящий TLS-тест невозможен")

    def tls_proxy(self, handler, certs=None, trusted=True):
        up = TlsUpstream(handler, self.certs if certs is None else certs)
        self.addCleanup(up.close)
        patcher = patch.dict(os.environ, {"SSL_CERT_FILE": self.certs["ca"]})
        patcher.start()
        self.addCleanup(patcher.stop)
        if not trusted:
            # Доверия к CA нет: проверка цепочки обязана сработать.
            del os.environ["SSL_CERT_FILE"]
        relay, port = self.start_relay(self.proxy_url(scheme="https", port=up.port))
        return up, relay, port

    def test_tls_tunnel_adds_credentials_and_carries_bytes(self):
        def handler(conn, log):
            log.append(read_head_rest(conn)[0])
            conn.sendall(ESTABLISHED)
            conn.sendall(recv_exact(conn, 4).upper())

        up, relay, port = self.tls_proxy(handler)
        got = self.talk(port, CONNECT + b"ping", ESTABLISHED + b"PING")
        self.assertEqual(got, ESTABLISHED + b"PING")
        self.assertEqual(up.log[0].split("\r\n"),
                         ["CONNECT a.example:443 HTTP/1.1", "Host: a.example:443", BASIC_LINE])
        self.assertIsNone(relay.fatal)

    def test_client_half_close_does_not_close_tls_tunnel(self):
        """SHUT_WR на ssl.SSLSocket шлёт close_notify и рвёт туннель целиком."""
        seen = []

        def handler(conn, log):
            log.append(read_head_rest(conn)[0])
            conn.sendall(ESTABLISHED)
            conn.settimeout(0.5)
            try:
                # EOF здесь означает, что релей полузакрыл TLS-соединение наверх.
                seen.append("eof" if not conn.recv(1) else "data")
            except TimeoutError:
                seen.append("open")
            conn.settimeout(5)
            conn.sendall(b"PONG")

        up, relay, port = self.tls_proxy(handler)
        with socket.create_connection(("127.0.0.1", port), 5) as client:
            client.settimeout(5)
            client.sendall(CONNECT)
            self.assertEqual(recv_exact(client, len(ESTABLISHED)), ESTABLISHED)
            client.shutdown(socket.SHUT_WR)  # клиент больше не пишет, но ещё читает
            self.assertEqual(client.recv(4096), b"PONG")
        self.assertEqual(seen, ["open"])
        self.assertIsNone(relay.fatal)

    def test_untrusted_proxy_certificate_is_refused_without_credentials(self):
        """Проверка цепочки не отключена: недоверенный CA — отказ до запроса."""
        def handler(conn, log):
            log.append(read_head_rest(conn)[0])

        up, relay, port = self.tls_proxy(handler, trusted=False)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got, GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, TLS_FAILED)
        # Рукопожатие не прошло: запрос с Proxy-Authorization наверх не ушёл.
        self.assertEqual(up.log, [])

    def test_proxy_certificate_name_mismatch_is_refused_without_credentials(self):
        """Цепочка доверенная, но имя в SAN не совпадает с адресом прокси."""
        def handler(conn, log):
            log.append(read_head_rest(conn)[0])

        up, relay, port = self.tls_proxy(handler, certs=self.other_host_certs)
        got = self.talk_eof(port, CONNECT)
        self.assertEqual(got, GATEWAY_RESPONSE)
        self.assertEqual(relay.fatal, TLS_FAILED)
        self.assertEqual(up.log, [])

    def test_supervision_handover_drops_the_duplicate(self):
        """После рукопожатия в реестре только обёртка: закрытый дубликат не остаётся."""
        held = threading.Event()
        self.addCleanup(held.set)

        def handler(conn, log):
            log.append(read_head_rest(conn)[0])
            conn.sendall(ESTABLISHED)
            held.wait(30)  # туннель жив, пока тест смотрит реестр сокетов

        up, relay, port = self.tls_proxy(handler)
        with socket.create_connection(("127.0.0.1", port), 5) as client:
            client.settimeout(5)
            client.sendall(CONNECT)
            self.assertEqual(recv_exact(client, len(ESTABLISHED)), ESTABLISHED)
            with relay._lock:
                tracked = list(relay._sockets)
            self.assertEqual([item for item in tracked if item.fileno() == -1], [],
                             "в реестре остался закрытый сокет (дубликат-наблюдатель)")
            self.assertEqual(len([item for item in tracked
                                  if isinstance(item, ssl.SSLSocket)]), 1)
            # слушатель + соединение клиента + обёртка прокси, и ничего лишнего
            self.assertEqual(len(tracked), 3)
            self.assertIn(BASIC_LINE, up.log[0].split("\r\n"))
            self.assertIsNone(relay.fatal)


class ModuleShapeTests(RelayCase):
    """Защита от молчаливого снятия класса с прогона (находка ревью M27)."""

    def test_no_test_class_shadows_unittest_run(self):
        module = sys.modules[__name__]
        loader = unittest.TestLoader()
        classes = []
        for name in dir(module):
            value = getattr(module, name)
            if not (isinstance(value, type) and issubclass(value, unittest.TestCase)):
                continue
            classes.append(name)
            # Перекрытый run() ломает TestCase.__call__: класс даёт «Ran 0 tests».
            self.assertIs(getattr(value, "run", None), unittest.TestCase.run,
                          f"{name} перекрывает unittest.TestCase.run")
            own_tests = [attr for attr in vars(value) if attr.startswith("test_")]
            if own_tests:
                collected = loader.loadTestsFromTestCase(value).countTestCases()
                self.assertEqual(collected, len(own_tests), f"{name}: собрано {collected}")
        self.assertIn("RunProbeRelayReasonTests", classes)
        self.assertGreater(len(classes), 5)

    def test_relay_limits_match_the_literals_used_in_tests(self):
        """Границы в тестах — литералы, поэтому значение констант закреплено здесь:
        удвоение лимита роняет этот тест, а не молча масштабирует остальные."""
        self.assertEqual(self.probe._RELAY_HEAD_LIMIT, HEAD_LIMIT)
        self.assertEqual(self.probe._RELAY_RESPONSE_LIMIT, RESPONSE_LIMIT)
        self.assertEqual(self.probe._RELAY_BIND_HOST, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
