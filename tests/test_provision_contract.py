"""Synthetic credentials and failures at filesystem boundaries."""
import os
from pathlib import Path
import stat
import tomllib
from unittest import mock
from urllib.parse import quote, unquote, urlsplit

from tests.m12_support import FileCase, identity, mode, script

provision = script('abg-provision')
VALID = b'PROXY_LOGIN=user\nPROXY_PASSWORD=password\n'


class ProvisionContractTests(FileCase):
    def setUp(self):
        super().setUp()
        self.source, self.target = self.base / 'source', self.base / 'profiles.toml'
        self.source.write_bytes(VALID)
        self.source.chmod(0o600)

    def prepare(self, expected=0):
        self.invoke(provision, ['--source', str(self.source), '--output', str(self.target)],
                    expected, 'profiles=15\n')

    def clean(self, target_absent=False):
        if target_absent:
            self.assertFalse(self.target.exists())
        self.assertEqual(list(self.base.glob('.abg-provision-*')), [])

    def test_exactly_fifteen_profiles_encode_both_credentials(self):
        login, password = 'user:@ /%雪', 'p:@ /%\\"$HOME`echo literal`'
        self.source.write_text(f' # ignored\nOTHER=value\n PROXY_LOGIN = "{login}"\n'
                               f" PROXY_PASSWORD = '{password}'\n")
        self.prepare()
        profiles = tomllib.loads(self.target.read_text())['profile']
        self.assertEqual(list(profiles), [f'ms{i}' for i in range(1, 16)])
        self.assertNotIn('ms16', profiles)
        for index, profile in enumerate(profiles.values(), 1):
            host = f'ms{index}.example.net'
            url = profile['url']
            self.assertEqual(url, f'http://{quote(login, safe="")}:{quote(password, safe="")}@{host}:8126')
            parsed = urlsplit(url)
            self.assertEqual((parsed.scheme, parsed.hostname, parsed.port), ('http', host, 8126))
            self.assertEqual((unquote(parsed.username), unquote(parsed.password)), (login, password))
        self.assertEqual((mode(self.target), self.target.stat().st_uid), (0o600, os.getuid()))
        self.clean()

    def test_missing_duplicate_empty_and_invalid_source(self):
        cases = [b'PROXY_LOGIN=user\n', b'PROXY_PASSWORD=password\n',
                 VALID + b'PROXY_LOGIN=other\n', VALID + b'PROXY_PASSWORD=other\n',
                 VALID.replace(b'=user', b'='), VALID.replace(b'=password', b'=""'),
                 VALID.replace(b'=user', b'=\xff'), None]
        for body in cases:
            with self.subTest(body=body):
                if body is None:
                    self.source.unlink()
                else:
                    self.source.write_bytes(body)
                self.prepare(1)
                self.clean(target_absent=True)
        self.source.write_bytes(VALID)
        self.prepare()

    def test_existing_target_is_not_overwritten_or_repermissioned(self):
        self.target.write_bytes(b'foreign configuration')
        self.target.chmod(0o640)
        before = identity(self.target)
        self.prepare(1)
        self.assertEqual((self.target.read_bytes(), identity(self.target)),
                         (b'foreign configuration', before))
        self.clean()

    def test_existing_and_dangling_symlinks_refused(self):
        external = self.base / 'external'
        external.write_bytes(b'keep')
        for exists in (True, False):
            with self.subTest(exists=exists):
                if not exists:
                    external.unlink()
                self.target.symlink_to(external)
                self.prepare(1)
                self.assertTrue(self.target.is_symlink())
                self.assertEqual(external.exists(), exists)
                if exists:
                    self.assertEqual(external.read_bytes(), b'keep')
                self.target.unlink()
                self.clean()

    def test_short_and_failed_writes_are_private_and_atomic(self):
        real_write, real_link = os.write, os.link
        for failure in (False, True):
            with self.subTest(failure=failure):
                writes, publications = [], []

                def write(fd, data):
                    self.assertFalse(self.target.exists())
                    self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
                    writes.append(len(data))
                    if failure and len(writes) == 2:
                        raise OSError('synthetic private disk error')
                    return real_write(fd, data[:7])

                def publish(source, target):
                    self.assertFalse(self.target.exists())
                    self.assertEqual(Path(source).read_bytes(), provision.body('user', 'password'))
                    self.assertEqual(mode(Path(source)), 0o600)
                    publications.append(target)
                    return real_link(source, target)

                with mock.patch.object(os, 'write', side_effect=write), mock.patch.object(os, 'link', side_effect=publish):
                    self.prepare(int(failure))
                self.assertEqual(len(publications), 0 if failure else 1)
                self.clean(target_absent=failure)
                if failure:
                    self.assertEqual(len(writes), 2)
                else:
                    self.assertGreater(len(writes), 1)
                    self.assertEqual(self.target.read_bytes(), provision.body('user', 'password'))
                    self.assertEqual(mode(self.target), 0o600)
                    self.target.unlink()

    def test_zero_write_and_publication_failure_remove_temporary(self):
        for name, effect in [('write', lambda *args: 0), ('link', OSError('synthetic full disk'))]:
            with self.subTest(boundary=name):
                with mock.patch.object(os, name, side_effect=effect) as boundary:
                    with self.assertRaises(OSError):
                        provision.write(self.target, b'complete bytes')
                boundary.assert_called_once()
                self.clean(target_absent=True)

    def test_parent_owner_refused_before_open(self):
        with mock.patch.object(os, 'getuid', return_value=os.getuid() + 1):
            with mock.patch.object(os, 'open') as opened:
                with self.assertRaises(OSError):
                    provision.write(self.target, b'complete bytes')
        opened.assert_not_called()
        self.clean(target_absent=True)
        provision.write(self.target, b'complete bytes')
        self.assertEqual(self.target.read_bytes(), b'complete bytes')

    def test_target_created_during_write_is_preserved(self):
        real_link = os.link

        def raced_link(source, target):
            self.assertFalse(self.target.exists())
            self.target.write_bytes(b'concurrent owner data')
            return real_link(source, target)

        with mock.patch.object(os, 'link', side_effect=raced_link):
            with self.assertRaises(FileExistsError):
                provision.write(self.target, b'new configuration')
        self.assertEqual(self.target.read_bytes(), b'concurrent owner data')
        self.clean()
