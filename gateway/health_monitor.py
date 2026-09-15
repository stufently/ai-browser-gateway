"""Sidecar health loop: GET /health, then ping or ping/fail."""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from gateway.service import ConfigError, read_private

_LOCAL = {'127.0.0.1', 'localhost', '::1'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _cap(timeout):
    try:
        value = min(float(timeout), 5.0)
    except (TypeError, ValueError):
        return 5.0
    return value if math.isfinite(value) and value > 0 else 5.0


def _fetch(url, timeout):
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, method='GET'), timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except OSError:
            pass
        finally:
            exc.close()
        return exc.code, b''


def check_once(health_url, ping_url, *, timeout=5):
    timeout = _cap(timeout)
    healthy = False
    try:
        status, body = _fetch(health_url, timeout)
        if status == 200:
            data = json.loads(body)
            healthy = isinstance(data, dict) and data.get('ok') is True
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
    allow = os.environ.get('ABG_MONITOR_ALLOW_LOCAL_HTTP') == '1'
    target = ping_url if healthy else ping_url + '/fail'
    if _url(ping_url, ping=True, allow_local=allow):
        try:
            _fetch(target, timeout)
        except Exception as exc:
            print(type(exc).__name__, file=sys.stderr)
    return healthy


def _url(value, *, ping, allow_local):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return False
    if (parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or not parsed.hostname
            or not parsed.path or (port is not None and not 1 <= port <= 65535)):
        return False
    if parsed.scheme == 'https':
        return True
    if parsed.scheme != 'http':
        return False
    local = parsed.hostname in _LOCAL
    if ping:
        return allow_local and local
    return allow_local if local else True


def main():
    env = os.environ
    try:
        allow = env.get('ABG_MONITOR_ALLOW_LOCAL_HTTP') == '1'
        health = env.get('ABG_HEALTH_URL', '')
        ping = read_private(env.get('ABG_HC_PING_FILE', '')).decode('utf-8').strip()
        raw = env.get('ABG_HEALTH_INTERVAL_SECONDS', '60')
        interval = float(raw)
        if (not _url(health, ping=False, allow_local=allow)
                or not _url(ping, ping=True, allow_local=allow)
                or not math.isfinite(interval) or interval <= 0):
            raise ConfigError
    except (TypeError, ValueError, UnicodeError, ConfigError):
        print('{"error":"invalid_configuration"}', file=sys.stderr)
        return 1
    while True:
        check_once(health, ping, timeout=5)
        time.sleep(interval)


if __name__ == '__main__':
    sys.exit(main())
