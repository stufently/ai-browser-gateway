"""Real service factory -> product transport -> labeled Docker command boundary."""
import json
import subprocess
import unittest
from unittest.mock import patch

from gateway import service
from tests import test_service_config as config
from tests.m11_helpers import request, serving


class LauncherTests(unittest.TestCase):
    setUp = config.ConfigurationTests.setUp

    def test_real_factory_preserves_request_labels_and_proxy_env(self):
        calls = []
        def run(argv, **kw):
            self.assertEqual(argv[:2], ['docker', 'run'])
            calls.append((argv, kw))
            url = next(arg for arg in argv if arg.startswith('http://target.invalid'))
            proxied = (kw.get('env') or {}).get('ABG_PROXY')
            status = 200 if proxied else 403
            raw = dict(ok=True, sentinel=False, status=status, final_url=url,
                       title='', html='<p>ok</p>', text='ok', err=None,
                       elapsed_ms=1, startup_ms=0, cpu_ms=0, peak_rss_mb=0,
                       bytes=2, redirects=0, challenge='none')
            return subprocess.CompletedProcess(argv, 0, json.dumps(raw), '')
        server = service.make_service(self.env | {'ABG_PROVIDER_NETWORK': 'local-network'})
        with patch.object(service.subprocess, 'run', run), serving(server) as address:
            for path in ('one', 'two'):
                status, body = request(address, {'url': 'http://target.invalid/' + path,
                    'allow_browser': False, 'budget_ms': 4000}, token='private-test-token')
                self.assertEqual(status, 200)
                self.assertTrue(body['ok'], body)
        self.assertEqual(len(calls), 4)
        request_ids = []
        for index, (argv, kw) in enumerate(calls):
            labels = dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '--label')
            self.assertEqual(labels['abg.owner'], 'ai-browser-gateway')
            self.assertEqual(labels['abg.instance'], 'test-one')
            self.assertEqual(labels['abg.role'], 'provider')
            self.assertTrue(labels['abg.request'])
            request_ids.append(labels['abg.request'])
            self.assertEqual(argv[argv.index('--user') + 1], '1002:1002')
            self.assertEqual(argv[argv.index('--network') + 1], 'local-network')
            self.assertTrue(any(arg.endswith('/opt/abg/probe.py,readonly') for arg in argv))
            self.assertEqual(kw['timeout'], int(argv[argv.index('--budget-ms') + 1]) / 1000)
            self.assertEqual(kw['stdin'], subprocess.DEVNULL)
            self.assertNotIn('shell', kw)
            self.assertNotIn('private-test-token', ' '.join(argv))
            self.assertNotIn('u:p@', ' '.join(argv))
            proxy = (kw.get('env') or {}).get('ABG_PROXY')
            self.assertEqual(proxy, 'https://u:p@proxy.invalid:8126' if index % 2 else None)
            if proxy:
                self.assertEqual(argv[argv.index('--env') + 1], 'ABG_PROXY')
        self.assertEqual(request_ids[0], request_ids[1])
        self.assertEqual(request_ids[2], request_ids[3])
        self.assertNotEqual(request_ids[0], request_ids[2])
