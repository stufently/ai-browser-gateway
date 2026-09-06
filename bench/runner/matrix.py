"""Deterministic, stateless provider × cell × mode plans."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanItem:
    provider: str
    cell: str
    mode: str
    index: int

    @property
    def run_id(self) -> str:
        return f'{self.provider}:{self.cell}:{self.mode}:{self.index}'


def build_plan(providers, cells, *, cold: int, warm: int) -> list[PlanItem]:
    for count in (cold, warm):
        if type(count) is not int or count < 0:
            raise ValueError('cold and warm must be nonnegative integers')
    providers, cells = tuple(providers), tuple(cells)
    if len({p.name for p in providers}) != len(providers) or len(set(cells)) != len(cells):
        raise ValueError('duplicate providers or cells would produce duplicate run IDs')
    plan = []
    for provider in providers:
        for cell in cells:
            modes = [('cold', cold)]
            if provider.kind == 'browser':
                modes.append(('warm', warm))
            for mode, count in modes:
                plan.extend(PlanItem(provider.name, cell, mode, index) for index in range(count))
    if len({item.run_id for item in plan}) != len(plan):
        raise ValueError('ambiguous provider/cell names produce duplicate run IDs')
    return plan
