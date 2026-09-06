"""Collect only observed reproducibility metadata through an injected reader."""
from __future__ import annotations

FIELDS = ('date', 'kernel', 'docker_version', 'egress_ip', 'asn')


def collect(*, reader) -> dict:
    """reader(field_name) returns an observed string or raises on unavailable data."""
    result = {}
    for field in FIELDS:
        try:
            value = reader(field)
        except Exception:
            value = None
        result[field] = value.strip() if isinstance(value, str) and value.strip() else 'unknown'
    return result
