"""Чекер M28: образы провайдеров в /health и --check-deploy, любой провайдер в bizprofile.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона (без
сети и без Docker: docker подменяется на уровне subprocess.run):
  python3 docs/specs/checks/m28_provider_images.py      ->  печатает `ok`
"""
import contextlib
import dataclasses
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

FAILURES = []
ROUTE = ['abg-curl_cffi:m2', 'abg-patchright:m2', 'abg-rss:m4', 'abg-scrapling:m8',
         'abg-wayback:m4']
FORMAT = '{{.Repository}}:{{.Tag}}'


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: ожидалось {expected!r}, получено {actual!r}")


def argv_for(images):
    argv = ['docker', 'image', 'ls', '--format', FORMAT]
    for image in images:
        argv += ['--filter', 'reference=' + image]
    return argv


class Docker:
    """subprocess.run stand-in: answers `docker image ls` from a set of present tags."""

    def __init__(self, present, rc=0, error=None, delay=0.0):
        self.present, self.rc, self.error, self.delay = set(present), rc, error, delay
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, argv, **kwargs):
        with self.lock:
            self.calls.append((list(argv), dict(kwargs)))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        refs = [argv[i + 1].split('=', 1)[1] for i, a in enumerate(argv) if a == '--filter']
        lines = ''.join(ref + '\n' for ref in refs if ref in self.present)
        return subprocess.CompletedProcess(argv, self.rc, lines + '<none>:<none>\n', '')


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def module_checks():
    try:
        from gateway import provider_images as pi
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"gateway.provider_images не импортируется: {type(exc).__name__}: {exc}")
        return None
    from bench.providers import registry

    check("route_images()", list(pi.route_images()), ROUTE)
    original = registry._BY_NAME['rss']
    registry._BY_NAME['rss'] = dataclasses.replace(original, image='abg-m28-absent:never')
    try:
        check("route_images() берёт образ из реестра в момент вызова",
              list(pi.route_images()), sorted(ROUTE[:2] + ['abg-m28-absent:never'] + ROUTE[3:]))
    finally:
        registry._BY_NAME['rss'] = original
    import gateway.product as product
    real_plan = product.plan_product

    def wider_plan(request):
        return real_plan(request) + (dataclasses.replace(real_plan(request)[0], provider='camoufox'),)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(product, 'plan_product', wider_plan))
        if hasattr(pi, 'plan_product'):
            stack.enter_context(patch.object(pi, 'plan_product', wider_plan))
        check("route_images() берёт состав маршрута из plan_product в момент вызова",
              list(pi.route_images()), sorted(ROUTE + ['abg-camoufox:m2']))

    def make(docker, clock=None, images=None):
        return pi.ImageCheck(images, run=docker, clock=clock or Clock())

    docker = Docker(ROUTE)
    probe = make(docker)
    check("конструктор не вызывает docker", docker.calls, [])
    check("все образы есть", probe.status(), {'ok': True})
    check("один вызов docker image ls на проверку", [c[0] for c in docker.calls], [argv_for(ROUTE)])
    if docker.calls:
        kwargs = docker.calls[0][1]
        check("timeout вызова", kwargs.get('timeout'), 3.0)
        check("capture_output", kwargs.get('capture_output'), True)
        check("text", kwargs.get('text'), True)

    docker = Docker(['abg-curl_cffi:m2', 'abg-patchright:m2', 'abg-scrapling:m8'])
    check("два образа отсутствуют", make(docker).status(),
          {'ok': False, 'error': 'provider_images_missing',
           'missing': ['abg-rss:m4', 'abg-wayback:m4']})
    docker = Docker(ROUTE)
    check("явный список образов", make(docker, images=('b:1', 'a:1')).status(),
          {'ok': False, 'error': 'provider_images_missing', 'missing': ['a:1', 'b:1']})
    check("явный список сортируется в argv", [c[0] for c in docker.calls], [argv_for(['a:1', 'b:1'])])

    unknown = {'ok': False, 'error': 'provider_images_unknown'}
    for label, docker in (("rc=1", Docker(ROUTE, rc=1)),
                          ("TimeoutExpired", Docker(ROUTE, error=subprocess.TimeoutExpired('docker', 3))),
                          ("OSError", Docker(ROUTE, error=FileNotFoundError('docker'))),
                          ("ValueError", Docker(ROUTE, error=ValueError('x')))):
        try:
            check(f"сбой docker ({label})", make(docker).status(), unknown)
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"сбой docker ({label}): status() бросил {type(exc).__name__}")

    clock, docker = Clock(), Docker(['abg-curl_cffi:m2'])
    probe = make(docker, clock)
    first = probe.status()
    first.setdefault('missing', []).append('mutated-by-caller')
    clock.now += 14.9
    second = probe.status()
    check("кэш 15 с: вызовов за 14.9 с", len(docker.calls), 1)
    check("кэш не портится вызывающим", second.get('missing'), ROUTE[1:])
    docker.present = set(ROUTE)
    clock.now = 1000.0 + 15.0
    check("после 15 с проверка заново и выздоровление", probe.status(), {'ok': True})
    check("вызовов после истечения кэша", len(docker.calls), 2)
    clock.now += 1.0
    probe.status()
    check("положительный результат тоже кэшируется", len(docker.calls), 2)

    clock, docker = Clock(), Docker(ROUTE, rc=1)
    probe = make(docker, clock)
    probe.status()
    clock.now += 5
    probe.status()
    check("сбой тоже кэшируется", len(docker.calls), 1)

    docker = Docker(ROUTE, delay=0.3)
    probe = make(docker)
    results, start = [], threading.Barrier(8)

    def worker():
        start.wait()
        results.append(probe.status())
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    check("одновременные /health — один вызов docker", len(docker.calls), 1)
    check("одновременные /health — все получили ответ", results, [{'ok': True}] * 8)
    return pi


def request(port, path='/health'):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read())


@contextlib.contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def api_checks():
    from gateway.httpapi import make_server
    token = 'm28-token'
    missing = {'ok': False, 'error': 'provider_images_missing', 'missing': ['abg-rss:m4']}
    with serving(make_server(('127.0.0.1', 0), token=token)) as port:
        check("без health_check /health прежний", request(port), (200, {'ok': True}))
    with serving(make_server(('127.0.0.1', 0), token=token,
                             health_check=lambda: {'ok': True})) as port:
        check("health_check ok", request(port), (200, {'ok': True}))
    with serving(make_server(('127.0.0.1', 0), token=token,
                             health_check=lambda: dict(missing))) as port:
        check("health_check missing -> 503", request(port), (503, missing))

    def boom():
        raise RuntimeError('boom')
    with serving(make_server(('127.0.0.1', 0), token=token, health_check=boom)) as port:
        check("health_check бросил -> 503", request(port),
              (503, {'ok': False, 'error': 'provider_images_unknown'}))
    try:
        make_server(('127.0.0.1', 0), token=token, health_check='not-callable')
        FAILURES.append("make_server принял health_check='not-callable'")
    except ValueError:
        pass


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def service_checks():
    from gateway import service
    with tempfile.TemporaryDirectory() as tmp:
        token, profiles = Path(tmp) / 'token', Path(tmp) / 'proxies.toml'
        write_private(token, 'm28-token\n')
        write_private(profiles, '[profile.p1]\nurl = "http://proxy.invalid:3128"\n')
        env = dict(ABG_TOKEN_FILE=str(token), ABG_PROFILES_FILE=str(profiles),
                   ABG_INSTANCE='m28-check', ABG_BIND='127.0.0.1', ABG_PORT='0')
        for present, expected in ((ROUTE, (200, {'ok': True})),
                                  (ROUTE[:-1], (503, {'ok': False, 'error': 'provider_images_missing',
                                                      'missing': ['abg-wayback:m4']}))):
            docker = Docker(present)
            with patch.object(subprocess, 'run', side_effect=docker):
                server = service.make_service(env, fetcher_factory=lambda *a, **k: None)
                check("make_service не зовёт docker при сборке", docker.calls, [])
                with serving(server) as port:
                    check(f"make_service /health ({len(present)} из 5)", request(port), expected)
                    request(port)
            check("make_service: argv и один вызов на два /health подряд",
                  [c[0] for c in docker.calls], [argv_for(ROUTE)])


def deployed_checks():
    import tests.deployed_m12b as d
    check("PROVIDER_IMAGES", list(getattr(d, 'PROVIDER_IMAGES', ())), ROUTE)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        service_root, evidence = root / 'service', root / 'evidence'
        service_root.mkdir()

        def main(args):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(d.sys, 'argv', ['deployed_m12b.py', *args]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = d.main()
            return rc, out.getvalue(), err.getvalue()

        base = ['--release', 'a' * 40, '--evidence', str(evidence),
                '--service-root', str(service_root)]
        for present, expected in ((ROUTE[:3], ['abg-scrapling:m8', 'abg-wayback:m4']),
                                  (ROUTE, None)):
            calls, order = [], []

            def docker(*args, **kwargs):
                calls.append(list(args))
                order.append(('docker', kwargs.get('timeout')))
                if list(args[:2]) == ['image', 'ls']:
                    return ''.join(i + '\n' for i in present)
                raise d.CheckError('unexpected_docker_call')
            with patch.object(d, 'verify_release', side_effect=lambda *a: order.append('verify')), \
                    patch.object(d, 'docker', side_effect=docker), \
                    patch.object(d.subprocess, 'run', side_effect=AssertionError('subprocess')):
                rc, out, err = main(['--check-deploy', *base])
            check(f"check-deploy: вызовы docker ({len(present)} из 5)", calls[:1],
                  [argv_for(ROUTE)[1:]])
            check(f"check-deploy: verify_release до docker, timeout=30 ({len(present)} из 5)",
                  order[:2], ['verify', ('docker', 30)])
            result_file = evidence / 'check_deploy-result.json'
            if expected:
                failure = {'ok': False, 'internal_error': 'provider_images_missing',
                           'missing_images': expected}
                check("check-deploy без образов: rc", rc, 1)
                check("check-deploy без образов: stderr", _json(err), failure)
                check("check-deploy без образов: stdout пуст", out, '')
                check("check-deploy без образов: файл результата", _json_file(result_file), failure)
                check("check-deploy без образов: дальше не идёт", len(calls), 1)
            else:
                check("check-deploy с образами идёт дальше (compose.env нет)", _json(err),
                      {'ok': False, 'internal_error': 'FileNotFoundError'})

        pages = ('home', 'card')
        markers = {'https://bizprofile.net/': True,
                   'https://bizprofile.net/ny/albany/elevate-electric-llc': True}

        def run_biz(values):
            rows = iter(values)

            def worker_call(action, **payload):
                assert action == 'bizprofile'
                value = next(rows)
                return {'api_evidence': value, 'marker_found': markers[payload['request']['url']]}
            biz_evidence = root / ('biz-' + str(len(list(root.iterdir()))))
            args = ['--check-bizprofile', '--release', 'a' * 40, '--evidence', str(biz_evidence)]
            with patch.object(d, 'worker_call', side_effect=worker_call), \
                    patch.object(d, 'wait_gap', return_value=None):
                rc, out, err = main(args)
            return rc, out, err, biz_evidence

        rc, out, err, folder = run_biz([evidence_value('curl_cffi'), evidence_value('scrapling')])
        providers = {'home': 'curl_cffi', 'card': 'scrapling'}
        check("bizprofile любой провайдер: rc", rc, 0)
        check("bizprofile: stdout", _json(out),
              {'ok': True, 'mode': 'check_bizprofile', 'providers': providers})
        check("bizprofile: файл результата", _json_file(folder / 'check_bizprofile-result.json'),
              {'ok': True, 'providers': providers})
        latest = _json_file(folder / 'bizprofile.json') or {}
        check("bizprofile.json: provider у страниц",
              [row.get('provider') for row in latest.get('pages', [])], ['curl_cffi', 'scrapling'])
        check("bizprofile.json: id страниц", [row.get('id') for row in latest.get('pages', [])],
              list(pages))

        failed = evidence_value(None, ok=False)
        rc, out, err, folder = run_biz([evidence_value('curl_cffi'), failed])
        check("bizprofile провал: rc", rc, 1)
        biz_failure = {'ok': False, 'internal_error': 'bizprofile_not_passed',
                       'providers': {'home': 'curl_cffi', 'card': None}}
        check("bizprofile провал: stderr", _json(err), biz_failure)
        check("bizprofile провал: файл результата",
              _json_file(folder / 'check_bizprofile-result.json'), biz_failure)
        check("bizprofile провал: stdout пуст", out, '')
        mismatch = evidence_value('scrapling')
        mismatch['attempts'][-1]['provider'] = 'curl_cffi'
        for label, bad in (("провайдер ответа не совпал с последней попыткой", mismatch),
                           ("пустой провайдер", evidence_value('')),
                           ("challenge != none", evidence_value('curl_cffi', challenge='suspected'))):
            rc, out, err, folder = run_biz([evidence_value('curl_cffi'), bad])
            check(f"bizprofile {label}: rc", rc, 1)
            check(f"bizprofile {label}: код", (_json(err) or {}).get('internal_error'),
                  'bizprofile_not_passed')


def evidence_value(provider, ok=True, challenge='none'):
    attempt = dict(provider=provider or 'curl_cffi', egress_profile='direct', status=200 if ok else 403,
                   success=ok, challenge=challenge, error_type='none' if ok else 'http_403',
                   elapsed_ms=10, age_hours=None, next_step='stop' if ok else 'human')
    return dict(ok=ok, provider=provider, error_type='none' if ok else 'http_403',
                step='stop' if ok else 'human', elapsed_ms=10, attempts=[attempt])


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return f"не JSON: {text[:300]!r}"


def _json_file(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return f"{path.name}: {type(exc).__name__}"


def main():
    for step in (module_checks, api_checks, service_checks, deployed_checks):
        try:
            step()
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"{step.__name__}: {type(exc).__name__}: {exc}")
    if FAILURES:
        print("FAIL")
        for line in FAILURES:
            print(" - " + line)
        return 1
    print("ok")
    return 0


if __name__ == '__main__':
    sys.exit(main())
