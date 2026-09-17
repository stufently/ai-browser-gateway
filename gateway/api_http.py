"""HTTP framing and JSON transport; product policy stays in gateway.product."""
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler
import hmac
import json
import re
import time
from gateway.api_limit import limit_fetcher
from gateway.format import MODES, render_content
from gateway.product import ProductRequest, plan_product, run_product


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('invalid_request')
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError('invalid_request')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {'error': 'invalid_request'})

    def respond(self, status, value):
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False).encode('utf-8')
        self.close_connection = True
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(raw)

    def __getattr__(self, name):
        if name.startswith('do_'):
            return self.dispatch
        raise AttributeError(name)

    def body(self):
        lengths = self.headers.get_all('Content-Length', [])
        types = self.headers.get_all('Content-Type', [])
        if (len(lengths) != 1 or self.headers.get_all('Transfer-Encoding')
                or not re.fullmatch(r'[0-9]+', lengths[0]) or len(types) != 1
                or types[0].split(';', 1)[0].strip().lower() != 'application/json'):
            raise ValueError('invalid_request')
        size = int(lengths[0])
        if size > 65536:
            raise ValueError('invalid_request')
        # read1 returns available bytes, allowing a total deadline even on a trickle.
        deadline, data = time.monotonic() + 4, bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('invalid_request')
            self.connection.settimeout(remaining)
            chunk = self.rfile.read1(size - len(data))
            if not chunk:
                raise ValueError('invalid_request')
            data.extend(chunk)
        self.connection.settimeout(None)
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=reject_constant)

    def dispatch(self):
        try:
            if self.path not in ('/health', '/v1/fetch'):
                return self.respond(404, {'error': 'not_found'})
            expected = 'GET' if self.path == '/health' else 'POST'
            if self.command != expected:
                return self.respond(405, {'error': 'method_not_allowed'})
            if self.path == '/health':
                return self.respond(200, {'ok': True})
            auth = self.headers.get_all('Authorization', [])
            if len(auth) != 1 or not hmac.compare_digest(
                    auth[0].encode('utf-8'), b'Bearer ' + self.server.token):
                return self.respond(401, {'error': 'unauthorized'})
            try:
                data = self.body()
                allowed = {'url', 'max_age_hours', 'budget_ms', 'allow_browser', 'expected_text', 'format'}
                if not isinstance(data, dict) or data.keys() - allowed:
                    raise ValueError('invalid_request')
                mode = data.pop('format', 'text')
                if mode not in MODES:
                    raise ValueError('invalid_request')
                request = ProductRequest(**data, egress_profiles=tuple(self.server.profiles))
                plan_product(request)  # Full M10 validation before factory and budget clock.
            except (ValueError, TypeError, OverflowError, RecursionError, OSError):
                return self.respond(400, {'error': 'invalid_request'})
            profiles = dict(self.server.profiles)
            if getattr(self.server, 'rotate_profiles', False) and profiles:
                with self.server.rotate_lock:
                    names = list(self.server.profiles)
                    index = self.server.rotate_index % len(names)
                    self.server.rotate_index += 1
                    names = names[index:] + names[:index]
                profiles = {name: self.server.profiles[name] for name in names}
                request = ProductRequest(**data, egress_profiles=tuple(profiles))
            fetcher = self.server.factory(request.url, entrances=dict(self.server.entrances),
                                          profiles=dict(profiles))
            result = run_product(request, limit_fetcher(fetcher, self.server.slots, url=request.url))
            value = {key: getattr(result, key) for key in ('ok', 'url', 'final_url', 'provider',
                     'age_hours', 'error_type', 'step', 'elapsed_ms')}
            value.update(format=mode, content=render_content(result, mode),
                         attempts=[asdict(attempt) for attempt in result.attempts])
            self.respond(200, value)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            try:
                self.respond(500, {'error': 'internal_error'})
            except OSError:
                pass
