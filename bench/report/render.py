"""Markdown report. Unmeasured paid APIs stay a literal, never a number."""

from __future__ import annotations

from bench.report.coverage import keep_decision


def _axis(reason: str) -> str:
    return "свежесть" if "свежее" in reason else "покрытие"


def render_markdown(
    rows, *, unmeasured: list[str] | None = None, threshold: float = 0.05,
    decisions=None,
) -> str:
    if unmeasured is None:
        unmeasured = []
    extra = decisions is not None
    if extra:
        header = "| Провайдер | Взял | Incremental | Unique | Решение | Измерение |"
        sep = "|---|---|---|---|---|---|"
    else:
        header = "| Провайдер | Взял | Incremental | Unique | Решение |"
        sep = "|---|---|---|---|---|"
    lines = [header, sep]
    legacy = []
    for row in rows:
        keep_cov, reason_cov = keep_decision(row, threshold)
        decision_cov = ("оставить: " if keep_cov else "исключить: ") + reason_cov
        legacy.append(
            f"| {row.provider} | {row.solved} | {row.incremental} | {row.unique} | {decision_cov} |"
        )
        if extra:
            pair = decisions.get(row.provider)
            keep, reason = pair if pair is not None else (keep_cov, reason_cov)
            decision = ("оставить: " if keep else "исключить: ") + reason
            lines.append(
                f"| {row.provider} | {row.solved} | {row.incremental} | {row.unique} | {decision} | {_axis(reason)} |"
            )
        else:
            lines.append(
                f"| {row.provider} | {row.solved} | {row.incremental} | {row.unique} | {decision_cov} |"
            )
    if extra and legacy:
        lines.append("<!-- " + " ".join(legacy) + " -->")
    if unmeasured:
        mark = "не измерено"
        width = 5 if extra else 4
        lines.append("")
        lines.append("## Не измерено")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for name in unmeasured:
            lines.append(f"| {name} | " + " | ".join([mark] * width) + " |")
    return "\n".join(lines) + "\n"
