"""Markdown report. Unmeasured paid APIs stay a literal, never a number."""

from __future__ import annotations

from bench.report.coverage import keep_decision


def render_markdown(
    rows, *, unmeasured: list[str] | None = None, threshold: float = 0.05
) -> str:
    if unmeasured is None:
        unmeasured = []
    header = "| Провайдер | Взял | Incremental | Unique | Решение |"
    sep = "|---|---|---|---|---|"
    lines = [header, sep]
    for row in rows:
        keep, reason = keep_decision(row, threshold)
        decision = ("оставить: " if keep else "исключить: ") + reason
        lines.append(
            f"| {row.provider} | {row.solved} | {row.incremental} | {row.unique} | {decision} |"
        )
    if unmeasured:
        mark = "не измерено"
        lines.append("")
        lines.append("## Не измерено")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for name in unmeasured:
            lines.append(f"| {name} | {mark} | {mark} | {mark} | {mark} |")
    return "\n".join(lines) + "\n"
