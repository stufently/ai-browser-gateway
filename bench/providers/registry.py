"""Immutable provider registry and Docker wire-format helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    image: str
    tier: int
    kind: Literal['http', 'browser', 'entrance']
    needs_network: bool
    argv_extra: tuple[str, ...] = ()


PROVIDERS: tuple[Provider, ...] = (
    Provider('curl', 'abg-curl:m2', 0, 'http', True),
    Provider('curl_cffi', 'abg-curl_cffi:m2', 1, 'http', True),
    Provider('primp', 'abg-primp:m2', 1, 'http', True),
    Provider('playwright', 'abg-playwright:m2', 2, 'browser', True),
    Provider('patchright', 'abg-patchright:m2', 2, 'browser', True),
    Provider('scrapling', 'abg-scrapling:m8', 2, 'browser', True),
    Provider('camoufox', 'abg-camoufox:m2', 3, 'browser', True),
    Provider('pydoll', 'abg-pydoll:m2', 3, 'browser', True),
    Provider('wayback', 'abg-wayback:m4', 0, 'entrance', True),
    Provider('rss', 'abg-rss:m4', 0, 'entrance', True),
)
_BY_NAME = {provider.name: provider for provider in PROVIDERS}


def by_name(name: str) -> Provider:
    return _BY_NAME[name]


def build_argv(provider: Provider, *, url: str, sentinel: str | None = None, network=None,
               proxy_env: str | None = None, probe_bind=None,
               include_content: bool = False, budget_ms: int | None = None,
               content_only: bool = False) -> list[str]:
    """argv_extra holds Docker options, never shell fragments or probe arguments."""
    argv = ['docker', 'run', '--rm', '--user', '1002:1002']
    if provider.kind == 'browser':
        argv.append('--shm-size=1g')
    if network is not None:
        argv.extend(['--network', network])
    argv.extend(provider.argv_extra)
    if proxy_env is not None:
        argv.extend(['--env', proxy_env])
    if probe_bind is not None:
        source = str(Path(probe_bind).resolve())
        target = '/opt/abg' if Path(source).is_dir() else '/opt/abg/probe.py'
        argv.extend(['--mount', f'type=bind,source={source},target={target},readonly'])
    if not content_only and (not isinstance(sentinel, str) or not sentinel):
        raise ValueError('invalid sentinel')
    argv.extend([provider.image, url])
    if content_only:
        argv.append('--content-only')
    else:
        argv.append(sentinel)
    if include_content:
        argv.append('--include-content')
    if budget_ms is not None:
        argv.extend(['--budget-ms', str(budget_ms)])
    return argv


def parse_output(provider: Provider, stdout: str) -> dict:
    """A broken last JSON line is a failure even if an earlier line was valid."""
    # One-line JSON from json.dumps(ensure_ascii=False) may contain U+0085,
    # U+2028, or U+2029. splitlines() would split inside that payload.
    candidates = [line for line in stdout.split('\n') if line.startswith('{')]
    try:
        payload = json.loads(candidates[-1]) if candidates else None
        if not isinstance(payload, dict):
            raise ValueError('expected a JSON object')
        return payload
    except (ValueError, IndexError) as exc:
        raise ValueError(f'{provider.name}: invalid probe output: {stdout[:200]}') from exc
