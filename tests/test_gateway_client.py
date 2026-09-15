import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tests.m11_helpers import URL, TOKEN, serving

CLIENT = Path(__file__).resolve().parents[1] / 'gateway/client.py'


class ClientTests(unittest.TestCase):
    def test_standalone_response_validation_and_redirect_refusal(self):
        hits, response = [], [200, None]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_POST(self):
                hits.append(self.headers.get('Authorization'))
                self.rfile.read(int(self.headers['Content-Length']))
                body = json.dumps(response[1]).encode()
                self.send_response(response[0])
                self.send_header('Location', '/receiver')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        good = dict(ok=True, url=URL, final_url=URL, format='text', content='selected',
                    provider='curl', age_hours=None, error_type='none', step='stop', elapsed_ms=1, attempts=[])
        self.assertTrue(CLIENT.is_file(), 'standalone client missing')
        with serving(ThreadingHTTPServer(('127.0.0.1', 0), Handler)) as addr, tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'client.py'
            target.write_bytes(CLIENT.read_bytes())
            env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
            env.update(ABG_URL='http://%s:%s/v1/fetch' % addr, ABG_TOKEN=TOKEN)
            for status, obj, success in [(200, good, True), (302, good, False),
                    (200, dict(good, attempts=[{}]), False), (200, dict(good, ok=False), False),
                    (500, {'error': TOKEN}, False), (200, dict(good, content=[]), False)]:
                response[:] = status, obj
                before = len(hits)
                proc = subprocess.run([sys.executable, str(target), URL], env=env, capture_output=True, text=True)
                self.assertEqual(len(hits), before + 1)
                self.assertEqual(hits[-1], 'Bearer ' + TOKEN)
                if success:
                    self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr), (0, 'selected', ''))
                else:
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(proc.stdout, '')
                    self.assertIsInstance(json.loads(proc.stderr)['error'], str)
                    self.assertNotIn(TOKEN, proc.stderr)
