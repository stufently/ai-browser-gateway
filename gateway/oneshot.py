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


class LocalLauncher:
    """Translate the registry's Docker command into an isolated local probe."""

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
        child_env['ABG_PROVIDER'] = provider.name
        proc = subprocess.Popen(command, env=child_env, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise
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
        result = run_product(request, ProductFetcher(request.url, launcher=LocalLauncher()))
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
