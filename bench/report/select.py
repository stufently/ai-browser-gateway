"""Keep providers for coverage, qualified by content freshness.

Cost decides only the order of consideration, never who is dropped.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from bench.providers.registry import PROVIDERS


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


def _merge_age(current, incoming):
    known = [age for age in (current, incoming) if age is not None]
    return min(known) if known else None


def _comparable(age_kept, age_candidate, tolerance: float) -> bool:
    if age_kept is None and age_candidate is None:
        return True
    if age_kept is None or age_candidate is None:
        return False
    return age_kept <= age_candidate + tolerance


def _solved_ages(records) -> dict[str, dict[str, float | None]]:
    solved: dict[str, dict[str, float | None]] = {}
    for record in records:
        if not record.success:
            continue
        cells = solved.setdefault(record.provider, {})
        if record.cell in cells:
            cells[record.cell] = _merge_age(cells[record.cell], record.entrance_age_hours)
        else:
            cells[record.cell] = record.entrance_age_hours
    return solved


def keep_set(records, *, age_tolerance_hours: float = 1.0) -> dict[str, tuple[bool, str]]:
    """Провайдер -> (оставить, причина). От порядка записей не зависит.

    age_tolerance_hours — политика, а не измерение. Умолчание 1.0 значит:
    в пределах часа содержимое считается одинаково свежим. Числа, полученного
    замером, здесь нет.
    """
    records = list(records)
    if not records:
        return {}
    order = canonical_order(records)
    solved = _solved_ages(records)
    kept_ages: dict[str, list[float | None]] = defaultdict(list)
    decisions: dict[str, tuple[bool, str]] = {}
    for provider in order:
        cells = solved.get(provider) or {}
        if not cells:
            decisions[provider] = (False, "нет успешных клеток")
            continue
        useful: list[tuple[str, float | None, list[float | None]]] = []
        for cell, age in cells.items():
            held = kept_ages.get(cell, [])
            if held and any(_comparable(other, age, age_tolerance_hours) for other in held):
                continue
            useful.append((cell, age, held))
        if not useful:
            decisions[provider] = (False, "клетки уже покрыты в сопоставимом качестве")
        else:
            parts = []
            for cell, age, held in useful:
                if held and age is not None:
                    older = [item for item in held if item is not None]
                    if older:
                        delta = min(older) - age
                        parts.append(f"клетка `{cell}` свежее на {delta:.1f} ч")
                        continue
                parts.append(f"клетка `{cell}`")
            decisions[provider] = (True, "; ".join(parts))
            for cell, age in cells.items():
                kept_ages[cell].append(age)
    return decisions
