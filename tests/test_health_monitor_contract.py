"""Health checks against a private HTTP receiver; mocks only at I/O boundaries."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
from unittest import mock

from gateway import health_monitor as monitor
from tests.m12_support import ERROR, FileCase, captured

HEALTHY = (200, b'{"ok":true}', {})
OPEN = 'urllib.request.OpenerDirector.open'


class HealthContractTests(FileCase):
    def setUp(self):
        super().setUp()
        self.requests, self.responses = [], {}
        self.release_response = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                status, body, headers = owner.responses.get(self.path, (200, b'', {}))
                if self.path == '/slow':
                    owner.release_response.wait(2)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.pingfile = self.base / 'ping'
        self.pingfile.write_text(self.url + '/ping')
        self.pingfile.chmod(0o600)
        patch = mock.patch.dict(os.environ, {
            'ABG_MONITOR_ALLOW_LOCAL_HTTP': '1', 'ABG_HEALTH_URL': self.url + '/health',
            'ABG_HC_PING_FILE': str(self.pingfile), 'ABG_HEALTH_INTERVAL_SECONDS': '0.125'})
        patch.start()
        self.addCleanup(patch.stop)

    def close_server(self):
        self.release_response.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def check(self, expected, health='/health', timeout=5, network_mock=False):
        self.requests.clear()
        with captured() as (output, error):
            result = monitor.check_once(self.url + health, self.url + '/ping', timeout=timeout)
        self.assertIs(result, expected)
        self.assertEqual(output.getvalue(), '')
        if not network_mock:
            self.assertEqual(self.requests, [health, '/ping' if expected else '/ping/fail'])
        return error.getvalue()

    def response(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status, response.read.return_value = 200, b'{"ok":true}'
        return response

    def test_only_http200_object_literal_true_is_healthy(self):
        cases = [(200, b'{"ok":true,"extra":1}', True), (200, b'{"ok":false}', False),
                 (200, b'{"ok":1}', False), (200, b'{"ok":"true"}', False),
                 (200, b'{}', False), (200, b'[true]', False), (200, b'true', False),
                 (200, b'not-json', False), (204, b'', False), (503, b'{"ok":true}', False)]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                self.responses['/health'] = status, body, {}
                self.check(expected)

    def test_health_and_ping_redirects_refused(self):
        self.responses['/destination'] = HEALTHY
        for status in (301, 302, 303, 307, 308):
            for path in ('/health', '/ping'):
                with self.subTest(status=status, path=path):
                    self.responses['/health'] = HEALTHY
                    self.responses[path] = status, b'', {'Location': self.url + '/destination'}
                    self.check(path == '/ping')

    def test_real_timeout_still_pings_failure(self):
        self.responses['/slow'] = HEALTHY
        self.assertEqual(self.check(False, health='/slow', timeout=0.03), 'TimeoutError\n')

    def test_timeout_cap_at_network_boundary(self):
        for supplied, expected in [(99, 5), (0, 5), (-1, 5), (float('nan'), 5),
                                   (float('inf'), 5), ('bad', 5), (None, 5), (0.25, 0.25)]:
            with self.subTest(timeout=supplied):
                with mock.patch(OPEN, return_value=self.response()) as opened:
                    self.check(True, timeout=supplied, network_mock=True)
                calls = opened.call_args_list
                self.assertEqual(len(calls), 2)
                self.assertEqual([call.kwargs['timeout'] for call in calls], [expected, expected])
                self.assertEqual([call.args[0].get_method() for call in calls], ['GET', 'GET'])

    def test_ping_failures_preserve_health_and_redact_errors(self):
        secret = 'synthetic-private-url-and-password'
        for healthy in (True, False):
            with self.subTest(healthy=healthy):
                self.responses['/health'] = HEALTHY if healthy else (503, b'', {})
                self.responses['/ping' if healthy else '/ping/fail'] = 500, b'unavailable', {}
                self.check(healthy)
                effects = [self.response() if healthy else TimeoutError(secret), OSError(secret)]
                with mock.patch(OPEN, side_effect=effects) as opened:
                    error = self.check(healthy, network_mock=True)
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(error, 'OSError\n' if healthy else 'TimeoutError\nOSError\n')
                self.assertNotIn(secret, error)

    def test_loop_rechecks_health_despite_failed_ping(self):
        self.responses.update({'/health': HEALTHY, '/ping': (503, b'unavailable', {})})
        intervals = []

        def sleep(interval):
            intervals.append(interval)
            if len(intervals) == 1:
                self.responses['/health'] = 503, b'', {}
            else:
                raise StopIteration('test complete')

        with mock.patch.object(monitor.time, 'sleep', side_effect=sleep):
            with self.assertRaises(StopIteration):
                monitor.main()
        self.assertEqual(intervals, [0.125, 0.125])
        self.assertEqual(self.requests, ['/health', '/ping', '/health', '/ping/fail'])

    def test_invalid_config_rejected_before_network(self):
        cases = [('interval', x) for x in ('0', '-1', 'nan', 'inf', 'bad')]
        cases += [('url', x) for x in ('https://user:pass@host/ping', 'https://host/ping?key=secret',
                                      'https://host/ping#secret', 'https://host', 'http://remote.invalid/ping')]
        cases += [('mode', 0o644), ('missing', None)]
        for kind, value in cases:
            with self.subTest(kind=kind, value=value):
                self.pingfile.write_text(value if kind == 'url' else self.url + '/ping')
                self.pingfile.chmod(value if kind == 'mode' else 0o600)
                if kind == 'missing':
                    self.pingfile.unlink()
                interval = value if kind == 'interval' else '1'
                with mock.patch.dict(os.environ, ABG_HEALTH_INTERVAL_SECONDS=interval):
                    with mock.patch.object(monitor, '_fetch') as fetch, captured() as (_, error):
                        self.assertEqual(monitor.main(), 1)
                fetch.assert_not_called()
                self.assertEqual(error.getvalue(), ERROR)
        self.assertEqual(self.requests, [])
