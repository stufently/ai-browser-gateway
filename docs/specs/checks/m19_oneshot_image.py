"""M19 checker: runs INSIDE the built one-shot image, offline, against loopback pages.

Owned by the coordinator; the executor must not edit it. Prints `ok` on success.
Run: docker run --rm --network none [--user U] --entrypoint python3 \
       -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m19 /check.py
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEYS = {'ok', 'url', 'final_url', 'provider', 'age_hours', 'error_type', 'step',
        'elapsed_ms', 'format', 'content', 'attempts'}
CHALLENGE = (b'<html><head><title>Just a moment...</title></head>'
             b'<body><div id="cf-challenge">Checking your browser</div></body></html>')
PAGE = (b'<html><head><title>Gateway check page</title></head><body><h1>Hello gateway</h1>'
        b'<p>Plain body text for the one-shot checker.</p>'
        b'<a href="https://example.org/next">Next page</a></body></html>')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/challenge'):
            status, body = 403, CHALLENGE
        else:
            status, body = 200, PAGE
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        if status == 403:
            self.send_header('cf-mitigated', 'challenge')
            self.send_header('Server', 'cloudflare')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def oneshot(*args):
    proc = subprocess.run([sys.executable, '-m', 'gateway.oneshot', *args], capture_output=True,
                          text=True, timeout=400, stdin=subprocess.DEVNULL)
    return proc.returncode, proc.stdout, proc.stderr


def parsed(stdout):
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout[:500]
    value = json.loads(lines[0])
    assert set(value) == KEYS, sorted(value)
    return value


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'

    # 1. Challenge page: the whole ladder runs locally, every provider really starts.
    rc, out, err = oneshot(base + '/challenge', '--budget-ms', '120000')
    value = parsed(out)
    assert rc == 1, (rc, err[-500:])
    assert value['ok'] is False and value['error_type'] == 'http_403' and value['step'] == 'human', value
    assert [a['provider'] for a in value['attempts']] == ['curl_cffi', 'patchright', 'scrapling'], value
    assert all(a['error_type'] == 'http_403' and a['status'] == 403 for a in value['attempts']), value

    # 2. --no-browser stops after the HTTP step.
    rc, out, err = oneshot(base + '/challenge', '--no-browser')
    value = parsed(out)
    assert rc == 1 and [a['provider'] for a in value['attempts']] == ['curl_cffi'], (rc, value)

    # 3. Normal page, default text format.
    rc, out, err = oneshot(base + '/page')
    value = parsed(out)
    assert rc == 0, (rc, err[-500:])
    assert value['ok'] is True and value['provider'] == 'curl_cffi' and value['format'] == 'text', value
    assert 'Hello gateway' in value['content'], value['content']

    # 4. Other formats and expected text.
    rc, out, err = oneshot(base + '/page', '--format', 'links', '--expected-text', 'Plain body text')
    value = parsed(out)
    assert rc == 0 and value['format'] == 'links', (rc, value)
    assert {'text': 'Next page', 'href': 'https://example.org/next'} in value['content'], value
    rc, out, err = oneshot(base + '/page', '--format', 'meta')
    value = parsed(out)
    assert rc == 0 and value['content']['title'] == 'Gateway check page', (rc, value)

    # 5. Expected text that is absent: page fetched but rejected.
    rc, out, err = oneshot(base + '/page', '--expected-text', 'absent marker 7731', '--no-browser')
    value = parsed(out)
    assert rc == 1 and value['ok'] is False and value['error_type'] == 'content_missing', (rc, value)

    # 6. Invalid invocations: rc 2, nothing on stdout, one JSON error line on stderr.
    for args in (['ftp://example.org/'], [base + '/page', '--format', 'pdf'],
                 [base + '/page', '--budget-ms', '0'], []):
        rc, out, err = oneshot(*args)
        assert rc == 2 and out == '', (args, rc, out)
        assert json.loads(err.strip().splitlines()[-1]) == {'error': 'invalid_request'}, (args, err)

    server.shutdown()
    print('ok')


if __name__ == '__main__':
    main()
