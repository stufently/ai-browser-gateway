"""M18-fix2 process checker: runs `python3 -m gateway.mcp_stdio` against a slow stub API.

Owned by the coordinator; the executor must not edit it. Prints `ok` on success.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

DELAY = 3.0
TOKEN = 'm18-fix2-token-5531'


def reply(url):
    return dict(ok=True, url=url, final_url=url, provider='curl', age_hours=None,
                error_type='none', step='stop', elapsed_ms=3000, format='text',
                content='Slow page', attempts=[])


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        time.sleep(DELAY)
        data = json.dumps(reply(body['url'])).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    api = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp())
    (tmp / 'token').write_text(TOKEN + '\n')
    env = dict(os.environ, ABG_URL=f'http://127.0.0.1:{api.server_address[1]}/v1/fetch',
               ABG_TOKEN_FILE=str(tmp / 'token'))
    env.pop('ABG_TOKEN', None)
    proc = subprocess.Popen([sys.executable, '-m', 'gateway.mcp_stdio'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()

    def send(value):
        proc.stdin.write((value if isinstance(value, str) else json.dumps(value)) + '\n')
        proc.stdin.flush()

    def read(timeout):
        return json.loads(lines.get(timeout=timeout))

    def call(ident, **args):
        return dict(jsonrpc='2.0', id=ident, method='tools/call',
                    params=dict(name='fetch_page', arguments=dict(url='https://example.org/', **args)))

    send(dict(jsonrpc='2.0', id=1, method='initialize', params=dict(
        protocolVersion='2025-11-25', capabilities={}, clientInfo=dict(name='t', version='0'))))
    assert read(10)['result']['protocolVersion'] == '2025-11-25'

    # 1. ping is answered promptly while a slow tool call is in flight.
    started = time.monotonic()
    send(call(2))
    send(dict(jsonrpc='2.0', id=3, method='ping'))
    first = read(DELAY + 10)
    assert first == dict(jsonrpc='2.0', id=3, result={}), first
    assert time.monotonic() - started < 1.5, 'ping waited for fetch_page'
    second = read(DELAY + 10)
    assert second['id'] == 2 and second['result']['structuredContent']['content'] == 'Slow page', second

    # 2. two tool calls run concurrently, not one after the other.
    started = time.monotonic()
    send(call(4))
    send(call(5))
    got = {read(DELAY + 10)['id'], read(DELAY + 10)['id']}
    assert got == {4, 5}, got
    assert time.monotonic() - started < DELAY * 2 - 1, 'tool calls were serialized'

    # 3. argument validation failures are tool results with isError, not JSON-RPC errors.
    send(call(6, budget_ms=0))
    bad = read(10)
    assert 'error' not in bad and bad['result']['isError'] is True, bad
    assert bad['result']['content'][0]['type'] == 'text' and bad['result']['content'][0]['text'], bad
    # Unknown tool stays a protocol error.
    send(dict(jsonrpc='2.0', id=7, method='tools/call', params=dict(name='nope', arguments={})))
    unknown = read(10)
    assert unknown['id'] == 7 and unknown['error']['code'] == -32602, unknown

    # 4. errors without a usable request id omit `id` instead of sending null.
    send('{not json')
    parse = read(10)
    assert parse['error']['code'] == -32700 and 'id' not in parse, parse
    send(dict(jsonrpc='2.0', id=None, method='ping'))
    invalid = read(10)
    assert invalid['error']['code'] == -32600 and 'id' not in invalid, invalid

    # 5. EOF right after a slow call: the in-flight response is still delivered.
    send(call(8))
    proc.stdin.close()
    last = read(DELAY + 10)
    assert last['id'] == 8 and last['result']['structuredContent']['content'] == 'Slow page', last
    assert proc.wait(timeout=10) == 0
    stderr = proc.stderr.read()
    assert TOKEN not in stderr, 'token leaked to stderr'
    api.shutdown()
    print('ok')


if __name__ == '__main__':
    main()
