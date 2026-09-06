"""Incremental coverage: what a provider adds to cheaper ones already kept."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoverageRow:
    provider: str
    solved: int
    incremental: int
    unique: int
    total_cells: int


def solved_cells(records) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for record in records:
        if record.success:
            out.setdefault(record.provider, set()).add(record.cell)
    return out


def incremental(records, order: list[str]) -> list[CoverageRow]:
    records = list(records)
    by_provider = solved_cells(records)
    unknown = {record.provider for record in records} - set(order)
    if unknown:
        raise ValueError("providers missing from order: " + ", ".join(sorted(unknown)))
    all_cells: set[str] = set()
    holders: dict[str, set[str]] = {}
    for record in records:
        all_cells.add(record.cell)
        if record.success:
            holders.setdefault(record.cell, set()).add(record.provider)
    unique_map: dict[str, set[str]] = {name: set() for name in order}
    for cell, who in holders.items():
        if len(who) == 1:
            unique_map[next(iter(who))].add(cell)
    total = len(all_cells)
    already: set[str] = set()
    rows: list[CoverageRow] = []
    for provider in order:
        solved = by_provider.get(provider, set())
        added = solved - already
        already |= solved
        rows.append(
            CoverageRow(
                provider=provider,
                solved=len(solved),
                incremental=len(added),
                unique=len(unique_map[provider]),
                total_cells=total,
            )
        )
    return rows


def keep_decision(row: CoverageRow, threshold: float = 0.05) -> tuple[bool, str]:
    ratio = (row.incremental / row.total_cells) if row.total_cells else 0.0
    if ratio >= threshold:
        return True, (
            f"incremental {row.incremental}/{row.total_cells} = {ratio:.4f} >= {threshold}"
        )
    if row.unique > 0:
        return True, f"unique cells {row.unique} > 0"
    return False, f"incremental {ratio:.4f} < {threshold} and unique = 0"
