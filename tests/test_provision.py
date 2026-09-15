import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import tomllib

ROOT = Path(__file__).resolve().parents[1]


class ProvisionTests(unittest.TestCase):
    def test_encoding_atomicity_and_symlink_refuse(self):
        tmp = tempfile.TemporaryDirectory(prefix='m12-prov-')
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        login, password = 'u@:#', 'p %q'
        source = base / 'src'
        fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write('PROXY_LOGIN="%s"\nPROXY_PASSWORD=\'%s\'\n' % (login, password))
        target = base / 'out.toml'
        cmd = [sys.executable, str(ROOT / 'scripts/abg-provision'), '--source', str(source), '--output']
        proc = subprocess.run(cmd + [str(target)], capture_output=True, text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        url = tomllib.loads(target.read_text())['profile']['ms15']['url']
        parts = urlsplit(url)
        self.assertEqual((parts.hostname, parts.port, unquote(parts.username)),
                         ('ms15.example.net', 8126, login))
        self.assertNotIn(login, proc.stdout + proc.stderr)
        before = target.read_bytes()
        self.assertNotEqual(subprocess.run(cmd + [str(target)], capture_output=True, timeout=8).returncode, 0)
        self.assertEqual(target.read_bytes(), before)
        victim = base / 'keep'
        victim.write_bytes(b'secret')
        link = base / 'link'
        link.symlink_to(victim)
        self.assertNotEqual(subprocess.run(cmd + [str(link)], capture_output=True, timeout=8).returncode, 0)
        self.assertEqual(victim.read_bytes(), b'secret')
