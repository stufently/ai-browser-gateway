"""Solved-challenge sessions per host: a browser's cookies and UA, replayed by curl_cffi.

Measured 2026-10-09: with a browser's cookies and User-Agent, curl_cffi gets
the real page from rbc.ru (Qrator) and bizprofile.net (Cloudflare
cf_clearance) instead of the challenge. Cookies are bound to the address that
solved them, so only direct steps share a session.
"""
import json
import os
from pathlib import Path
import re
import threading
import time

MAX_AGE_S = 1800
MAX_ENTRIES = 256
MAX_COOKIES = 64
MAX_TEXT = 4096
# A file name is the host itself, so only plain DNS labels qualify.
_HOST = re.compile(r'[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*')


def valid_session(value):
    """The probe's session shape: {"ua": str, "cookies": [{"name", "value"}...]}."""
    if not isinstance(value, dict) or set(value) != {'ua', 'cookies'}:
        return False
    ua, cookies = value.get('ua'), value.get('cookies')
    if not isinstance(ua, str) or not ua or len(ua) > 512 or any(ord(c) < 32 for c in ua):
        return False
    if not isinstance(cookies, list) or not 0 < len(cookies) <= MAX_COOKIES:
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict) or set(cookie) != {'name', 'value'}:
            return False
        if not all(isinstance(cookie[key], str) and len(cookie[key]) <= MAX_TEXT
                   for key in ('name', 'value')) or not cookie['name']:
            return False
    return True


class SessionStore:
    """In-memory, thread-safe, bounded; the oldest entry leaves first."""

    def __init__(self, *, clock=time.time, max_entries=MAX_ENTRIES):
        self._clock = clock
        self._max = max_entries
        self._lock = threading.Lock()
        self._items = {}

    def get(self, host):
        with self._lock:
            item = self._items.get(host)
            if item is None:
                return None
            deadline, session = item
            if self._clock() >= deadline:
                del self._items[host]
                return None
            return {'ua': session['ua'], 'cookies': [dict(c) for c in session['cookies']]}

    def put(self, host, session):
        if not host or not valid_session(session):
            return
        with self._lock:
            self._items.pop(host, None)
            self._items[host] = (self._clock() + MAX_AGE_S, session)
            while len(self._items) > self._max:
                del self._items[next(iter(self._items))]

    def drop(self, host):
        with self._lock:
            self._items.pop(host, None)


class FileSessionStore:
    """One 0600 JSON file per host in a 0700 directory, for the one-shot CLI."""

    def __init__(self, directory, *, clock=time.time):
        self._dir = Path(directory)
        self._clock = clock

    def _path(self, host):
        if not isinstance(host, str) or len(host) > 253 or not _HOST.fullmatch(host):
            return None
        return self._dir / (host + '.json')

    def get(self, host):
        path = self._path(host)
        if path is None:
            return None
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            deadline, session = item['deadline'], item['session']
            if type(deadline) not in (int, float) or not valid_session(session):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if self._clock() >= deadline:
            self.drop(host)
            return None
        return {'ua': session['ua'], 'cookies': session['cookies']}

    def put(self, host, session):
        path = self._path(host)
        if path is None or not valid_session(session):
            return
        try:
            self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = json.dumps({'deadline': self._clock() + MAX_AGE_S, 'session': session})
            temporary = path.with_name(path.name + '.tmp')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(data)
            os.replace(temporary, path)
        except OSError:
            pass

    def drop(self, host):
        path = self._path(host)
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass
