"""Стенд M28 внутри рантайм-образа сервиса: настоящий docker-сокет хоста.

Запускается только из m28_stand.sh. Собирает сервис make_service() из клона
(без main(): никакой зачистки контейнеров, свой ABG_INSTANCE), поднимает его на
127.0.0.1 со случайным портом и прогоняет ДОСЛОВНУЮ команду healthcheck из
deploy/compose.yaml. Сценарий absent подменяет в реестре образ rss на заведомо
отсутствующий тег: остальные четыре образа маршрута ищутся в настоящем docker.
Печатает `ok` или `FAIL ...`; `blocked ...` и код 3 — если на хосте нет
образов маршрута (стенд тогда ничего не доказывает).
"""
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path('/work')
sys.path.insert(0, str(ROOT))
ROUTE = ['abg-curl_cffi:m2', 'abg-patchright:m2', 'abg-rss:m4', 'abg-scrapling:m8',
         'abg-wayback:m4']
ABSENT = 'abg-m28-absent:never'


def healthcheck_argv(port):
    for line in (ROOT / 'deploy/compose.yaml').read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith('test: ["CMD"'):
            argv = json.loads(stripped[len('test: '):])[1:]
            break
    else:
        raise SystemExit('FAIL healthcheck not found in deploy/compose.yaml')
    url = 'http://127.0.0.1:8765/health'
    if sum(url in part for part in argv) != 1:
        raise SystemExit('FAIL healthcheck URL changed')
    return [part.replace(url, f'http://127.0.0.1:{port}/health') for part in argv]


def get_health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read())


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def main():
    scenario = os.environ.get('M28_SCENARIO')
    if scenario not in ('present', 'absent'):
        raise SystemExit('FAIL scenario must be present or absent')
    listed = subprocess.run(
        ['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}',
         *[arg for image in ROUTE for arg in ('--filter', 'reference=' + image)]],
        capture_output=True, text=True, timeout=10)
    have = set(listed.stdout.split())
    if listed.returncode != 0 or not set(ROUTE) <= have:
        print('blocked: route images on host: ' + ','.join(sorted(have)) + ' ' + listed.stderr.strip())
        return 3
    if scenario == 'absent':
        from bench.providers import registry
        registry._BY_NAME['rss'] = dataclasses.replace(registry._BY_NAME['rss'], image=ABSENT)
        expected_body = {'ok': False, 'error': 'provider_images_missing', 'missing': [ABSENT]}
        expected = (503, expected_body, 1)
    else:
        expected = (200, {'ok': True}, 0)
    write_private('/tmp/token', 'm28-stand-token\n')
    write_private('/tmp/proxies.toml', '[profile.p1]\nurl = "http://proxy.invalid:3128"\n')
    env = dict(ABG_TOKEN_FILE='/tmp/token', ABG_PROFILES_FILE='/tmp/proxies.toml',
               ABG_INSTANCE='m28-stand', ABG_BIND='127.0.0.1', ABG_PORT='0')
    from gateway.service import make_service
    server = make_service(env)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        start = time.monotonic()
        status, body = get_health(port)
        first_ms = int((time.monotonic() - start) * 1000)
        hc = subprocess.run(healthcheck_argv(port), capture_output=True, text=True, timeout=10)
    finally:
        server.shutdown()
        server.server_close()
    actual = (status, body, hc.returncode)
    problems = []
    if actual != expected:
        problems.append(f'expected {expected!r}, got {actual!r}')
    if first_ms >= 3500:
        problems.append(f'first /health took {first_ms} ms')
    if problems:
        print('FAIL ' + scenario + ': ' + '; '.join(problems))
        return 1
    print('ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
