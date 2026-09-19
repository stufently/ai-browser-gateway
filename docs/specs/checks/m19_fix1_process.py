"""M19-fix1 checker: direct means direct, and a terminated CLI takes its probe with it.

Owned by the coordinator; the executor must not edit it. Prints `ok` on success.
Runs INSIDE the image, offline, under a reaping PID 1 so zombies are not counted:
  docker run --rm --network none --user U --entrypoint /usr/bin/tini \
    -v "$PWD/docs/specs/checks/m19_fix1_process.py:/check.py:ro" abg-oneshot:m19 -s -- python3 /check.py
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHALLENGE = b'<html><head><title>Just a moment...</title></head><body>cf</body></html>'
PAGE = b'<html><head><title>Direct page</title></head><body><h1>Direct body</h1></body></html>'
PROXY_VARS = ('http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')


class Handler(BaseHTTPRequestHandler):
    served = 0

    def do_GET(self):
        if self.path.startswith('/page'):
            status, body = 200, PAGE
        else:
            Handler.served += 1
            if Handler.served > 1:
                time.sleep(120)
                return
            status, body = 403, CHALLENGE
        self.send_response(status)
        if status == 403:
            self.send_header('cf-mitigated', 'challenge')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def live_probe_processes():
    rows = subprocess.run(['ps', '-eo', 'pid=,stat=,args='], capture_output=True, text=True).stdout
    alive = []
    for row in rows.splitlines():
        fields = row.split(None, 2)
        if len(fields) == 3 and not fields[1].startswith('Z') and any(
                name in fields[2] for name in ('chrome', 'Xvfb', 'xvfb-run', 'probe.py')):
            alive.append(row.strip()[:80])
    return alive


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'

    # 1. Proxy variables in the caller's environment must not reach the providers.
    env = dict(os.environ, **{name: 'http://127.0.0.1:9' for name in PROXY_VARS})
    env.pop('no_proxy', None)
    env.pop('NO_PROXY', None)
    proc = subprocess.run([sys.executable, '-m', 'gateway.oneshot', base + '/page', '--no-browser'],
                          capture_output=True, text=True, timeout=120, env=env,
                          stdin=subprocess.DEVNULL)
    value = json.loads(proc.stdout)
    assert proc.returncode == 0 and value['ok'] is True, (proc.returncode, value)
    assert 'Direct body' in value['content'], value

    # 2. SIGTERM while a browser probe runs: CLI exits 4, nothing of the probe survives.
    for signum in (signal.SIGTERM, signal.SIGINT):
        Handler.served = 0
        cli = subprocess.Popen([sys.executable, '-m', 'gateway.oneshot', base + '/challenge',
                                '--budget-ms', '90000'], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while Handler.served < 2:
            assert time.monotonic() < deadline, 'browser step never started'
            time.sleep(0.5)
        cli.send_signal(signum)
        out, err = cli.communicate(timeout=30)
        assert cli.returncode == 4 and out == '', (signum, cli.returncode, out)
        assert json.loads(err.strip().splitlines()[-1]) == {'error': 'interrupted'}, err
        time.sleep(3)
        assert live_probe_processes() == [], (signum, live_probe_processes())

    server.shutdown()
    print('ok')


if __name__ == '__main__':
    main()
