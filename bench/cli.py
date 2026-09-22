"""Standard-library command line for reproducible M2 runs."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tomllib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bench.egress import load_profiles, profile_url
from bench.models import FailureReason
from bench.providers.registry import PROVIDERS, by_name
from bench.report.aggregate import DEFAULT_ORDER, build_aggregate
from bench.report.build import build_report
from bench.runner.environment import collect
from bench.runner.execute import DockerLauncher, execute_plan
from bench.runner.matrix import build_plan
from bench.runner.record import to_jsonl_line
from bench.scenarios import SCENARIOS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python3 -m bench', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('providers', help='list provider registry')
    for name in ('plan', 'run'):
        cmd = commands.add_parser(name, help='print plan' if name == 'plan' else 'execute plan into a new JSONL file')
        cmd.add_argument('--providers', nargs='+', default=[p.name for p in PROVIDERS if p.kind != 'entrance'])
        cmd.add_argument('--cells', nargs='+', help='scenario:<id> or target:<id>; defaults to all selected inputs')
        cmd.add_argument('--base-url', '--stand-url', default='http://127.0.0.1:8000', help='stand A base URL')
        cmd.add_argument('--targets', type=Path, nargs='+',
                         help='target TOML files, merged in order; invalid targets are skipped')
        cmd.add_argument('--cold', type=int, default=1)
        cmd.add_argument('--warm', type=int, default=None, help='browser warm attempts (default 1 for stand, 0 for targets)')
        if name == 'run':
            cmd.add_argument('--output', '-o', required=True, type=Path, help='new JSONL file; never overwrite a run')
            cmd.add_argument('--timeout', type=int, default=180)
            cmd.add_argument('--pause-s', type=float, default=20, help='pause per repeated host; target files require at least 30s')
            cmd.add_argument('--egress-ip', help='observed egress, otherwise unknown; never inferred from local interfaces')
            cmd.add_argument('--asn', help='observed ASN, otherwise unknown')
            cmd.add_argument('--egress', help='proxy profile name from ~/.config/abg/proxies.toml')
    report = commands.add_parser('report', help='JSONL to Markdown')
    report.add_argument('jsonl_path')
    report.add_argument('--order', nargs='+', default=[p.name for p in sorted(PROVIDERS, key=lambda p: p.tier)])
    report.add_argument('--threshold', type=float, default=.05)
    report.add_argument('--unmeasured', nargs='*', default=[])
    report.add_argument('--output', '-o', type=Path)
    aggregate = commands.add_parser('aggregate', help='JSONL to a class-level summary safe to publish')
    aggregate.add_argument('jsonl_path')
    aggregate.add_argument('--targets', type=Path, nargs='+', required=True,
                           help='every target TOML the run used; each target needs a class')
    aggregate.add_argument('--order', nargs='+', default=list(DEFAULT_ORDER))
    aggregate.add_argument('--output', '-o', type=Path)
    return parser


def _cells_and_plan(args):
    cells = {f'scenario:{s.id}': {'url': args.base_url.rstrip('/') + s.path, 'sentinel': s.sentinel}
             for s in SCENARIOS}
    target_names = []
    if args.targets is not None:
        targets = []
        for path in args.targets:
            with path.open('rb') as source:
                targets.extend(tomllib.load(source).get('target', []))
        for target in targets:
            if target.get('valid', True) is False:
                continue
            name = 'target:' + target['id']
            if name in cells:
                raise ValueError(f'duplicate target: {name}')
            cells[name] = {'url': target['url'], 'sentinel': target['expect'],
                           'entrances': target.get('entrances', {})}
            target_names.append(name)
    selected = args.cells if args.cells is not None else (target_names if args.targets is not None else list(cells))
    selected_cells = {}
    for name in selected:
        if name not in cells:
            raise ValueError(f'unknown cell: {name}')
        cell = cells[name]
        parsed = urlsplit(cell['url'])
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError(f'{name}: expected an HTTP(S) URL')
        if not isinstance(cell['sentinel'], str) or not cell['sentinel']:
            raise ValueError(f'{name}: empty sentinel')
        selected_cells[name] = cell
    has_targets = any(name.startswith('target:') for name in selected)
    warm = args.warm if args.warm is not None else (0 if has_targets else 1)
    if has_targets and (args.cold != 1 or warm != 0):
        raise ValueError('target files permit one request per provider and target: --cold 1 --warm 0')
    providers = [by_name(name) for name in args.providers]
    plan = build_plan(providers, selected, cold=args.cold, warm=warm)
    return selected_cells, plan, has_targets


def _environment_reader(args, launcher):
    """Observe local facts; external commands still cross the Launcher boundary."""
    def read(key):
        if key == 'date':
            return datetime.now(timezone.utc).isoformat()
        if key == 'kernel':
            return platform.release()
        if key == 'docker_version':
            rc, out, _ = launcher.run(['docker', '--version'], timeout=10)
            return out if rc == 0 else None
        return getattr(args, key, None)
    return read


def main(argv=None, *, launcher=None, reader=None, sleep=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'providers':
            print('name\ttier\tkind\tneeds_network\timage')
            for p in PROVIDERS:
                print(f'{p.name}\t{p.tier}\t{p.kind}\t{str(p.needs_network).lower()}\t{p.image}')
        elif args.command in ('report', 'aggregate'):
            if args.command == 'report':
                result = build_report(args.jsonl_path, order=args.order, threshold=args.threshold,
                                      unmeasured=args.unmeasured)
            else:
                result = build_aggregate(args.jsonl_path, args.targets, order=args.order)
            if args.output is None:
                print(result, end='')
            else:
                with args.output.open('x', encoding='utf-8') as destination:
                    destination.write(result)
        else:
            cells, plan, has_targets = _cells_and_plan(args)
            if args.command == 'plan':
                for item in plan:
                    print(json.dumps({**asdict(item), 'run_id': item.run_id}, ensure_ascii=False))
            else:
                launcher = DockerLauncher() if launcher is None else launcher
                pause = max(30, args.pause_s) if has_targets else args.pause_s
                # Open exclusively before any metadata command or provider launch.
                with args.output.open('x', encoding='utf-8') as destination:
                    env = collect(reader=reader if reader is not None else _environment_reader(args, launcher))
                    egress = None
                    skip_reason = None
                    if args.egress:
                        creds = Path.home() / '.config' / 'abg' / 'proxies.toml'
                        try:
                            profiles = load_profiles(creds)
                            egress = (args.egress, profile_url(profiles, args.egress))
                        except PermissionError:
                            print(f'credentials file is group- or world-accessible: {creds}', file=sys.stderr)
                            egress = (args.egress, None)
                            skip_reason = FailureReason.environment_error
                    records = execute_plan(plan, launcher=launcher, cells=cells, env=env,
                                           timeout=args.timeout, pause_s=pause, sleep=sleep,
                                           egress=egress, skip_reason=skip_reason)
                    for record in records:
                        destination.write(to_jsonl_line(record))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
