"""Release contract with only git replaced by synthetic archive bytes."""
import hashlib
import io
import subprocess
import tarfile
from unittest import mock

from tests.m12_support import FileCase, identity, mode, script

release = script('abg-release')


class ReleaseContractTests(FileCase):
    def setUp(self):
        super().setUp()
        self.sha = 'b' * 40
        self.root = self.base / 'delivery'
        self.tree = self.root / 'releases' / self.sha
        self.manifest = self.root / 'manifests' / (self.sha + '.sha256')
        self.files = [('data.txt', b'committed\n', 0o600),
                      ('nested/bin/tool', b'#!/bin/sh\n', 0o700)]
        self.archive_files()
        patch = mock.patch.object(release, 'git', side_effect=self.git)
        patch.start()
        self.addCleanup(patch.stop)

    def git(self, repo, command, *args):
        outputs = {'cat-file': b'commit', 'rev-parse': self.sha.encode(), 'archive': self.archive}
        return subprocess.CompletedProcess([command, *args], 0, outputs[command], b'')

    def archive_files(self, extra=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as tar:
            for name, data, permissions in self.files:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), permissions
                tar.addfile(info, io.BytesIO(data))
            if extra is not None:
                tar.addfile(extra)
        self.archive = stream.getvalue()

    def prepare(self, expected=0):
        self.invoke(release, ['prepare', '--repo', str(self.base), '--sha', self.sha,
                              '--root', str(self.root)], expected, 'prepared\n')

    def test_symlinks_refused_without_changing_external_file(self):
        self.prepare()
        for target in (self.manifest, self.tree / 'data.txt'):
            with self.subTest(target=target.name):
                contents = target.read_bytes()
                external = self.base / 'external'
                external.write_bytes(contents)
                before = identity(external)
                target.unlink()
                target.symlink_to(external)
                self.prepare(1)
                self.assertTrue(target.is_symlink())
                self.assertEqual((external.read_bytes(), identity(external)), (contents, before))
                target.unlink()
                target.write_bytes(contents)
                target.chmod(0o644)
        self.prepare()

    def test_modes_manifest_and_repeat(self):
        self.prepare()
        for name, data, permissions in self.files:
            target = self.tree / name
            self.assertEqual((target.read_bytes(), mode(target)),
                             (data, 0o755 if permissions & 0o111 else 0o644))
        for folder in (self.tree, self.tree / 'nested', self.tree / 'nested/bin',
                       self.root / 'releases', self.root / 'manifests'):
            self.assertEqual(mode(folder), 0o755)
        expected = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                           for name, data, _ in sorted(self.files))
        self.assertEqual((self.manifest.read_text(), mode(self.manifest)), (expected, 0o644))
        paths = [self.tree / name for name, _, _ in self.files] + [self.manifest]
        before = [identity(path) for path in paths]
        self.prepare()
        self.assertEqual([identity(path) for path in paths], before)

    def test_mode_mismatches_preserved(self):
        self.prepare()
        for name, original, changed in [('data.txt', 0o644, 0o600), ('nested', 0o755, 0o700),
                                        ('nested/bin/tool', 0o755, 0o644)]:
            with self.subTest(path=name):
                target = self.tree / name
                target.chmod(changed)
                self.prepare(1)
                self.assertEqual(mode(target), changed)
                target.chmod(original)
        self.prepare()

    def test_content_and_extra_file_mismatches_preserved(self):
        self.prepare()
        for name in ('data.txt', 'foreign'):
            target = self.tree / name
            target.write_bytes(b'foreign contents')
            self.prepare(1)
            self.assertEqual(target.read_bytes(), b'foreign contents')
            target.unlink()
            if name == 'data.txt':
                target.write_bytes(self.files[0][1])
        self.prepare()

    def test_archive_symlink_hardlink_and_traversal_refused(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.REGTYPE):
            with self.subTest(kind=kind):
                info = tarfile.TarInfo('../escape' if kind == tarfile.REGTYPE else 'link')
                info.type, info.linkname = kind, 'data.txt'
                self.archive_files(info)
                self.prepare(1)
                self.assertFalse(self.tree.exists())
                self.assertFalse((self.root / 'escape').exists())
        self.archive_files()
        self.prepare()
