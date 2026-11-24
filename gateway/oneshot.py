"""Self-contained product CLI with local provider processes.

ABG_PROXY routes curl_cffi, patchright and scrapling through a single proxy.
--proxy URL takes precedence and rejects userinfo (proxy_credentials_in_argv).
Pass proxy credentials through ABG_PROXY: browser steps receive them through a
loopback relay inside the probe, so SOCKS5 with a password works with browser
steps enabled. Invalid URLs report invalid_request.

With no explicit proxy, the ladder starts direct and ABG_EGRESS_PROXY can
add a final curl_cffi step. ABG_SESSION_DIR keeps sessions across runs,
with a separate directory for each explicit proxy identity.
"""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from bench.providers.registry import PROVIDERS
from gateway.fetch import ProductFetcher
from gateway.format import MODES, render_content
from gateway.product import ProductRequest, plan_product, run_product


EGRESS_ENV = 'ABG_EGRESS_PROXY'
SESSION_DIR_ENV = 'ABG_SESSION_DIR'
EGRESS_PROFILE = 'proxy'
EXPLICIT_PROFILE = 'explicit'
_PROXY_PORTS = {'http': 80, 'https': 443, 'socks5': 1080, 'socks5h': 1080}


def _proxy_parts(proxy):
    parts = urlsplit(proxy)
    if parts.scheme not in _PROXY_PORTS or not parts.hostname:
        raise ValueError('invalid proxy')
    parts.port  # ValueError on a malformed port.
    return parts


def egress_profiles(environ=os.environ):
    """{profile: proxy URL} from the environment; empty when unset or blank."""
    proxy = environ.get(EGRESS_ENV, '').strip()
    if not proxy:
        return {}
    _proxy_parts(proxy)
    return {EGRESS_PROFILE: proxy}


class _ProxyRefusal(ValueError):
    """A proxy input rejected with a specific CLI error."""


def _explicit_proxy(flags):
    if flags:
        candidates = flags
    else:
        proxy = os.environ.get('ABG_PROXY', '')
        if not proxy.strip():
            return None
        candidates = [proxy]
    for proxy in candidates:
        if any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159
               for char in proxy):
            raise ValueError('invalid proxy')
        parts = _proxy_parts(proxy)
        if parts.username is not None and flags:
            raise _ProxyRefusal('proxy_credentials_in_argv')
    # curl_cffi must resolve names at the proxy, as Chromium does with SOCKS5.
    return 'socks5h' + proxy[len(parts.scheme):] if parts.scheme == 'socks5' else proxy


class _Interrupted(BaseException):
    """Unwind the provider ladder without becoming a provider error."""


class LocalLauncher:
    """Translate the registry's Docker command into an isolated local probe."""

    def __init__(self):
        self._active = set()
        self._starting = False
        self._interrupted = False

    def kill_active(self):
        for pid in tuple(self._active):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run(self, argv, timeout, *, env=None):
        images = {provider.image: provider for provider in PROVIDERS}
        for index, arg in enumerate(argv):
            if arg in images:
                provider = images[arg]
                break
        else:
            raise ValueError('unknown provider image')
        command = ['python3', '/opt/abg/probe.py', *argv[index + 1:]]
        if provider.kind == 'browser':
            command = ['xvfb-run', '-a', '-s', '-screen 0 1920x1080x24', *command]
        child_env = dict(os.environ if env is None else env)
        child_env = {name: value for name, value in child_env.items()
                     if name.lower() not in {'http_proxy', 'https_proxy', 'all_proxy',
                                             'ftp_proxy', 'no_proxy'}
                     and name not in {EGRESS_ENV,
                                      'PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK'}}
        child_env['ABG_PROVIDER'] = provider.name
        proc = None
        try:
            # Defer interruption until Popen has returned the PID we must kill.
            self._starting = True
            try:
                proc = subprocess.Popen(command, env=child_env, start_new_session=True,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
                self._active.add(proc.pid)
            finally:
                self._starting = False
                if self._interrupted:
                    self.kill_active()
                    raise _Interrupted
            stdout, stderr = proc.communicate(timeout=timeout)
        except _Interrupted:
            if proc is not None:
                proc.wait()
            raise
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise
        finally:
            if proc is not None:
                self._active.discard(proc.pid)
        return proc.returncode, stdout, stderr


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_request')


def session_store(proxy=None):
    """Persist sessions in the mounted directory, scoped by proxy identity."""
    directory = os.environ.get(SESSION_DIR_ENV)
    if not directory:
        return None
    from gateway.sessions import FileSessionStore
    root = FileSessionStore(directory)
    if proxy is None:
        return root
    if not root._private():
        return None
    parts = urlsplit(proxy)
    identity = '|'.join((parts.scheme, parts.hostname,
                         str(parts.port or _PROXY_PORTS[parts.scheme]),
                         unquote(parts.username or '')))
    scope = 'proxy-' + sha256(identity.encode('utf-8')).hexdigest()[:16]
    return FileSessionStore(Path(directory) / scope)


def main(argv=None):
    try:
        try:
            parser = _Parser(add_help=False, allow_abbrev=False)
            parser.add_argument('url')
            parser.add_argument('--format', choices=MODES, default='text')
            parser.add_argument('--expected-text')
            parser.add_argument('--budget-ms', type=int, default=30000)
            parser.add_argument('--no-browser', action='store_true')
            parser.add_argument('--proxy', action='append')
            args = parser.parse_args(argv)
            profiles = egress_profiles()
            proxy = _explicit_proxy(args.proxy)
            egress = tuple(profiles)
            route = 'direct'
            if proxy is not None:
                route = EXPLICIT_PROFILE
                profiles = {route: proxy}
                egress = ()
            request = ProductRequest(args.url, max_age_hours=0, egress_profiles=egress,
                                     budget_ms=args.budget_ms, allow_browser=not args.no_browser,
                                     expected_text=args.expected_text, route_profile=route)
            plan_product(request)
        except _ProxyRefusal as error:
            print(json.dumps({'error': str(error)}), file=sys.stderr)
            return 2
        except (ValueError, TypeError, OverflowError, RecursionError, OSError):
            print('{"error": "invalid_request"}', file=sys.stderr)
            return 2
        launcher = LocalLauncher()

        def interrupt(signum, frame):
            first = not launcher._interrupted
            launcher._interrupted = True
            launcher.kill_active()
            if first and not launcher._starting:
                raise _Interrupted

        previous = {}
        try:
            for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                previous[signum] = signal.signal(signum, interrupt)
            result = run_product(request, ProductFetcher(
                request.url, profiles=profiles, launcher=launcher,
                sessions=session_store(proxy), route=request.route_profile))
        except _Interrupted:
            print('{"error": "interrupted"}', file=sys.stderr)
            return 4
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        value = {key: getattr(result, key) for key in ('ok', 'url', 'final_url', 'provider',
                 'age_hours', 'error_type', 'step', 'elapsed_ms')}
        value.update(format=args.format, content=render_content(result, args.format),
                     attempts=[asdict(attempt) for attempt in result.attempts])
        print(json.dumps(value, ensure_ascii=True, allow_nan=False))
        return 0 if result.ok else 1
    except Exception:
        print('{"error": "internal_error"}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
