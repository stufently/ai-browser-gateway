"""Class-level summary that is safe to publish.

Local targets (``bench/targets/local.toml``) must never leave the host, yet
their results should. This summary prints target classes and counts only:
no target ids, URLs, egress addresses or ASNs, and its errors never echo
values read from the target files or the JSONL either.
"""
from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from pathlib import Path

from bench.models import FailureReason
from bench.providers.registry import PROVIDERS
from bench.runner.record import from_jsonl_line

# Lower-case words joined by '+' or '-'. No dots, so a class cannot carry a domain.
CLASS_PATTERN = re.compile(r'^[a-z0-9]+(?:[+-][a-z0-9]+)*$')
DEFAULT_ORDER = tuple(p.name for p in sorted(PROVIDERS, key=lambda p: p.tier))
KNOWN_PROVIDERS = frozenset(DEFAULT_ORDER)
NOT_MEASURED = 'not measured'


def load_classes(paths) -> dict[str, str]:
    """Map target id to class across all files; reject what could leak."""
    classes: dict[str, str] = {}
    for path in map(Path, paths):
        try:
            with path.open('rb') as source:
                targets = tomllib.load(source).get('target', [])
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f'{path.name}: invalid TOML at line {exc.lineno}') from None
        if not isinstance(targets, list):
            raise ValueError(f'{path.name}: [[target]] must be an array of tables')
        for number, target in enumerate(targets, 1):
            where = f'{path.name}: target #{number}'
            if not isinstance(target, dict) or not isinstance(target.get('id'), str) or not target['id']:
                raise ValueError(f'{where}: missing id')
            klass = target.get('class')
            if not isinstance(klass, str) or not CLASS_PATTERN.fullmatch(klass):
                raise ValueError(f'{where}: class must match {CLASS_PATTERN.pattern}')
            if target['id'] in classes:
                raise ValueError(f'{where}: duplicate target id across --targets')
            classes[target['id']] = klass
    return classes


def build_aggregate(jsonl_path, target_paths, *, order=DEFAULT_ORDER) -> str:
    order = list(order)
    if len(set(order)) != len(order):
        raise ValueError('duplicate providers in order')
    if not set(order) <= KNOWN_PROVIDERS:
        raise ValueError('--order names providers outside the registry')
    classes = load_classes(target_paths)
    seen: set[str] = set()
    providers: set[str] = set()
    measured: dict[str, set[str]] = defaultdict(set)
    taken: dict[str, set[str]] = defaultdict(set)
    unknown = 0
    foreign = 0
    with Path(jsonl_path).open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = from_jsonl_line(line)
            except (ValueError, TypeError, KeyError):
                raise ValueError(f'line {line_number}: invalid run record') from None
            if record.target is None:  # stand scenarios are not targets
                continue
            if record.target not in classes:
                unknown += 1
                continue
            if record.provider not in KNOWN_PROVIDERS:
                foreign += 1
                continue
            seen.add(record.target)
            providers.add(record.provider)
            if record.error_type == FailureReason.not_measured:
                continue
            measured[record.provider].add(record.target)
            if record.success:
                taken[record.provider].add(record.target)
    if unknown:
        raise ValueError(f'{unknown} records reference targets missing from --targets')
    if foreign:
        raise ValueError(f'{foreign} records name providers outside the registry')
    missing = sorted(providers - set(order))
    if missing:
        raise ValueError('providers missing from --order: ' + ', '.join(missing))
    columns = [name for name in order if name in providers]

    lines = ['# Benchmark summary by target class', '',
             'Targets taken / targets measured, per provider. A target counts once per',
             'provider; "Any provider" counts targets taken by at least one of them.', '',
             '| Class | Targets |' + ''.join(f' {name} |' for name in columns) + ' Any provider |',
             '|---|---|' + '---|' * len(columns) + '---|']
    for klass in sorted({classes[target] for target in seen}):
        members = {target for target in seen if classes[target] == klass}
        cells, any_measured, any_taken = [], set(), set()
        for name in columns:
            got, tried = taken[name] & members, measured[name] & members
            any_measured |= tried
            any_taken |= got
            cells.append(f'{len(got)}/{len(tried)}' if tried else NOT_MEASURED)
        overall = f'{len(any_taken)}/{len(any_measured)}' if any_measured else NOT_MEASURED
        lines.append(f'| {klass} | {len(members)} |' + ''.join(f' {cell} |' for cell in cells)
                     + f' {overall} |')
    return '\n'.join(lines) + '\n'
