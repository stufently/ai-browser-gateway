"""Stream JSONL into M1 coverage while accumulating report observations."""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path

from bench.models import FailureReason
from bench.providers.registry import PROVIDERS
from bench.report.coverage import incremental
from bench.report.render import render_markdown
from bench.runner.environment import FIELDS
from bench.runner.record import from_jsonl_line


def _md(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def build_report(jsonl_path, *, order, threshold=0.05, unmeasured=()) -> str:
    order = list(order)
    if len(set(order)) != len(order):
        raise ValueError('duplicate providers in order')
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('threshold must be between 0 and 1')
    metadata = {key: set() for key in (*FIELDS, 'provider_version', 'image_version', 'egress_profile')}
    counts = defaultdict(lambda: [0, 0])
    skipped = defaultdict(int)
    measured_providers, observed_providers, measured_groups = set(), set(), set()
    ages = defaultdict(list)
    timings, memory = defaultdict(list), defaultdict(list)
    groups, cells = set(), set()

    def read_records(source):
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = from_jsonl_line(line)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f'{jsonl_path}: line {line_number}: {exc}') from exc
            cells.add(record.cell)
            group = record.provider, record.mode
            groups.add(group)
            observed_providers.add(record.provider)
            not_measured = record.error_type == FailureReason.not_measured
            if not_measured:
                skipped[record.provider, record.cell] += 1
            else:
                count = counts[record.provider, record.cell]
                count[0] += int(record.success)
                count[1] += 1
                measured_providers.add(record.provider)
                measured_groups.add(group)
                if record.entrance_age_hours is not None:
                    ages[record.provider].append(record.entrance_age_hours)
            for key in metadata:
                value = getattr(record, key) or 'unknown'
                if key in ('provider_version', 'image_version'):
                    value = f'{record.provider}: {value}'
                metadata[key].add(value)
            unavailable = (
                record.error_type in (
                    FailureReason.provider_error, FailureReason.timeout,
                    FailureReason.environment_error,
                )
                and not any((record.elapsed_ms, record.startup_ms, record.cpu_ms, record.peak_rss_mb))
            )
            if not not_measured and not unavailable:
                timings[group].append(record.elapsed_ms)
                memory[group].append(record.peak_rss_mb)
            yield record

    with Path(jsonl_path).open(encoding='utf-8') as source:
        records = read_records(source)
        rows = incremental(records, order)

    lines = ['# Отчёт прогона', '', '## Окружение', '', '| Поле | Наблюдения |', '|---|---|']
    for key, values in metadata.items():
        lines.append(f'| {key} | {_md("; ".join(sorted(values)) or "unknown")} |')
    lines += ['', '## Провайдер × ячейка', '',
              'Успешных / измеренных попыток; пропуски — не измерено.', '']
    ordered_cells = sorted(cells)
    lines.append('| Провайдер |' + ''.join(f' {_md(cell)} |' for cell in ordered_cells))
    lines.append('|---|' + '---|' * len(ordered_cells))
    for provider in order:
        values = []
        for cell in ordered_cells:
            success, total = counts[provider, cell]
            value = f'{success}/{total}' if total else 'не измерено'
            if total and skipped[provider, cell]:
                value += f'; не измерено: {skipped[provider, cell]}'
            values.append(value)
        lines.append(f'| {_md(provider)} |' + ''.join(f' {v} |' for v in values))
    lines += ['', '## Задержка и память', '',
              'Метрики всех измеренных попыток, включая HTTP-отказы. p95: ближайший ранг ceil(0.95 × n).',
              'Нулевые заглушки метрик при отказе запуска/протокола исключены; покрытие включает измеренные попытки.', '',
              '| Провайдер | Режим | Измерений | Медиана, мс | p95, мс | Пиковый RSS, МиБ |',
              '|---|---|---|---|---|---|']
    for provider in order:
        for mode in ('cold', 'warm'):
            group = provider, mode
            if group not in groups:
                continue
            if group not in measured_groups:
                lines.append(f'| {_md(provider)} | {mode} | ' + ' | '.join(['не измерено'] * 4) + ' |')
                continue
            values = sorted(timings[group])
            if values:
                stats = (f'{statistics.median(values):.2f}',
                         f'{values[math.ceil(.95 * len(values)) - 1]:.2f}',
                         f'{max(memory[group]):.2f}')
            else:
                stats = ('unknown',) * 3
            lines.append(f'| {_md(provider)} | {mode} | {len(values)} | {" | ".join(stats)} |')
    entrance_names = {p.name for p in PROVIDERS if p.kind == 'entrance'}
    entrances = [name for name in order if name in entrance_names and name in observed_providers]
    if entrances:
        lines += ['', '## Возраст контента', '',
                  '| Провайдер | Медианный возраст, ч |', '|---|---|']
        for provider in entrances:
            values = ages[provider]
            age = (f'{statistics.median(values):.2f}' if values else
                   'unknown' if provider in measured_providers else 'не измерено')
            lines.append(f'| {_md(provider)} | {age} |')
    wholly_unmeasured = observed_providers - measured_providers
    unmeasured = list(dict.fromkeys([*unmeasured, *(name for name in order if name in wholly_unmeasured)]))
    lines += ['', '## Incremental coverage', '',
              render_markdown([row for row in rows if row.provider not in wholly_unmeasured],
                              threshold=threshold, unmeasured=unmeasured).rstrip()]
    return '\n'.join(lines) + '\n'
