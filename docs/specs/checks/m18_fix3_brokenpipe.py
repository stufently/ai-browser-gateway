"""M18-fix3 process checker: a client that stops reading stdout must not leave the server running.

Owned by the coordinator; the executor must not edit it. Prints `ok` on success.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = 'm18-fix3-token-7710'


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        data = json.dumps(dict(ok=True, url='https://example.org/', final_url='https://example.org/',
                               provider='curl', age_hours=None, error_type='none', step='stop',
                               elapsed_ms=1, format='text', content='x', attempts=[])).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def run(message):
    """Close the server's stdout reader, keep stdin open, send one message."""
    api = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    env = dict(os.environ, ABG_URL=f'http://127.0.0.1:{api.server_address[1]}/v1/fetch', ABG_TOKEN=TOKEN)
    proc = subprocess.Popen([sys.executable, '-m', 'gateway.mcp_stdio'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    proc.stdout.close()
    proc.stdin.write(json.dumps(message) + '\n')
    proc.stdin.flush()
    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(f'server still running with stdin open: {message["method"]}')
    stderr = proc.stderr.read()
    proc.stdin.close()
    api.shutdown()
    assert rc != 0, (message['method'], rc)
    assert TOKEN not in stderr and 'Traceback' not in stderr, stderr
    return rc


def main():
    # Worker-thread write failure (the fix2 regression).
    run(dict(jsonrpc='2.0', id=1, method='tools/call',
             params=dict(name='fetch_page', arguments=dict(url='https://example.org/'))))
    # Main-thread write failure keeps exiting as before.
    run(dict(jsonrpc='2.0', id=2, method='ping'))
    print('ok')


if __name__ == '__main__':
    main()
