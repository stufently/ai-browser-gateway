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
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name) / 'client.py'
        self.assertTrue(CLIENT.is_file(), 'standalone client missing')
        self.target.write_bytes(CLIENT.read_bytes())

    def client(self, addr, url=URL, mode='text', *, options=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
        env.update(ABG_URL='http://%s:%s/v1/fetch' % addr, ABG_TOKEN=TOKEN)
        env.update(options or {})
        return subprocess.run([sys.executable, str(self.target), url, mode], cwd=self.target.parent,
                              env=env, capture_output=True, text=True, timeout=8)

    def test_api_result_urls_do_not_inherit_request_guard(self):
        from dataclasses import replace
        from gateway.httpapi import make_server
        from tests.m11_helpers import reply
        href, hits = 'https://user:pass@example.invalid/a', []
        def factory(url, **kw):
            hits.append(url)
            value = reply(html='<a href="' + href + '">label</a>')
            return lambda s, b: replace(value, result=replace(value.result, final_url=href))
        with serving(make_server(('127.0.0.1', 0), token=TOKEN, fetcher_factory=factory)) as addr:
            for url, mode in [(URL, 'links'), (URL, 'text'), (href, 'links')]:
                with self.subTest(url=url, mode=mode):
                    proc = self.client(addr, url, mode)
                    if url == href:
                        self.assertNotEqual(proc.returncode, 0)
                        self.assertEqual(proc.stdout, '')
                    else:
                        self.assertEqual((proc.returncode, proc.stderr), (0, ''))
                        self.assertEqual(json.loads(proc.stdout) if mode == 'links' else proc.stdout.strip(),
                                         [{'text': 'label', 'href': href}] if mode == 'links' else 'page')
            self.assertEqual(hits, [URL, URL])

    def test_standalone_response_validation_and_redirect_refusal(self):
        hits, received, response = [], [], [200, None]
        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_GET(self):
                received.append((self.command, self.path, self.headers.get('Authorization')))
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                body = json.dumps(good).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            do_POST = do_GET
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_POST(self):
                hits.append(self.headers.get('Authorization'))
                self.rfile.read(int(self.headers['Content-Length']))
                body = json.dumps(response[1]).encode()
                self.send_response(response[0])
                self.send_header('Location', 'http://%s:%s/receiver' % receiver_addr)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        good = dict(ok=True, url=URL, final_url=URL, format='text', content='selected',
                    provider='curl', age_hours=None, error_type='none', step='stop', elapsed_ms=1, attempts=[])
        with serving(ThreadingHTTPServer(('127.0.0.1', 0), Receiver)) as receiver_addr, \
                serving(ThreadingHTTPServer(('127.0.0.1', 0), Handler)) as addr:
            for status, obj, success in [(200, good, True), (302, good, False),
                    (200, dict(good, attempts=[{}]), False), (200, dict(good, ok=False), False),
                    (500, {'error': TOKEN}, False), (200, dict(good, content=[]), False),
                    *[(200, dict(good, format='links', content=[{'text': 'L', 'href': h}]), False)
                      for h in ('javascript:bad()', 'mailto:a@b', '/relative', 12)]]:
                response[:] = status, obj
                before = len(hits)
                proc = self.client(addr, mode=obj.get('format', 'text'))
                self.assertEqual(received, [], 'CLI followed redirect or forwarded Bearer')
                self.assertEqual(len(hits), before + 1)
                self.assertEqual(hits[-1], 'Bearer ' + TOKEN)
                if success:
                    self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr), (0, 'selected', ''))
                else:
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(proc.stdout, '')
                    self.assertIsInstance(json.loads(proc.stderr)['error'], str)
                    self.assertNotIn(TOKEN, proc.stderr)

    def test_standalone_forwards_configured_request_body(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, self.headers.get('Authorization'),
                                 self.headers.get_content_type(), body))
                value = dict(ok=True, url=URL, final_url=URL, format='meta',
                             content={'title': 'selected', 'h1': []}, provider='curl',
                             age_hours=2.5, error_type='none', step='stop', elapsed_ms=1, attempts=[])
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        with serving(ThreadingHTTPServer(('127.0.0.1', 0), Handler)) as addr:
            proc = self.client(addr, mode='meta', options={
                'ABG_EXPECTED_TEXT': '  нужный текст [x]  ', 'ABG_BUDGET_MS': '12345',
                'ABG_MAX_AGE_HOURS': '2.5', 'ABG_ALLOW_BROWSER': '0'})
        self.assertEqual((proc.returncode, proc.stderr), (0, ''))
        self.assertEqual(json.loads(proc.stdout), {'title': 'selected', 'h1': []})
        self.assertEqual(received, [('/v1/fetch', 'Bearer ' + TOKEN, 'application/json', {
            'url': URL, 'format': 'meta', 'budget_ms': 12345, 'max_age_hours': 2.5,
            'allow_browser': False, 'expected_text': '  нужный текст [x]  '})])

    def test_wrapper_passes_token_by_environment_name_and_mounts_only_client(self):
        root = CLIENT.parents[1]
        tmp = self.target.parent
        fake_bin = tmp / 'fake-bin'
        fake_bin.mkdir()
        docker = fake_bin / 'docker'
        docker.write_text('#!' + sys.executable + '\n'
                          'import json, os, sys\n'
                          'from pathlib import Path\n'
                          'with Path(os.environ["CAPTURE"]).open("a") as f:\n'
                          '    f.write(json.dumps({"argv": sys.argv[1:], '
                          '"token_env": os.environ.get("ABG_TOKEN")}) + "\\n")\n')
        docker.chmod(0o755)
        wrapper = tmp / 'abg-fetch'
        wrapper.symlink_to(root / 'scripts/abg-fetch')
        capture = tmp / 'docker.jsonl'
        env = {k: v for k, v in os.environ.items() if not k.startswith('ABG_')}
        env.update(PATH=str(fake_bin) + os.pathsep + os.defpath, HOME=str(tmp),
                   CAPTURE=str(capture), ABG_TOKEN='synthetic-wrapper-token-only',
                   ABG_TOKEN_FILE=str(tmp / 'missing-token-file'))
        proc = subprocess.run([str(wrapper), URL, 'meta'], env=env, cwd=tmp,
                              capture_output=True, text=True, timeout=8)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, '', ''))
        records = [json.loads(line) for line in capture.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        argv = records[0]['argv']
        self.assertEqual(records[0]['token_env'], 'synthetic-wrapper-token-only')
        self.assertNotIn('synthetic-wrapper-token-only', '\n'.join(argv),
                         'token value leaked into Docker argv')
        self.assertEqual(argv[0], 'run')
        self.assertIn('--rm', argv)
        self.assertEqual(argv[argv.index('--user') + 1], '1002:1002')
        self.assertEqual(argv[argv.index('--network') + 1], 'host')
        passed_env = [argv[i + 1] for i, arg in enumerate(argv) if arg == '-e']
        self.assertIn('ABG_TOKEN', passed_env)
        self.assertFalse(any(arg.startswith('ABG_TOKEN=') for arg in passed_env))
        mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == '--mount']
        self.assertEqual(mounts, [f'type=bind,source={CLIENT},target=/client.py,readonly'])
        self.assertNotIn('-v', argv)
        self.assertNotIn('--volume', argv)
        self.assertNotIn('docker.sock', '\n'.join(argv))
        self.assertEqual(argv[-5:], [
            'python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6',
            'python3', '/client.py', URL, 'meta'])
