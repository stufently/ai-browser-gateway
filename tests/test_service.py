from pathlib import Path
import stat
import unittest
from unittest.mock import patch


class ServiceTests(unittest.TestCase):
    def test_labeled_launcher_argv_and_unique_request_ids(self):
        from gateway.service import LabeledLauncher
        seen = []

        class Inner:
            def run(self, argv, timeout, *, env=None):
                seen.append((argv, timeout, env))
                return 0, '', ''

        env = {'ABG_PROXY': 'http://u:p@proxy.invalid:8126'}
        LabeledLauncher('inst-a', 'req-1', Inner()).run(['docker', 'run', '--rm', 'img'], 7, env=env)
        LabeledLauncher('inst-a', 'req-2', Inner()).run(['docker', 'ps'], 3)
        argv, timeout, passed = seen[0]
        self.assertEqual((timeout, passed, argv[:2]), (7, env, ['docker', 'run']))
        values = [argv[i + 1] for i, part in enumerate(argv) if part == '--label']
        self.assertEqual(set(values), {
            'abg.owner=ai-browser-gateway', 'abg.instance=inst-a',
            'abg.role=provider', 'abg.request=req-1'})
        self.assertFalse(any('http://' in part or 'u:p' in part for part in argv))
        self.assertEqual(seen[1][0], ['docker', 'ps'])

    def test_sweep_is_scoped_to_owner_instance_role(self):
        from gateway.service import sweep_providers
        calls = []

        class Result:
            stdout = 'cid1\n'

        with patch('gateway.service.subprocess.run', lambda cmd, **k: calls.append(cmd) or Result()):
            sweep_providers('run-7')
            sweep_providers('')
        listed, removed = calls
        self.assertEqual(listed[:3], ['docker', 'ps', '-aq'])
        self.assertIn('label=abg.owner=ai-browser-gateway', listed)
        self.assertIn('label=abg.instance=run-7', listed)
        self.assertIn('label=abg.role=provider', listed)
        self.assertEqual(removed[:3], ['docker', 'rm', '--force'])
        self.assertIn('cid1', removed)


class ImageContractTests(unittest.TestCase):
    def test_dockerfile_and_compose_pins(self):
        root = Path(__file__).resolve().parents[1]
        docker = (root / 'deploy/Dockerfile').read_text()
        compose = (root / 'deploy/compose.yaml').read_text()
        self.assertIn('sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6', docker)
        self.assertIn('sha256:eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66', docker)
        self.assertIn('127.0.0.1:${ABG_HOST_PORT:-8765}:8765', compose)
        self.assertNotIn('ABG_TOKEN:', compose)
        self.assertNotIn('/var/run/docker.sock', compose.split('monitor:')[1])
        self.assertTrue(stat.S_IXUSR & (root / 'scripts/abg-release').stat().st_mode)
        self.assertTrue(stat.S_IXUSR & (root / 'scripts/abg-provision').stat().st_mode)
