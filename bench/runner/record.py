"""JSONL run records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields

from bench.models import ChallengeType, FailureReason

_ALLOWED_MODES = frozenset({"cold", "warm"})


@dataclass(frozen=True, slots=True)
class RunRecord:
    provider: str
    provider_version: str
    scenario: str | None
    target: str | None
    run_id: str
    mode: str
    success: bool
    sentinel_found: bool
    status: int | None
    final_url: str
    challenge_type: ChallengeType
    elapsed_ms: int
    startup_ms: int
    cpu_ms: int
    peak_rss_mb: float
    bytes: int
    redirects: int
    error_type: FailureReason
    date: str
    kernel: str
    docker_version: str
    image_version: str
    egress_ip: str
    asn: str
    cell: str


def validate(record: RunRecord) -> None:
    for item in fields(record):
        if not hasattr(record, item.name):
            raise ValueError(f"missing field: {item.name}")
    if record.mode not in _ALLOWED_MODES:
        raise ValueError(f"mode must be 'cold' or 'warm', got {record.mode!r}")
    if record.elapsed_ms < 0:
        raise ValueError(f"elapsed_ms must be >= 0, got {record.elapsed_ms}")
    if record.success and record.error_type != FailureReason.none:
        raise ValueError(
            f"success=True requires error_type=none, got {record.error_type}"
        )


def to_jsonl_line(record: RunRecord) -> str:
    validate(record)
    return json.dumps(asdict(record), ensure_ascii=False) + "\n"


def from_jsonl_line(line: str) -> RunRecord:
    raw = json.loads(line)
    if not isinstance(raw, dict):
        raise ValueError("JSONL line must be an object")
    missing = [item.name for item in fields(RunRecord) if item.name not in raw]
    if missing:
        raise ValueError("missing field: " + ", ".join(missing))
    record = RunRecord(
        provider=raw["provider"],
        provider_version=raw["provider_version"],
        scenario=raw["scenario"],
        target=raw["target"],
        run_id=raw["run_id"],
        mode=raw["mode"],
        success=raw["success"],
        sentinel_found=raw["sentinel_found"],
        status=raw["status"],
        final_url=raw["final_url"],
        challenge_type=ChallengeType(raw["challenge_type"]),
        elapsed_ms=raw["elapsed_ms"],
        startup_ms=raw["startup_ms"],
        cpu_ms=raw["cpu_ms"],
        peak_rss_mb=raw["peak_rss_mb"],
        bytes=raw["bytes"],
        redirects=raw["redirects"],
        error_type=FailureReason(raw["error_type"]),
        date=raw["date"],
        kernel=raw["kernel"],
        docker_version=raw["docker_version"],
        image_version=raw["image_version"],
        egress_ip=raw["egress_ip"],
        asn=raw["asn"],
        cell=raw["cell"],
    )
    validate(record)
    return record
