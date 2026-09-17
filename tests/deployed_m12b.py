#!/usr/bin/env python3
"""Read-only deployed checks; all HTTP runs in Docker, never on the host.

Only sanitized allowlisted evidence crosses the container boundary. The ping
file is never opened here. No service lifecycle operations or target retries.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

SHA = '929bded313e371808b0747fd9a400696a36638aa'
ROOT = Path(__file__).resolve().parent.parent
SERVICE = Path('/home/user/services/ai-browser-gateway')
RELEASE = SERVICE / 'releases' / SHA
EVIDENCE = Path('/home/user/.cache/abg-coord-20260917/m12b')
PY = 'sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'
IMAGE = 'abg-runtime:' + SHA[:12]
NAMES = tuple('ms' + str(i) for i in range(1, 16))
ECHO = 'http://api.ipify.org'
API = 'http://127.0.0.1:8765'
ATTEMPT_KEYS = ('provider', 'egress_profile', 'status', 'success', 'challenge',
                'error_type', 'elapsed_ms', 'age_hours', 'next_step')


class CheckError(Exception):
    """Static, non-secret internal failure code."""


def require(condition, code):
    if not condition:
        raise CheckError(code)


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {redact(str(k), secrets): redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, '[redacted]')
    value = re.sub(r'https?://[^\s<>"\']+', '[url]', value, flags=re.I)
    value = re.sub(r'(?i)\bBearer\s+[^\s"\']+', 'Bearer [redacted]', value)
    value = re.sub(r'(?i)\b(token|password|ping)\s*[=:]\s*[^\s,"\']+', r'\1=[redacted]', value)
    return re.sub(r'\b[0-9a-fA-F]{64}\b', '[redacted]', value)


def docker(*args, input=None, timeout=200):
    try:
        result = subprocess.run(['docker', *args], input=input, capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise CheckError('docker_unavailable') from None
    require(result.returncode == 0, 'docker_failed')
    return result.stdout


def parse_api(status, body):
    require(status == 200, 'api_http_error')
    try:
        value = json.loads(body)
    except (ValueError, TypeError):
        raise CheckError('api_invalid_json') from None
    require(isinstance(value, dict) and type(value.get('ok')) is bool
            and isinstance(value.get('content'), str)
            and type(value.get('elapsed_ms')) is int
            and isinstance(value.get('error_type'), str)
            and isinstance(value.get('step'), str), 'api_invalid_schema')
    attempts = value.get('attempts')
    require(isinstance(attempts, list), 'api_invalid_attempts')
    for a in attempts:
        require(isinstance(a, dict) and all(k in a for k in ATTEMPT_KEYS), 'api_invalid_attempts')
        require(a['egress_profile'] in ('direct', *NAMES)
                and isinstance(a['provider'], str) and type(a['success']) is bool
                and (a['status'] is None or type(a['status']) is int)
                and type(a['elapsed_ms']) is int and a['elapsed_ms'] >= 0
                and isinstance(a['challenge'], str) and isinstance(a['error_type'], str),
                'api_invalid_attempts')
    return value


def api_evidence(value):
    return redact({k: value.get(k) for k in
                   ('ok', 'provider', 'error_type', 'step', 'elapsed_ms')} | {
                       'attempts': [{k: a[k] for k in ATTEMPT_KEYS} for a in value['attempts']]})


def echo_result(status, body):
    result = dict(status=status, ip=None, error=None)
    if status == 200:
        try:
            result['ip'] = str(ipaddress.ip_address(body.strip()))
        except ValueError:
            result['error'] = 'invalid_ip'
    return result


def classify_profiles(rows, direct):
    counts = Counter(r['ip'] for r in rows if r['ip'])
    output = []
    for row in rows:
        failure = row['error']
        if not failure and row['status'] != 200:
            failure = 'http_' + str(row['status'])
        if not failure and row['ip'] == direct:
            failure = 'direct_ip'
        if not failure and counts[row['ip']] > 1:
            failure = 'duplicate_ip'
        output.append(row | {'failure_class': failure})
    return output


def rotation_path(first, working):
    require(first in NAMES and len(working) >= 3 and set(working) <= set(NAMES), 'rotation_pool_invalid')
    path, good = [], 0
    for offset in range(1, 16):
        name = NAMES[(NAMES.index(first) + offset) % len(NAMES)]
        path.append(name)
        good += name in working
        if good == 2:
            return path
    raise CheckError('rotation_pool_invalid')


def first_egress(value):
    attempts = value['attempts']
    require(bool(attempts) and attempts[0]['egress_profile'] == 'direct'
            and attempts[0]['status'] == 200
            and attempts[0]['error_type'] == 'content_missing', 'direct_miss_not_proven')
    names = [a['egress_profile'] for a in attempts if a['egress_profile'] != 'direct']
    require(len(names) == 1 and names[0] in NAMES, 'egress_not_proven')
    return names[0]


def assert_egress(value, name, ip):
    require(first_egress(value) == name and value['ok'] is True
            and ip in value['content'] and value['attempts'][-1]['success'] is True,
            'rotation_success_not_proven')


def save(name, value, folder=EVIDENCE):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    path = folder / (name + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def wait_gap(url, folder=EVIDENCE):
    path = folder / 'request-times.json'
    stamps = json.loads(path.read_text()) if path.exists() else {}
    host = urlsplit(url).hostname
    delay = max(0, stamps.get(host, 0) + 30 - time.time())
    if delay:
        time.sleep(delay)
    stamps[host] = time.time()
    save('request-times', stamps, folder)


def worker_call(action, **payload):
    args = ['run', '--rm', '-i', '--user', '1002:1002', '--network', 'host',
            '--read-only', '--tmpfs', '/tmp', '-e', 'HOME=/tmp',
            '-e', 'PYTHONDONTWRITEBYTECODE=1',
            '--mount', f'type=bind,source={Path(__file__).resolve()},target=/runner.py,readonly']
    for secret in ('token', 'proxies.toml'):
        args += ['--mount', f'type=bind,source={SERVICE / "secrets" / secret},target=/run/{secret},readonly']
    raw = docker(*args, PY, 'python3', '-c',
                 'import runpy; runpy.run_path("/runner.py")["worker"]()',
                 input=json.dumps(dict(action=action, **payload)))
    try:
        data = json.loads(raw)
    except ValueError:
        raise CheckError('worker_invalid_json') from None
    require(isinstance(data, dict) and 'internal_error' not in data, 'worker_internal_error')
    return data


def worker():
    """Container entry; raw responses and credentials stay inside the container."""
    import base64
    import http.client
    import socket
    import tomllib
    from urllib.error import HTTPError, URLError
    from urllib.parse import unquote
    from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    echo_network = False
    try:
        data = json.load(sys.stdin)
        action = data['action']
        if action == 'echo':
            name = data.get('name')
            start = time.monotonic()
            if name:
                profiles = tomllib.loads(Path('/run/proxies.toml').read_text())['profile']
                require(tuple(profiles) == NAMES, 'profile_order_invalid')
                proxy = urlsplit(profiles[name]['url'])
                conn = http.client.HTTPConnection(proxy.hostname, proxy.port, timeout=20)
                headers = {}
                if not data.get('no_auth'):
                    creds = unquote(proxy.username or '') + ':' + unquote(proxy.password or '')
                    headers['Proxy-Authorization'] = 'Basic ' + base64.b64encode(creds.encode()).decode()
                echo_network = True
                conn.request('GET', ECHO, headers=headers)
            else:
                conn = http.client.HTTPConnection('api.ipify.org', 80, timeout=20)
                echo_network = True
                conn.request('GET', '/')
            try:
                response = conn.getresponse()
                value = echo_result(response.status, response.read(4096).decode(errors='replace'))
            finally:
                conn.close()
            value['elapsed_ms'] = int((time.monotonic() - start) * 1000)
        elif action in ('api', 'health', 'unauthorized'):
            body = json.dumps(data['request']).encode() if action == 'api' else (b'{}' if action == 'unauthorized' else None)
            headers = {'Content-Type': 'application/json'}
            if action == 'api':
                headers['Authorization'] = 'Bearer ' + Path('/run/token').read_text().strip()
            endpoint = API + ('/health' if action == 'health' else '/v1/fetch')
            opener = build_opener(ProxyHandler({}), NoRedirect)
            try:
                with opener.open(Request(endpoint, data=body, headers=headers), timeout=160) as response:
                    status, raw = response.status, response.read().decode()
            except HTTPError as exc:
                status, raw = exc.code, exc.read().decode()
                exc.close()
            if action == 'api':
                parsed = parse_api(status, raw)
                value = api_evidence(parsed)
                value['expected_found'] = data['request']['expected_text'] in parsed['content']
                # Rotation code consumes only the requested public IP, not page content.
                if data.get('echo'):
                    value['content'] = data['request']['expected_text'] if value['expected_found'] else ''
            else:
                value = {'status': status, 'body': json.loads(raw)}
        elif action == 'scan':
            token = Path('/run/token').read_text().strip()
            text = json.dumps(data['metadata'])
            require(token not in text, 'token_leak')
            require(not re.search(r'https?://[^\s"<>]+:[^\s"<>]+@', text), 'userinfo_leak')
            # Only the documented local health URL may appear in argv/env/logs.
            urls = re.findall(r'https?://[^\s"\'<>\\]+', text)
            require(all(u in ('http://api:8765/health', 'http://127.0.0.1:8765/health') for u in urls), 'unexpected_url_in_metadata')
            value = {'secrets_absent': True}
        else:
            raise CheckError('unknown_worker_action')
    except (TimeoutError, socket.timeout):
        value = dict(status=None, ip=None, error='timeout') if echo_network else {'internal_error': 'worker_timeout'}
    except (OSError, http.client.HTTPException, URLError):
        value = dict(status=None, ip=None, error='connection_error') if echo_network else {'internal_error': 'worker_connection'}
    except Exception:
        value = {'internal_error': 'worker_failure'}
    print(json.dumps(redact(value)))


def fetch(url, expected, browser=True):
    wait_gap(url)
    return worker_call('api', request=dict(url=url, expected_text=expected,
                       allow_browser=browser, budget_ms=120000, format='text', max_age_hours=0),
                       echo=url == ECHO)


def check_profiles():
    evidence = {'release_sha': SHA, 'profiles': []}
    save('profiles', evidence)
    wait_gap(ECHO)
    direct = worker_call('echo')
    evidence['direct'] = direct
    save('profiles', evidence)
    require(direct['status'] == 200 and direct['ip'], 'direct_not_measured')
    for name in NAMES:
        wait_gap(ECHO)
        evidence['profiles'].append(dict(name=name, **worker_call('echo', name=name)))
        save('profiles', evidence)
        print('measured ' + name, flush=True)
    evidence['profiles'] = classify_profiles(evidence['profiles'], direct['ip'])
    wait_gap(ECHO)
    evidence['no_auth'] = worker_call('echo', name='ms1', no_auth=True)
    save('profiles', evidence)
    require(evidence['no_auth']['status'] == 407, 'no_auth_407_missing')
    require(sum(r['failure_class'] is None for r in evidence['profiles']) >= 3,
            'fewer_than_three_unique_working_profiles')


def check_api_egress():
    pool = json.loads((EVIDENCE / 'profiles.json').read_text())
    require(pool['release_sha'] == SHA and len(pool['profiles']) == 15, 'profile_evidence_invalid')
    working = {r['name']: r['ip'] for r in pool['profiles'] if r['failure_class'] is None}
    require(len(working) >= 3, 'fewer_than_three_unique_working_profiles')
    require(len(set(working.values())) == len(working) and pool['direct']['ip'] not in working.values(), 'profile_evidence_invalid')
    evidence = {'requests': []}
    save('api-egress', evidence)
    first = fetch(ECHO, next(iter(working.values())), False)
    evidence['requests'].append(api_evidence(first) | {'kind': 'anchor'})
    save('api-egress', evidence)
    start = first_egress(first)
    for name in rotation_path(start, working):
        value = fetch(ECHO, working.get(name, next(iter(working.values()))), False)
        evidence['requests'].append(api_evidence(value) | {
            'expected_profile': name, 'expected_found': value['expected_found'],
            'kind': 'required_success' if name in working else 'intermediate'})
        save('api-egress', evidence)
        if name in working:
            assert_egress(value, name, working[name])
        # Failed intermediate requests still advance the server's rotation.
    evidence['rotation_proven'] = True
    save('api-egress', evidence)


def run_targets():
    # Host Python may predate tomllib; load the tracked table in pinned Docker.
    raw = docker('run', '--rm', '--user', '1002:1002', '--network', 'none',
                 '--mount', f'type=bind,source={ROOT / "bench/targets/targets.toml"},target=/targets.toml,readonly',
                 PY, 'python3', '-c',
                 'import tomllib,json; print(json.dumps(tomllib.load(open("/targets.toml","rb"))["target"]))')
    targets = [t for t in json.loads(raw) if t.get('valid') is not False]
    require(len(targets) == 6, 'target_count_changed')
    evidence = {'targets': []}
    save('targets', evidence)
    for target in targets:
        value = fetch(target['url'], target['expect'])
        evidence['targets'].append(dict(id=target['id'], **api_evidence(value)))
        save('targets', evidence)
        print(target['id'] + ': ' + ('ok' if value['ok'] else value['error_type']), flush=True)
    wait_gap('https://example.com/')
    env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
    env['ABG_BUDGET_MS'] = '120000'
    result = subprocess.run([str(ROOT / 'scripts/abg-fetch'), 'https://example.com/', 'text'],
                            env=env, capture_output=True, text=True, timeout=180)
    evidence['cli'] = {'rc': result.returncode, 'expected_found': 'Example Domain' in result.stdout}
    save('targets', evidence)
    require(result.returncode == 0 and evidence['cli']['expected_found'], 'cli_failed')


def inspect(ident):
    return json.loads(docker('inspect', ident))[0]


def check_deploy():
    config = {}
    for line in (SERVICE / 'compose.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            require(key not in config, 'duplicate_compose_key')
            config[key] = value
    gid = str(os.stat('/var/run/docker.sock').st_gid)
    expected = dict(ABG_RELEASE=str(RELEASE), ABG_TOKEN_FILE=str(SERVICE / 'secrets/token'),
                    ABG_PROFILES_FILE=str(SERVICE / 'secrets/proxies.toml'),
                    ABG_PING_FILE=str(SERVICE / 'secrets/hc-ping'), ABG_INSTANCE='stand-host',
                    ABG_RUNTIME_IMAGE=IMAGE, ABG_DOCKER_GID=gid, ABG_HOST_PORT='8765',
                    ABG_COMPOSE_PROJECT='ai-browser-gateway')
    require(config == expected, 'compose_env_mismatch')
    require((SERVICE / 'secrets').stat().st_mode & 0o777 == 0o700, 'secret_directory_mode')
    for name in ('token', 'proxies.toml', 'hc-ping'):
        info = (SERVICE / 'secrets' / name).stat()
        require(info.st_mode & 0o777 == 0o600 and info.st_uid == 1002, 'secret_mode_owner')
    link = Path.home() / '.config/abg/client-token'
    require(link.is_symlink() and link.resolve() == SERVICE / 'secrets/token', 'client_token_link')
    # The accepted script verifies the immutable release byte-for-byte on reuse.
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/abg-release'), 'prepare',
                             '--repo', str(ROOT), '--sha', SHA, '--root', str(SERVICE)],
                            capture_output=True, timeout=60)
    require(result.returncode == 0, 'release_integrity_failed')
    data, metadata = {}, []
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=ai-browser-gateway').split()
    require(len(ids) == 2, 'compose_container_count')
    for ident in ids:
        entry = inspect(ident)
        role = entry['Config']['Labels'].get('com.docker.compose.service')
        require(role in ('api', 'monitor') and role not in data, 'compose_role_mismatch')
        data[role] = entry
    started = datetime.fromisoformat(data['monitor']['State']['StartedAt'].replace('Z', '+00:00'))
    delay = max(0, 131 - (datetime.now(timezone.utc) - started).total_seconds())
    while delay > 0:
        print('waiting for monitor uptime >=130s', flush=True)
        time.sleep(min(delay, 30))
        delay -= 30
    for role, entry in data.items():
        entry = inspect(entry['Id'])
        config, host = entry['Config'], entry['HostConfig']
        require(entry['State']['Running'] and entry['RestartCount'] == 0, 'container_not_stable')
        require(config['User'] == '1002:1002' and config['WorkingDir'] == str(RELEASE), 'container_identity')
        require(set(host.get('GroupAdd') or []) == ({gid} if role == 'api' else set()), 'container_groups')
        require(host['ReadonlyRootfs'] and '/tmp' in host['Tmpfs'] and not host['Privileged'], 'container_isolation')
        require(host['RestartPolicy']['Name'] == 'unless-stopped', 'restart_policy')
        require(config['Cmd'] == ['python3', '-m', 'gateway.service' if role == 'api' else 'gateway.health_monitor'], 'container_command')
        mounts = {m['Destination']: (m['Source'], m['RW']) for m in entry['Mounts'] if m['Type'] != 'tmpfs'}
        expected_mounts = {str(RELEASE): (str(RELEASE), False)}
        env = dict(item.split('=', 1) for item in config['Env'])
        if role == 'api':
            expected_mounts.update({'/var/run/docker.sock': ('/var/run/docker.sock', True),
                                   '/run/abg/token': (str(SERVICE / 'secrets/token'), False),
                                   '/run/abg/proxies.toml': (str(SERVICE / 'secrets/proxies.toml'), False)})
            require(entry['NetworkSettings']['Ports'] == {'8765/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8765'}]}, 'loopback_publish')
            require(entry['State'].get('Health', {}).get('Status') == 'healthy', 'api_unhealthy')
            require(env.get('ABG_INSTANCE') == 'stand-host' and not env.get('ABG_PROVIDER_NETWORK'), 'provider_config')
            require(entry['Image'] == json.loads(docker('image', 'inspect', IMAGE))[0]['Id'], 'image_id_mismatch')
        else:
            expected_mounts['/run/abg/ping'] = (str(SERVICE / 'secrets/hc-ping'), False)
            require(not any(entry['NetworkSettings']['Ports'].values()), 'monitor_publication')
            require(not set(env) & {'ABG_TOKEN', 'ABG_TOKEN_FILE', 'ABG_PROFILES_FILE', 'DOCKER_HOST'}, 'monitor_secret_env')
            require(env.get('ABG_HEALTH_INTERVAL_SECONDS') == '60', 'monitor_interval')
        require(mounts == expected_mounts, 'container_mounts')
        # docker logs uses stderr for application stderr too: inspect both streams.
        logs = subprocess.run(['docker', 'logs', entry['Id']], capture_output=True, text=True, timeout=20)
        require(logs.returncode == 0, 'docker_logs_failed')
        if role == 'monitor':
            require(not (logs.stdout + logs.stderr).strip(), 'monitor_delivery_errors')
        metadata.append({'argv': config['Cmd'], 'env': config['Env'], 'logs': logs.stdout + logs.stderr})
    worker_call('scan', metadata=metadata)
    require(worker_call('health') == {'status': 200, 'body': {'ok': True}}, 'health_failed')
    require(worker_call('unauthorized')['status'] == 401, 'auth_failed')
    save('deploy', {'release_sha': SHA, 'image_id': data['api']['Image'],
                    'docker_version': docker('--version').strip(),
                    'compose_version': docker('compose', 'version').strip(),
                    'python_version': docker('exec', data['api']['Id'], 'python3', '--version').strip(),
                    'monitor_uptime_seconds': (datetime.now(timezone.utc) - started).total_seconds(),
                    'monitor_logs_empty': True, 'healthy': True,
                    'metadata_verified': True, 'secrets_absent': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for flag in ('check-deploy', 'check-profiles', 'check-api-egress', 'run-targets'):
        group.add_argument('--' + flag, action='store_true')
    args = parser.parse_args()
    EVIDENCE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(EVIDENCE, 0o700)
    mode = next(k for k, v in vars(args).items() if v)
    with (EVIDENCE / 'runner.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            globals()[mode]()
        except Exception as exc:
            error = str(exc) if isinstance(exc, CheckError) else type(exc).__name__
            save(mode + '-result', {'ok': False, 'internal_error': redact(error)})
            print(json.dumps({'ok': False, 'internal_error': redact(error)}), file=sys.stderr)
            return 1
        save(mode + '-result', {'ok': True})
        print(json.dumps({'ok': True, 'mode': mode}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
