"""Solved-challenge sessions per host: a browser's cookies and UA, replayed by curl_cffi.

Measured 2026-10-09: with a browser's cookies and User-Agent, curl_cffi gets
the real page from rbc.ru (Qrator) and bizprofile.net (Cloudflare
cf_clearance) instead of the challenge. Cookies are bound to the address that
solved them, so only direct steps share a session.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time

MAX_AGE_S = 1800
MAX_ENTRIES = 256
MAX_COOKIES = 64
MAX_TEXT = 4096
# A file name is the host itself, so only plain DNS labels qualify.
_HOST = re.compile(r'[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*')


def _same(stored, session):
    return stored['ua'] == session['ua'] and stored['cookies'] == session['cookies']


def valid_session(value):
    """The probe's session shape: {"ua": str, "cookies": [{"name", "value"[, "domain"]}...]}."""
    if not isinstance(value, dict) or set(value) != {'ua', 'cookies'}:
        return False
    ua, cookies = value.get('ua'), value.get('cookies')
    if not isinstance(ua, str) or not ua or len(ua) > 512 or any(ord(c) < 32 for c in ua):
        return False
    if not isinstance(cookies, list) or not 0 < len(cookies) <= MAX_COOKIES:
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict) or set(cookie) not in ({'name', 'value'},
                                                               {'name', 'value', 'domain'}):
            return False
        if not all(isinstance(cookie[key], str) and len(cookie[key]) <= MAX_TEXT
                   for key in ('name', 'value')) or not cookie['name']:
            return False
        domain = cookie.get('domain', '')
        if not isinstance(domain, str) or len(domain) > 255:
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

    def drop(self, host, session=None):
        """Remove the host's session; with session, only if it is still that one."""
        with self._lock:
            item = self._items.get(host)
            if item is not None and (session is None or _same(item[1], session)):
                del self._items[host]


class FileSessionStore:
    """One 0600 JSON file per host in a private (0700, own) directory, for the CLI.

    A directory another user owns or can write to is refused: nothing is read
    or written there. Writes go through a fresh mkstemp file, so a planted
    link is never followed and concurrent writers never share a file.
    """

    def __init__(self, directory, *, clock=time.time):
        self._dir = Path(directory)
        self._clock = clock

    def _path(self, host):
        if not isinstance(host, str) or len(host) > 253 or not _HOST.fullmatch(host):
            return None
        return self._dir / (host + '.json')

    def _private(self):
        try:
            info = os.lstat(self._dir)
        except OSError:
            return False
        return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and not info.st_mode & 0o077)

    @contextmanager
    def _locked(self):
        """One writer at a time across processes: put and a checked drop."""
        fd = os.open(self._dir / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _read(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, encoding='utf-8') as stream:
                item = json.loads(stream.read())
            deadline, session = item['deadline'], item['session']
            if type(deadline) not in (int, float) or not valid_session(session):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return deadline, session

    def get(self, host):
        path = self._path(host)
        if path is None or not self._private():
            return None
        item = self._read(path)
        if item is None:
            return None
        deadline, session = item
        if self._clock() >= deadline:
            self.drop(host, session)
            return None
        return {'ua': session['ua'], 'cookies': session['cookies']}

    def put(self, host, session):
        path = self._path(host)
        if path is None or not valid_session(session):
            return
        try:
            self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self._private():
                return
            data = json.dumps({'deadline': self._clock() + MAX_AGE_S, 'session': session})
            fd, temporary = tempfile.mkstemp(dir=self._dir, prefix='.session-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(data)
                with self._locked():
                    os.replace(temporary, path)
            except OSError:
                os.unlink(temporary)
                raise
        except OSError:
            pass

    def drop(self, host, session=None):
        """Remove the host's session; with session, only if it is still that one."""
        path = self._path(host)
        if path is None or not self._private():
            return
        try:
            with self._locked():
                if session is not None:
                    item = self._read(path)
                    if item is None or not _same(item[1], session):
                        return
                path.unlink()
        except OSError:
            pass
