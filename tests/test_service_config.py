"""Exercise fail-closed configuration through make_service, before bind."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import service


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.token, self.profiles = (Path(tmp.name) / name for name in ('token', 'profiles'))
        self.token.write_bytes(b'private-test-token\r\n')
        self.profiles.write_text('[profile.alpha]\nurl="https://u:p@proxy.invalid:8126"\n')
        for path in (self.token, self.profiles):
            path.chmod(0o600)
        self.env = dict(ABG_TOKEN_FILE=str(self.token), ABG_PROFILES_FILE=str(self.profiles),
                        ABG_INSTANCE='test-one', ABG_BIND='127.0.0.1', ABG_PORT='0')

    def reject(self, **changes):
        with patch('http.server.HTTPServer.server_bind') as bind:
            with self.assertRaises(service.ConfigError):
                server = service.make_service(self.env | changes)
                server.server_close()
            bind.assert_not_called()

    def test_valid_config_and_limit(self):
        for limit in (1, 2):
            server = service.make_service(self.env | {'ABG_BROWSER_LIMIT': str(limit)})
            self.addCleanup(server.server_close)
            self.assertEqual(server.token, b'private-test-token')
            self.assertEqual(server.profiles, {'alpha': 'https://u:p@proxy.invalid:8126'})
            self.assertEqual(server.instance, 'test-one')
            self.assertTrue(server.rotate_profiles)
            for _ in range(limit):
                self.assertTrue(server.slots.acquire(blocking=False))
            self.assertFalse(server.slots.acquire(blocking=False))
            for _ in range(limit):
                server.slots.release()

    def test_invalid_environment_before_bind(self):
        cases = {'TOKEN_FILE': [''], 'PROFILES_FILE': [''], 'TOKEN': ['conflict'],
                 'INSTANCE': ['', 'Bad', '../other', 'a' * 64], 'BIND': [''],
                 'PORT': ['-1', '65536', 'x', '1.5'], 'BROWSER_LIMIT': ['0', '-1', 'x', '1.5']}
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.reject(**{'ABG_' + key: value})

    def test_invalid_token_bytes(self):
        for raw in (b'', b'a b', b'a\tb', b'a\nb', b'\xff', b'a\x00b'):
            with self.subTest(raw=raw):
                self.token.write_bytes(raw)
                self.reject()

    def test_private_files_permissions_type_owner_and_read_error(self):
        for path in (self.token, self.profiles):
            for mode in (0o640, 0o604, 0o644):
                path.chmod(mode)
                self.reject()
            path.chmod(0o600)
            with patch.object(service.os, 'getuid', return_value=os.getuid() + 1):
                self.reject()
            raw = path.read_bytes()
            path.unlink()
            self.reject()
            path.mkdir(mode=0o700)
            self.reject()
            path.rmdir()
            path.write_bytes(raw)
            path.chmod(0o600)
        with patch.object(Path, 'read_bytes', side_effect=PermissionError):
            self.reject()

    def test_profile_format_name_and_url(self):
        for raw in (b'', b'broken[', b'\xff', b'[unrelated]\na=1', b'profile="scalar"',
                    b'[profile.direct]\nurl="http://p:8"', b'[profile.""]\nurl="http://p:8"',
                    b'[profile]\na="scalar"'):
            with self.subTest(raw=raw):
                self.profiles.write_bytes(raw)
                self.reject()
        for url in ('', 'socks5://proxy:8', 'http://:8', 'http://proxy:0',
                    'http://proxy:65536', 'http://proxy:bad', 'http://proxy',
                    *('http://proxy:8/a' + c + 'b' for c in (' ', '\u00a0', '\u0085', '\u009f'))):
            with self.subTest(url=url):
                self.profiles.write_text('[profile.alpha]\nurl=' + json.dumps(url) + '\n')
                self.reject()

    def test_entrypoint_error_redaction(self):
        self.token.write_bytes(b'invalid secret token')
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), patch('sys.stderr', output):
            self.assertEqual(service.main(), 1)
        self.assertEqual(output.getvalue(), '{"error":"invalid_configuration"}\n')
