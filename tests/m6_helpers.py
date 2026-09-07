"""Synthetic M6 records with the measured ages from the spec, not live runs."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bench.models import FailureReason
from bench.runner.record import to_jsonl_line
from tests.m4_helpers import record

# Ages and cpu medians from the M6 spec ("Задача и почему"), not invented.
RSS_AGE = 0.0172
WAYBACK_AGE = 431.86
RSS_CPU_MS = 933
WAYBACK_CPU_MS = 986
CURL_CPU_MS = 659
LOWENDTALK = "target:cf-lowendtalk"
BIZPROFILE = "target:cf-bizprofile"

_KEEP_TEMPS: list[tempfile.TemporaryDirectory] = []


def fixture_records():
    return [
        record(
            "wayback",
            LOWENDTALK,
            entrance_age_hours=WAYBACK_AGE,
            cpu_ms=WAYBACK_CPU_MS,
        ),
        record(
            "wayback",
            BIZPROFILE,
            entrance_age_hours=WAYBACK_AGE,
            cpu_ms=WAYBACK_CPU_MS,
        ),
        record(
            "rss",
            LOWENDTALK,
            entrance_age_hours=RSS_AGE,
            cpu_ms=RSS_CPU_MS,
        ),
        record(
            "rss",
            BIZPROFILE,
            success=False,
            error_type=FailureReason.not_measured,
            cpu_ms=RSS_CPU_MS,
        ),
        record(
            "curl",
            LOWENDTALK,
            success=False,
            error_type=FailureReason.http_403,
            cpu_ms=CURL_CPU_MS,
        ),
        record(
            "curl",
            BIZPROFILE,
            success=False,
            error_type=FailureReason.http_403,
            cpu_ms=CURL_CPU_MS,
        ),
    ]


def write_real_run():
    stored = tempfile.TemporaryDirectory(prefix="m6-run-")
    _KEEP_TEMPS.append(stored)
    path = Path(stored.name) / "run.jsonl"
    path.write_text("".join(to_jsonl_line(item) for item in fixture_records()), encoding="utf-8")
    return path
