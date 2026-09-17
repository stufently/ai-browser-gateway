import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GIT = r'''#!/usr/local/bin/python3
import os, pathlib, sys
a = sys.argv[1:]
while a and a[0] in ('-C', '--git-dir', '--work-tree'):
    a = a[2:]
cmd, rest, sha = a[0], a[1:], os.environ['PROBE_COMMIT']
if cmd == 'archive':
    if sha not in rest and sha + '^{commit}' not in rest:
        sys.exit(2)
    sys.stdout.buffer.write(pathlib.Path(os.environ['PROBE_ARCHIVE']).read_bytes())
elif cmd == 'rev-parse' and any(x == sha or x.startswith(sha + '^') for x in rest):
    print(sha)
elif cmd == 'cat-file' and sha in rest:
    print('commit')
else:
    sys.exit(1)
'''


class ReleaseTests(unittest.TestCase):
    def test_archive_repeat_and_mismatch(self):
        tmp = tempfile.TemporaryDirectory(prefix='m12-rel-')
        self.addCleanup(tmp.cleanup)
        base, sha = Path(tmp.name), 'a' * 40
        repo, root, archive = base / 'repo', base / 'delivery', base / 'archive.tar'
        repo.mkdir()
        with tarfile.open(archive, 'w') as tar:
            for name, data, mode in (('data.txt', b'committed\n', 0o644),
                                     ('bin/tool', b'#!/bin/sh\n', 0o755)):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                tar.addfile(info, io.BytesIO(data))
        bindir = base / 'bin'
        bindir.mkdir()
        git = bindir / 'git'
        git.write_text(GIT)
        git.chmod(0o700)
        env = dict(os.environ)
        env.update(PATH=str(bindir) + os.pathsep + env.get('PATH', ''),
                   PROBE_COMMIT=sha, PROBE_ARCHIVE=str(archive),
                   PYTHONDONTWRITEBYTECODE='1')

        def prepare():
            return subprocess.run(
                [sys.executable, str(ROOT / 'scripts/abg-release'), 'prepare',
                 '--repo', str(repo), '--sha', sha, '--root', str(root)],
                env=env, capture_output=True, text=True, timeout=8)

        self.assertEqual(prepare().returncode, 0)
        release = root / 'releases' / sha
        self.assertEqual((release / 'data.txt').read_bytes(), b'committed\n')
        self.assertEqual(stat.S_IMODE((release / 'bin/tool').stat().st_mode), 0o755)
        ino = (release / 'data.txt').stat().st_ino
        self.assertEqual(prepare().returncode, 0)
        self.assertEqual((release / 'data.txt').stat().st_ino, ino)
        (release / 'data.txt').write_bytes(b'foreign')
        self.assertNotEqual(prepare().returncode, 0)
        self.assertEqual((release / 'data.txt').read_bytes(), b'foreign')
