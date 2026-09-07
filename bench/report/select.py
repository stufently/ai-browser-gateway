"""Keep providers for coverage, qualified by content freshness.

Cost decides only the order of consideration, never who is dropped.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from bench.providers.registry import PROVIDERS


class Decision(tuple):
    """(keep, reason, axis). Unpacks as (keep, reason) for two-field callers."""

    def __new__(cls, keep, reason, axis):
        return super().__new__(cls, (keep, reason, axis))

    def __iter__(self):
        yield self[0]
        yield self[1]


def canonical_order(records) -> list[str]:
    """Порядок разбора из ДАННЫХ, а не из порядка строк в реестре."""
    records = list(records)
    names = {record.provider for record in records}
    if not names:
        return []
    cpu_by: dict[str, list[float]] = defaultdict(list)
    for record in records:
        if record.success:
            cpu_by[record.provider].append(record.cpu_ms)
    tier_by = {provider.name: provider.tier for provider in PROVIDERS}

    def key(name: str):
        samples = cpu_by[name]
        cpu = statistics.median(samples) if samples else float("inf")
        return (tier_by.get(name, float("inf")), cpu, name)

    return sorted(names, key=key)


def _comparable(age_kept, age_candidate, tolerance: float) -> bool:
    if age_kept is None and age_candidate is None:
        return True
    if age_kept is None or age_candidate is None:
        return False
    return age_kept <= age_candidate + tolerance


def _solved_ages(records) -> dict[str, dict[str, list]]:
    solved: dict[str, dict[str, list]] = {}
    for record in records:
        if not record.success:
            continue
        cells = solved.setdefault(record.provider, {})
        cells.setdefault(record.cell, []).append(record.entrance_age_hours)
    return solved


def keep_set(records, *, age_tolerance_hours: float = 1.0) -> dict[str, tuple]:
    """Провайдер -> (оставить, причина, измерение). От порядка записей не зависит.

    age_tolerance_hours — политика, а не измерение. Умолчание 1.0 значит:
    в пределах часа содержимое считается одинаково свежим. Числа, полученного
    замером, здесь нет.
    """
    records = list(records)
    if not records:
        return {}
    order = canonical_order(records)
    solved = _solved_ages(records)
    kept_ages: dict[str, list] = defaultdict(list)
    decisions: dict[str, tuple] = {}
    for provider in order:
        cells = solved.get(provider) or {}
        if not cells:
            decisions[provider] = Decision(False, "нет успешных клеток", "покрытие")
            continue
        useful = []
        for cell in sorted(cells):
            ages = cells[cell]
            held = kept_ages.get(cell, [])
            if held and any(_comparable(other, age, age_tolerance_hours) for other in held for age in ages):
                continue
            useful.append((cell, ages, held))
        if not useful:
            decisions[provider] = Decision(
                False, "клетки уже покрыты в сопоставимом качестве", "покрытие"
            )
        else:
            parts = []
            has_new_cell = False
            for cell, ages, held in useful:
                if not held:
                    has_new_cell = True
                    parts.append(f"клетка `{cell}`")
                    continue
                known_held = sorted(item for item in held if item is not None)
                known_new = sorted(item for item in ages if item is not None)
                if known_held and known_new:
                    delta = known_held[0] - known_new[0]
                    parts.append(f"клетка `{cell}` свежее на {delta:.1f} ч")
                else:
                    parts.append(f"клетка `{cell}`")
            axis = "покрытие" if has_new_cell else "свежесть"
            decisions[provider] = Decision(True, "; ".join(parts), axis)
            for cell, ages in cells.items():
                kept_ages[cell].extend(ages)
    return decisions
