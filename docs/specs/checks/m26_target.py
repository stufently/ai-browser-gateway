"""Цель стенда M26: HTTP-сервер в изолированной docker-сети.

Владеет постановщик; исполнитель его не правит. Запускает m26_stand.sh.
Пути:
  /ok    200, текст в разметке;
  /deny  403 на всё (не Cloudflare: без cf-mitigated и «Just a moment»);
  /js    200, видимый текст появляется только после JS (curl_cffi видит
         пустую страницу -> content_missing -> лестница идёт в браузер);
  /gate  200 только клиенту с адресом хоста из $ALLOW_HOST, иначе 403.
Каждый запрос печатается в stderr строкой `TARGET <ip> <path> <ua>`.
"""
import http.server
import os
import socket
import sys

OK = (b"<html><head><title>M26 OK</title></head><body><h1>proxied page</h1>"
      b"<p>m26 marker text</p></body></html>")
DENY = b"<html><head><title>Denied</title></head><body><p>denied</p></body></html>"
JS = (b"<html><body><div id=m></div><script>document.getElementById('m')"
      b".textContent='m26 rendered by script';</script></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        client = self.client_address[0]
        sys.stderr.write(f"TARGET {client} {self.path} "
                         f"{self.headers.get('User-Agent', '')[:80]}\n")
        sys.stderr.flush()
        path = self.path.split("?", 1)[0]
        if path == "/ok":
            code, body = 200, OK
        elif path == "/js":
            code, body = 200, JS
        elif path == "/gate":
            try:
                allowed = socket.gethostbyname(os.environ.get("ALLOW_HOST", ""))
            except OSError:
                allowed = None
            code, body = (200, OK) if client == allowed else (403, DENY)
        elif path == "/deny":
            code, body = 403, DENY
        else:
            code, body = 404, b""
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
