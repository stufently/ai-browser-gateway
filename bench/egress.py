"""Proxy profiles from a credentials file that is never committed."""
from __future__ import annotations

import tomllib
from pathlib import Path


def load_profiles(path) -> dict[str, str]:
    """Имя профиля -> URL. Файла нет — пустой словарь, это не ошибка."""
    path = Path(path)
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        return {}
    if mode & 0o077:
        raise PermissionError("credentials file is group- or world-accessible")
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except (tomllib.TOMLDecodeError, OSError):
        raise ValueError("invalid credentials file") from None
    raw = data.get("profile", {})
    if not isinstance(raw, dict):
        raise ValueError("invalid credentials file")
    profiles = {}
    for name, body in raw.items():
        if not isinstance(name, str) or not isinstance(body, dict):
            raise ValueError("invalid credentials file")
        url = body.get("url", "")
        if url is None:
            url = ""
        if not isinstance(url, str):
            raise ValueError("invalid credentials file")
        profiles[name] = url
    return profiles


def profile_url(profiles, name) -> str | None:
    """None означает «профиля нет или он пуст» — то есть НЕ ИЗМЕРЕНО."""
    url = profiles.get(name)
    if not url:
        return None
    return url
