"""Direct-only, self-contained product CLI with local provider processes."""
import argparse
from dataclasses import asdict
import json
import os
import signal
import subprocess
import sys

from bench.providers.registry import PROVIDERS
from gateway.fetch import ProductFetcher
from gateway.format import MODES, render_content
from gateway.product import ProductRequest, plan_product, run_product


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
                                             'ftp_proxy', 'no_proxy'}}
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


def main(argv=None):
    try:
        try:
            parser = _Parser(add_help=False, allow_abbrev=False)
            parser.add_argument('url')
            parser.add_argument('--format', choices=MODES, default='text')
            parser.add_argument('--expected-text')
            parser.add_argument('--budget-ms', type=int, default=30000)
            parser.add_argument('--no-browser', action='store_true')
            args = parser.parse_args(argv)
            request = ProductRequest(args.url, max_age_hours=0, egress_profiles=(),
                                     budget_ms=args.budget_ms, allow_browser=not args.no_browser,
                                     expected_text=args.expected_text)
            plan_product(request)
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
            result = run_product(request, ProductFetcher(request.url, launcher=launcher))
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
