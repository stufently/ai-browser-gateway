"""Цель стенда M27: HTTP-сервер в изолированной docker-сети.

Владеет постановщик; исполнитель его не правит. Запускает m27_stand.sh.
Пути (B — имя второго хоста цели из ?b=, другой сайт для Chromium):
  /ok, /deny, /js   как у m26_target.py;
  /frame?b=B        главный документ, текст «m27 iframe text» только в
                    cross-site iframe http://B:8000/inner;
  /sw               регистрирует service worker /sw.js; страница берёт
                    /via-sw, воркер отвечает своим fetch('/sw-backend'),
                    текст «m27 service worker text» (нужен secure context:
                    стенд открывает /sw как http://localhost:8000);
  /authpage?b=B     текст «m27 auth page» только из JS и картинка
                    http://B:8000/auth401 (cross-site: Chromium не показывает
                    окно входа, а iframe или главный документ с 401 Basic
                    без обработчика CDP подвешивают или роняют загрузку);
  /auth401          401 с WWW-Authenticate: Basic.
Страница /sw держит событие load картинкой /hold?k=K, пока
страница не запросит /release?k=K (после записи текста) или 15 с.
Каждый запрос печатается в stderr: `TARGET <ip> <path> authz=<0|1>`.
"""
import html
import http.server
import sys
import threading
import uuid
from urllib.parse import parse_qs, urlsplit

OK = (b"<html><head><title>M26 OK</title></head><body><h1>proxied page</h1>"
      b"<p>m26 marker text</p></body></html>")
DENY = b"<html><head><title>Denied</title></head><body><p>denied</p></body></html>"
JS = (b"<html><body><div id=m></div><script>document.getElementById('m')"
      b".textContent='m26 rendered by script';</script></body></html>")
PIXEL = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
         b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
HOLDS = {}
LOCK = threading.Lock()


def hold_key():
    key = uuid.uuid4().hex
    with LOCK:
        HOLDS[key] = threading.Event()
    return key


def page(title, script, key):
    return (f"<html><head><title>{title}</title></head><body><div id=m>waiting</div>"
            f"<script>function done(text){{document.getElementById('m').textContent=text;"
            f"fetch('/release?k={key}');}}{script}</script>"
            f"<img src='/hold?k={key}' alt=''></body></html>").encode()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        authz = 1 if self.headers.get("Authorization") else 0
        sys.stderr.write(f"TARGET {self.client_address[0]} {path} authz={authz}\n")
        sys.stderr.flush()
        other = html.escape(query.get("b", [""])[0], quote=True)
        ctype, extra = "text/html; charset=utf-8", []
        if path == "/ok":
            code, body = 200, OK
        elif path == "/js":
            code, body = 200, JS
        elif path == "/deny":
            code, body = 403, DENY
        elif path == "/frame":
            code, body = 200, (f"<html><head><title>M27 frame</title></head><body>"
                               f"<p>m27 main</p><iframe src='http://{other}:8000/inner'>"
                               f"</iframe></body></html>").encode()
        elif path == "/inner":
            code, body = 200, b"<html><body><p>m27 iframe text</p></body></html>"
        elif path == "/sw":
            key = hold_key()
            code, body = 200, page("M27 sw", (
                "navigator.serviceWorker.register('/sw.js').then(function(){"
                "if(navigator.serviceWorker.controller){return;}"
                "return new Promise(function(r){navigator.serviceWorker"
                ".addEventListener('controllerchange',r);});}).then(function(){"
                "return fetch('/via-sw');}).then(function(r){return r.text();})"
                ".then(done,function(e){done('sw failed '+e);});"), key)
        elif path == "/sw.js":
            ctype = "text/javascript"
            code, body = 200, (b"self.addEventListener('install',function(){self.skipWaiting();});"
                               b"self.addEventListener('activate',function(e){"
                               b"e.waitUntil(self.clients.claim());});"
                               b"self.addEventListener('fetch',function(e){"
                               b"if(new URL(e.request.url).pathname==='/via-sw'){"
                               b"e.respondWith(fetch('/sw-backend'));}});")
        elif path == "/sw-backend":
            ctype = "text/plain; charset=utf-8"
            code, body = 200, b"m27 service worker text"
        elif path == "/hold":
            with LOCK:
                event = HOLDS.get(query.get("k", [""])[0])
            if event is not None:
                event.wait(15)
            ctype, code, body = "image/gif", 200, PIXEL
        elif path == "/release":
            with LOCK:
                event = HOLDS.get(query.get("k", [""])[0])
            if event is not None:
                event.set()
            ctype, code, body = "text/plain", 200, b"ok"
        elif path == "/authpage":
            code, body = 200, (f"<html><head><title>M27 auth</title></head><body><div id=m></div>"
                               f"<script>document.getElementById('m').textContent='m27 auth'+' page';"
                               f"</script><img src='http://{other}:8000/auth401' alt=''>"
                               f"</body></html>").encode()
        elif path == "/auth401":
            code, body = 401, b"<html><body><p>auth required</p></body></html>"
            extra = [("WWW-Authenticate", 'Basic realm="m27"')]
        else:
            code, body = 404, b""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
