"""Offline provider inventory and HTTP health contracts."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import subprocess
from threading import Barrier, Event, Thread
import unittest
from unittest.mock import Mock, patch

from gateway import provider_images
from gateway.httpapi import make_server


class ImageTests(unittest.TestCase):
    def test_route_uses_current_registry(self):
        tags = ('abg-curl_cffi:m2', 'abg-patchright:m2', 'abg-rss:m4',
                'abg-scrapling:m8', 'abg-wayback:m4')
        self.assertEqual(provider_images.route_images(), tags)
        with patch('bench.providers.registry.by_name', return_value=Mock(image='shared:1')):
            self.assertEqual(provider_images.route_images(), ('shared:1',))

    def test_missing_copy_and_cache_boundary(self):
        clock = Mock(return_value=0)
        check = provider_images.ImageCheck(['c:1', 'a:1', 'b:1'], clock=clock)
        with patch.object(subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, ' b:1 \n<none>:<none>')
            missing = dict(ok=False, error='provider_images_missing', missing=['a:1', 'c:1'])
            first = check.status()
            self.assertEqual(first, missing)
            first['missing'].clear()
            first['ok'] = True
            clock.return_value = 14.99
            self.assertEqual(check.status(), missing)
            run.assert_called_once_with(
                ['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}',
                 '--filter', 'reference=a:1', '--filter', 'reference=b:1', '--filter', 'reference=c:1'],
                timeout=3.0, stdin=subprocess.DEVNULL, capture_output=True, text=True)
            clock.return_value = 15
            run.return_value.stdout = 'a:1\nb:1\nc:1'
            self.assertEqual(check.status(), {'ok': True})
            self.assertEqual(check.status(), {'ok': True})
            self.assertEqual(run.call_count, 2)

    def test_unknown_is_cached(self):
        for result in (subprocess.CompletedProcess([], 1, 'a:1'), FileNotFoundError(),
                       subprocess.TimeoutExpired('docker', 3), RuntimeError()):
            with self.subTest(result=result):
                run = Mock(side_effect=[result])
                check = provider_images.ImageCheck(['a:1'], run=run, clock=lambda: 0)
                for _ in range(2):
                    self.assertEqual(check.status(), dict(ok=False, error='provider_images_unknown'))
                run.assert_called_once()

    def test_concurrent_checks_share_probe(self):
        start = Barrier(4)
        entered, release, duplicate = Event(), Event(), Event()

        def delayed(*args, **kwargs):
            if entered.is_set():
                duplicate.set()
            entered.set()
            release.wait(3)
            return subprocess.CompletedProcess([], 0, 'a:1')

        run = Mock(side_effect=delayed)
        check = provider_images.ImageCheck(['a:1'], run=run)

        def request():
            start.wait(3)
            return check.status()

        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = [pool.submit(request) for _ in range(4)]
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(duplicate.wait(.1))
            finally:
                release.set()
            self.assertEqual([task.result() for task in pending], [{'ok': True}] * 4)
        run.assert_called_once()


class HealthTests(unittest.TestCase):
    def health(self, server):
        self.addCleanup(server.server_close)
        thread = Thread(target=server.handle_request)
        server.timeout = 3
        thread.start()
        connection = HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request('GET', '/health')
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
            thread.join(4)

    def server(self, **kwargs):
        return make_server(('localhost', 0), token='test-token', **kwargs)

    def test_default(self):
        self.assertEqual(self.health(self.server()), (200, {'ok': True}))

    def test_status_and_body(self):
        for body, status in (({'ok': True}, 200), ({'ok': False, 'missing': ['a:1']}, 503),
                             ({'ok': 1}, 503)):
            with self.subTest(body=body):
                server = self.server(health_check=lambda: body)
                self.assertEqual(self.health(server), (status, body))

    def test_callback_errors(self):
        for callback in (Mock(side_effect=RuntimeError), lambda: None):
            with self.subTest(callback=callback):
                self.assertEqual(self.health(self.server(health_check=callback)),
                                 (503, dict(ok=False, error='provider_images_unknown')))

    def test_invalid_callback(self):
        with self.assertRaisesRegex(ValueError, '^invalid configuration$'):
            self.server(health_check=0)

    def test_service_health_callback(self):
        from gateway import service
        env = dict(ABG_INSTANCE='test', ABG_BIND='localhost', ABG_PORT='0')
        private = [b'test-token', b'[profile.test]\nurl="http://proxy.invalid:1234"']
        with patch.object(service, 'read_private', side_effect=private * 2), \
                patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
            server = service.make_service(env)
            run.assert_not_called()
            self.assertEqual(self.health(server), (503, dict(ok=False, error='provider_images_missing',
                                                             missing=list(provider_images.route_images()))))
            run.assert_called_once()
            override = {'ok': True, 'test': True}
            self.assertEqual(self.health(service.make_service(env, health_check=lambda: override)),
                             (200, override))
            run.assert_called_once()
