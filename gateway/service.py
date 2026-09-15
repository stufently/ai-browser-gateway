"""Deployed API entry: fail-closed files, rotation, labeled provider runs."""
from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

from gateway.httpapi import make_server

_INSTANCE = re.compile(r'[a-z][a-z0-9-]{0,62}')
_PORT = re.compile(r'0|[1-9][0-9]{0,4}')
_LIMIT = re.compile(r'[1-9][0-9]*')
_OWNER = 'ai-browser-gateway'


class ConfigError(Exception):
    pass


class LabeledLauncher:
    def __init__(self, instance, request_id, inner=None):
        from bench.runner.execute import DockerLauncher
        self.instance = instance
        self.request_id = request_id
        self.inner = inner or DockerLauncher()

    def run(self, argv, timeout, *, env=None):
        if argv[:2] == ['docker', 'run']:
            argv = argv[:2] + [
                '--label', 'abg.owner=' + _OWNER,
                '--label', 'abg.instance=' + self.instance,
                '--label', 'abg.role=provider',
                '--label', 'abg.request=' + self.request_id,
            ] + argv[2:]
        return self.inner.run(argv, timeout, env=env)


def sweep_providers(instance, timeout=20):
    if not instance:
        return
    filters = [
        '--filter', 'label=abg.owner=' + _OWNER,
        '--filter', 'label=abg.instance=' + instance,
        '--filter', 'label=abg.role=provider',
    ]
    try:
        listed = subprocess.run(
            ['docker', 'ps', '-aq', *filters], capture_output=True, text=True,
            timeout=timeout, stdin=subprocess.DEVNULL)
        ids = listed.stdout.split()
        if ids:
            subprocess.run(
                ['docker', 'rm', '--force', *ids], capture_output=True,
                timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def read_private(path):
    path = Path(path)
    try:
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ConfigError
        data = path.read_bytes()
    except OSError:
        raise ConfigError from None
    if not data:
        raise ConfigError
    return data


def _proxy(url):
    if (not isinstance(url, str) or not url
            or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        raise ConfigError
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ConfigError from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or type(port) is not int or not 1 <= port <= 65535):
        raise ConfigError
    return url


def _profiles(raw):
    try:
        data = tomllib.loads(raw.decode('utf-8'))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise ConfigError from None
    table = data.get('profile', {})
    if not isinstance(table, dict) or not table:
        raise ConfigError
    profiles = {}
    for name, body in table.items():
        if (not isinstance(name, str) or not name or name == 'direct'
                or not isinstance(body, dict)):
            raise ConfigError
        profiles[name] = _proxy(body.get('url', ''))
    return profiles


def _int_env(env, key, default, pattern, hi=None):
    raw = env.get(key, default)
    if not isinstance(raw, str) or not pattern.fullmatch(raw):
        raise ConfigError
    value = int(raw)
    if hi is not None and value > hi:
        raise ConfigError
    return value


def make_service(environ=None, *, fetcher_factory=None):
    env = os.environ if environ is None else environ
    try:
        if env.get('ABG_TOKEN'):
            raise ConfigError
        token = read_private(env.get('ABG_TOKEN_FILE', '')).decode('ascii').rstrip('\r\n')
        if (not token or any(not 33 <= ord(char) <= 126 for char in token)):
            raise ConfigError
        profiles = _profiles(read_private(env.get('ABG_PROFILES_FILE', '')))
        bind = env.get('ABG_BIND', '0.0.0.0')
        instance = env.get('ABG_INSTANCE', '')
        if not isinstance(bind, str) or not bind or not _INSTANCE.fullmatch(instance):
            raise ConfigError
        port = _int_env(env, 'ABG_PORT', '8765', _PORT, 65535)
        limit = _int_env(env, 'ABG_BROWSER_LIMIT', '1', _LIMIT)
        network = env.get('ABG_PROVIDER_NETWORK') or None
    except (TypeError, ValueError, UnicodeError, ConfigError):
        raise ConfigError from None

    def factory(url, **kwargs):
        if fetcher_factory is not None:
            return fetcher_factory(url, **kwargs)
        from gateway.fetch import ProductFetcher
        return ProductFetcher(
            url, launcher=LabeledLauncher(instance, os.urandom(16).hex()),
            network=network, **kwargs)

    server = make_server(
        (bind, port), token=token, browser_limit=limit, profiles=profiles,
        fetcher_factory=factory, rotate_profiles=True)
    server.instance = instance
    return server


def main():
    try:
        server = make_service()
    except Exception:
        print('{"error":"invalid_configuration"}', file=sys.stderr)
        return 1
    instance = getattr(server, 'instance', '')
    sweep_providers(instance)

    def stop(*_args):
        server.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        sweep_providers(instance)
    return 0


if __name__ == '__main__':
    sys.exit(main())
