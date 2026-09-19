"""Offline contract checks: no Docker daemon, network or real credentials."""
import copy
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bench.escalate import Step
from bench.models import ChallengeType, FailureReason
from tests import deployed_m12b as d


def run_main(args):
    with patch.object(d.sys, 'argv', ['deployed_m12b.py', *args]):
        return d.main()


def outcome(ok=False):
    return dict(ok=ok, provider='curl' if ok else None, content='203.0.113.2' if ok else '',
                elapsed_ms=42, error_type='none' if ok else 'http_403',
                step='stop' if ok else 'human', attempts=[dict(
                    provider='curl', egress_profile='direct', status=200,
                    success=False, challenge='none', error_type='content_missing',
                    elapsed_ms=10, age_hours=None, next_step='change_egress'), dict(
                    provider='curl', egress_profile='ms2', status=200 if ok else 403,
                    success=ok, challenge='none' if ok else 'access_denied',
                    error_type='none' if ok else 'http_403', elapsed_ms=32,
                    age_hours=None, next_step='stop' if ok else 'human')])


class ClassificationTests(unittest.TestCase):
    def test_standalone_enum_constants_match_bench(self):
        for name, enum in [('FAILURE_REASONS', FailureReason),
                           ('CHALLENGE_TYPES', ChallengeType), ('STEPS', Step)]:
            with self.subTest(name=name):
                self.assertEqual(set(getattr(d, name, ())), {e.value for e in enum})

    def test_non_200_rejects_otherwise_valid_body(self):
        body = json.dumps(outcome(True))
        self.assertTrue(d.parse_api(200, body)['ok'])
        for status in (201, 301, 401, 500):
            with self.subTest(status=status), self.assertRaisesRegex(
                    d.CheckError, '^api_http_error$'):
                d.parse_api(status, body)

    def test_each_invalid_top_level_field_has_schema_error(self):
        cases = {
            'ok': [None, 0, 1, 'true', [], {}],
            'content': [None, 1, True, [], {}],
            'elapsed_ms': [-1, None, True, 1.5, '1'],
            'error_type': ['unknown', None, 1, [], {}],
            'step': ['unknown', None, 1, [], {}],
            'provider': [1, True, [], {}],
        }
        for field, invalids in cases.items():
            for invalid in invalids:
                value = outcome(True)
                value[field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaisesRegex(
                        d.CheckError, '^api_invalid_schema$'):
                    d.parse_api(200, json.dumps(value))
        for field in cases:
            value = outcome(True)
            del value[field]
            with self.subTest(missing=field), self.assertRaisesRegex(
                    d.CheckError, '^api_invalid_schema$'):
                d.parse_api(200, json.dumps(value))

    def test_each_invalid_attempt_field_has_attempt_error(self):
        cases = {
            'provider': [None, 1, True, [], {}],
            'egress_profile': ['unknown', 'ms0', 'ms16', None, [], {}],
            'status': [99, 600, -1, True, 200.0, '200', [], {}],
            'success': [None, 0, 1, 'true', [], {}],
            'challenge': ['unknown', None, 1, [], {}],
            'error_type': ['unknown', None, 1, [], {}],
            'next_step': ['unknown', None, 1, [], {}],
            'elapsed_ms': [-1, None, True, 1.5, '1'],
            'age_hours': [-1, -0.1, True, '1', [], {}, float('nan'),
                          float('inf'), float('-inf')],
        }
        for field, invalids in cases.items():
            for invalid in invalids:
                value = outcome(True)
                value['attempts'][1][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaisesRegex(
                        d.CheckError, '^api_invalid_attempts$'):
                    d.parse_api(200, json.dumps(value))
        for field in cases:
            value = outcome(True)
            del value['attempts'][1][field]
            with self.subTest(missing=field), self.assertRaisesRegex(
                    d.CheckError, '^api_invalid_attempts$'):
                d.parse_api(200, json.dumps(value))

    def test_valid_boundaries_and_enum_values_are_accepted(self):
        for field, values in {
                'status': [None, 100, 599], 'age_hours': [None, 0, 0.5, 10**400],
                'elapsed_ms': [0], 'success': [False, True],
                'egress_profile': ['direct', *('ms' + str(i) for i in range(1, 16))],
                'challenge': [e.value for e in ChallengeType],
                'next_step': [e.value for e in Step],
                'error_type': [e.value for e in FailureReason
                               if e.value not in ('provider_error', 'environment_error')],
        }.items():
            for valid in values:
                value = outcome(True)
                value['attempts'][1][field] = valid
                with self.subTest(field=field, valid=valid):
                    self.assertEqual(d.parse_api(200, json.dumps(value)), value)
        for field, values in {
                'ok': [False, True], 'provider': [None, '', 'curl'], 'elapsed_ms': [0],
                'step': [e.value for e in Step],
                'error_type': [e.value for e in FailureReason
                               if e.value not in ('provider_error', 'environment_error')],
        }.items():
            for valid in values:
                value = outcome(True)
                value[field] = valid
                with self.subTest(field=field, valid=valid):
                    self.assertEqual(d.parse_api(200, json.dumps(value)), value)

    def test_infrastructure_error_in_attempt_only_is_internal(self):
        for error in ('provider_error', 'environment_error'):
            for index in (0, 1):
                value = outcome()
                value['attempts'][index]['error_type'] = error
                with self.subTest(error=error, index=index), self.assertRaisesRegex(
                        d.CheckError, '^api_provider_infrastructure_error$'):
                    d.parse_api(200, json.dumps(value))

    def test_external_refusal_is_evidence_not_harness_error(self):
        result = d.parse_api(200, json.dumps(outcome()))
        self.assertFalse(result['ok'])
        self.assertEqual(result['attempts'][1]['status'], 403)
        self.assertEqual(result['attempts'][1]['challenge'], 'access_denied')
        self.assertEqual(result['attempts'][1]['elapsed_ms'], 32)

    def test_http_json_and_schema_failures_are_internal(self):
        for status, body in [(500, '{}'), (401, '{}'), (200, 'oops'),
                             (200, '[]'), (200, '{"ok":false}')]:
            with self.subTest(status=status, body=body), self.assertRaises(d.CheckError):
                d.parse_api(status, body)

    def test_malformed_attempts_do_not_silently_disappear(self):
        for attempts in [None, {}, ['oops'], [{'provider': 'curl'}]]:
            value = outcome()
            value['attempts'] = attempts
            with self.subTest(attempts=attempts), self.assertRaises(d.CheckError):
                d.parse_api(200, json.dumps(value))

    def test_docker_failure_is_not_external_target_failure(self):
        proc = subprocess.CompletedProcess([], 125, '', 'secret stderr')
        with patch.object(d.subprocess, 'run', return_value=proc):
            with self.assertRaisesRegex(d.CheckError, '^docker_failed$'):
                d.docker('version')

    def test_provider_infrastructure_failure_is_not_target_refusal(self):
        for error in ('provider_error', 'environment_error'):
            value = outcome()
            value['attempts'][1]['error_type'] = error
            value['error_type'] = error
            with self.subTest(error=error), self.assertRaisesRegex(
                    d.CheckError, '^api_provider_infrastructure_error$'):
                d.parse_api(200, json.dumps(value))

    def test_docker_missing_and_timeout_are_static_errors(self):
        for error in [FileNotFoundError('secret'), subprocess.TimeoutExpired('secret', 1)]:
            with patch.object(d.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(d.CheckError, '^docker_unavailable$'):
                    d.docker('version')

    def test_echo_classification_and_duplicate_ips(self):
        rows = [dict(name='ms1', status=200, ip='203.0.113.2', error=None),
                dict(name='ms2', status=200, ip='203.0.113.2', error=None),
                dict(name='ms3', status=200, ip='203.0.113.1', error=None),
                dict(name='ms4', status=407, ip=None, error=None),
                dict(name='ms5', status=None, ip=None, error='timeout'),
                dict(name='ms6', status=200, ip='203.0.113.6', error=None)]
        result = d.classify_profiles(rows, '203.0.113.1')
        self.assertEqual([r['failure_class'] for r in result],
                         ['duplicate_ip', 'duplicate_ip', 'direct_ip', 'http_407', 'timeout', None])

    def test_echo_invalid_body_is_failure(self):
        self.assertEqual(d.echo_result(200, 'not an IP')['error'], 'invalid_ip')
        self.assertEqual(d.echo_result(200, '203.0.113.5\n')['ip'], '203.0.113.5')
        self.assertIsNone(d.echo_result(403, '203.0.113.5')['ip'])


class RedactionTests(unittest.TestCase):
    def test_recursive_values_and_keys_hide_secrets(self):
        value = {'token': 'opaque-token', 'nest': ['http://alice:password@proxy:8126',
                 'https://hc-ping.com/private-check/fail', 'Bearer opaque-token'],
                 'opaque-token': 'token=opaque-token'}
        safe = json.dumps(d.redact(value, ['opaque-token']))
        for secret in ['opaque-token', 'alice', 'password', 'private-check', 'proxy:8126']:
            self.assertNotIn(secret, safe)

    def test_unlisted_token_and_url_are_redacted(self):
        raw = 'Bearer unusual-secret token=another-secret ' + 'a' * 64
        safe = d.redact(raw)
        for secret in ['unusual-secret', 'another-secret', 'a' * 64]:
            self.assertNotIn(secret, safe)

    def test_evidence_omits_content_and_urls_but_keeps_attempts(self):
        value = outcome(True)
        value.update(url='http://alice:password@proxy:8126', content='opaque-token')
        safe = d.api_evidence(value)
        self.assertNotIn('content', safe)
        self.assertNotIn('url', safe)
        self.assertEqual(safe['attempts'], value['attempts'])


class RotationTests(unittest.TestCase):
    def test_two_egress_attempts_are_not_proof(self):
        value = outcome(True)
        value['attempts'].append(dict(value['attempts'][1], egress_profile='ms3'))
        parsed = d.parse_api(200, json.dumps(value))
        with self.assertRaisesRegex(d.CheckError, '^egress_not_proven$'):
            d.first_egress(parsed)

    def test_wraparound_includes_intermediate_unhealthy_profiles(self):
        self.assertEqual(d.rotation_path('ms14', {'ms1', 'ms3', 'ms14'}),
                         ['ms15', 'ms1', 'ms2', 'ms3'])

    def test_two_consecutive_working_profiles(self):
        self.assertEqual(d.rotation_path('ms1', {'ms1', 'ms2', 'ms3'}), ['ms2', 'ms3'])

    def test_unknown_profile_or_insufficient_pool_fails(self):
        for first, working in [('unknown', {'ms1', 'ms2', 'ms3'}), ('ms1', {'ms1', 'ms2'})]:
            with self.assertRaises(d.CheckError):
                d.rotation_path(first, working)

    def test_rotation_requires_real_direct_miss_and_exact_success_profile(self):
        self.assertEqual(d.first_egress(outcome(True)), 'ms2')
        d.assert_egress(outcome(True), 'ms2', '203.0.113.2')
        variants = []
        for mutate in [lambda v: v.update(ok=False), lambda v: v.update(content='wrong'),
                       lambda v: v['attempts'][1].update(egress_profile='ms3'),
                       lambda v: v['attempts'][0].update(error_type='none'),
                       lambda v: v['attempts'][0].update(status=403)]:
            value = copy.deepcopy(outcome(True)); mutate(value); variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(d.CheckError):
                d.assert_egress(value, 'ms2', '203.0.113.2')

    def test_persistent_gap_applies_across_runner_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = [100.0]
            def sleep(seconds):
                clock[0] += seconds
            with patch.object(d.time, 'time', side_effect=lambda: clock[0]), \
                 patch.object(d.time, 'sleep', side_effect=sleep):
                d.wait_gap('http://api.ipify.org', Path(tmp))
                clock[0] = 105.0
                d.wait_gap('http://api.ipify.org', Path(tmp))
                self.assertEqual(clock[0], 130.0)
                d.wait_gap('https://example.com', Path(tmp))
                self.assertEqual(clock[0], 130.0)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.release = self.root / 'releases' / d.SHA
        self.release.mkdir(parents=True, mode=0o755)
        (self.release / 'bin').mkdir(mode=0o755)
        self.files = {'readme.txt': b'release\n', 'bin/run': b'#!/bin/sh\nexit 0\n'}
        for name, data in self.files.items():
            path = self.release / name
            path.write_bytes(data)
            path.chmod(0o755 if name == 'bin/run' else 0o644)
        self.manifest = self.root / 'manifests' / (d.SHA + '.sha256')
        self.manifest.parent.mkdir()
        self.manifest.write_text(''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                         for name, data in self.files.items()))

    def snapshot(self):
        return {str(p.relative_to(self.root)): (s.st_mode, s.st_mtime_ns, s.st_ctime_ns,
                                               s.st_size)
                for p in (self.root, *self.root.rglob('*')) for s in [p.lstat()]}

    def verify(self):
        self.assertTrue(callable(getattr(d, 'verify_release', None)),
                        'release verification must be available without deployment side effects')
        before = self.snapshot()
        original_open = Path.open
        def read_only(path, mode='r', *args, **kwargs):
            self.assertIn(mode, ('r', 'rb'), 'verification attempted a write')
            return original_open(path, mode, *args, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, 'open', read_only))
            for cls, names in [(Path, ('mkdir', 'chmod', 'write_text', 'write_bytes',
                                      'touch', 'unlink', 'rename', 'rmdir')),
                               (os, ('open', 'chmod', 'mkdir', 'write', 'rename', 'unlink')),
                               (d.subprocess, ('run',))]:
                for name in names:
                    stack.enter_context(patch.object(cls, name, side_effect=AssertionError(
                        'release verification must not mutate files or launch commands')))
            try:
                d.verify_release(self.release, self.manifest)
            finally:
                self.assertEqual(self.snapshot(), before)

    def test_valid_release_is_verified_without_writes_or_subprocess(self):
        self.verify()

    def test_missing_manifest_is_rejected_without_creating_it(self):
        self.manifest.unlink()
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()
        self.assertFalse(self.manifest.exists())

    def test_missing_release_is_rejected_without_creating_it(self):
        self.release = self.release.with_name('missing')
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()
        self.assertFalse(self.release.exists())

    def test_symlink_release_manifest_file_or_directory_is_rejected(self):
        for path in (self.release, self.manifest, self.release / 'readme.txt',
                     self.release / 'bin'):
            with self.subTest(path=path):
                # An extra file inside the release must not mask link following.
                moved = self.root / 'symlink-target'
                path.rename(moved)
                path.symlink_to(moved)
                try:
                    with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
                        self.verify()
                finally:
                    path.unlink()
                    moved.rename(path)

    def test_extra_missing_and_changed_file_are_rejected(self):
        extra = self.release / 'extra'
        extra.write_text('extra')
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()
        extra.unlink()
        path = self.release / 'readme.txt'
        path.unlink()
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()
        path.write_bytes(b'changed\n')
        path.chmod(0o644)
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()

    def test_wrong_file_and_directory_modes_are_rejected(self):
        for path, mode in ((self.release, 0o700), (self.release / 'bin', 0o775),
                           (self.release / 'readme.txt', 0o664),
                           (self.release / 'bin/run', 0o744),
                           (self.release / 'bin/run', 0o4755)):
            original = path.stat().st_mode & 0o7777
            path.chmod(mode)
            try:
                with self.subTest(path=path, mode=mode), self.assertRaisesRegex(
                        d.CheckError, '^release_integrity_failed$'):
                    self.verify()
            finally:
                path.chmod(original)

    def test_nonregular_release_entry_and_manifest_are_rejected(self):
        fifo = self.release / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()
        fifo.unlink()
        self.manifest.unlink()
        self.manifest.mkdir()
        with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
            self.verify()

    def test_malformed_duplicate_and_unsafe_manifest_entries_are_rejected(self):
        good = self.manifest.read_text()
        digest = hashlib.sha256(b'release\n').hexdigest()
        for content in ('', 'malformed\n', good + good, good.replace(digest, '0' * 64),
                        good + digest + '  ../outside\n', good + digest + '  /outside\n',
                        good + digest + '  bin/../readme.txt\n'):
            self.manifest.write_text(content)
            with self.subTest(content=content), self.assertRaisesRegex(
                    d.CheckError, '^release_integrity_failed$'):
                self.verify()

    def test_check_deploy_rejects_missing_manifest_before_external_checks(self):
        self.manifest.unlink()
        with patch.object(d, 'SERVICE', self.root), patch.object(d, 'RELEASE', self.release), \
             patch.object(d.subprocess, 'run', side_effect=AssertionError('external command')):
            with self.assertRaisesRegex(d.CheckError, '^release_integrity_failed$'):
                d.check_deploy()
        self.assertFalse(self.manifest.exists())


class MonitorLogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        service, release = root / 'service', root / 'release'
        secrets = service / 'secrets'
        secrets.mkdir(parents=True, mode=0o700)
        for name in ('token', 'proxies.toml', 'hc-ping'):
            path = secrets / name
            path.touch(mode=0o600)
        link = root / '.config/abg/client-token'
        link.parent.mkdir(parents=True)
        link.symlink_to(secrets / 'token')
        config = dict(ABG_RELEASE=release, ABG_TOKEN_FILE=secrets / 'token',
                      ABG_PROFILES_FILE=secrets / 'proxies.toml',
                      ABG_PING_FILE=secrets / 'hc-ping', ABG_INSTANCE='stand-host',
                      ABG_RUNTIME_IMAGE=d.IMAGE, ABG_DOCKER_GID='983',
                      ABG_HOST_PORT='8765', ABG_COMPOSE_PROJECT='ai-browser-gateway')
        (service / 'compose.env').write_text(''.join(f'{k}={v}\n' for k, v in config.items()))
        self.entries = {}
        for role in ('api', 'monitor'):
            mounts = {str(release): (str(release), False)}
            if role == 'api':
                mounts.update({'/var/run/docker.sock': ('/var/run/docker.sock', True),
                               '/run/abg/token': (str(secrets / 'token'), False),
                               '/run/abg/proxies.toml': (str(secrets / 'proxies.toml'), False)})
            else:
                mounts['/run/abg/ping'] = (str(secrets / 'hc-ping'), False)
            self.entries[role] = dict(
                Id=role, Image='image-id', RestartCount=0,
                State=dict(Running=True, StartedAt=datetime.now(timezone.utc).isoformat(),
                           Health={'Status': 'healthy'}),
                Config=dict(Labels={'com.docker.compose.service': role}, User='1002:1002',
                            WorkingDir=str(release),
                            Cmd=['python3', '-m', 'gateway.service' if role == 'api'
                                 else 'gateway.health_monitor'],
                            Env=['ABG_INSTANCE=stand-host'] if role == 'api'
                            else ['ABG_HEALTH_INTERVAL_SECONDS=60']),
                HostConfig=dict(GroupAdd=['983'] if role == 'api' else [],
                                ReadonlyRootfs=True, Tmpfs={'/tmp': ''}, Privileged=False,
                                RestartPolicy={'Name': 'unless-stopped'}),
                Mounts=[dict(Destination=dest, Source=src, RW=rw, Type='bind')
                        for dest, (src, rw) in mounts.items()],
                NetworkSettings=dict(Ports={'8765/tcp': [{'HostIp': '127.0.0.1',
                                                         'HostPort': '8765'}]}
                                     if role == 'api' else {}))
        self.full_logs = {'api': ('api stdout\n', 'api stderr\n'),
                          'monitor': ('', 'old URLError\n')}
        self.recent_logs = ('', '')
        self.recent_rc = 0
        self.scanned = None
        self.slept = 0
        self.log_commands = []
        original_stat = os.stat
        original_save = d.save
        def fake_stat(path, *args, **kwargs):
            if str(path) == '/var/run/docker.sock':
                return os.stat_result((0, 0, 0, 0, 0, 983, 0, 0, 0, 0))
            return original_stat(path, *args, **kwargs)
        for target, name, kwargs in (
                (d, 'SERVICE', {'new': service}), (d, 'RELEASE', {'new': release}),
                (d, 'save', {'side_effect': lambda name, value: original_save(name, value, root)}),
                (d, 'verify_release', {'return_value': None}),
                (Path, 'home', {'return_value': root}),
                (os, 'stat', {'side_effect': fake_stat}),
                (d.subprocess, 'run', {'side_effect': self.run_docker}),
                (d, 'worker_call', {'side_effect': self.worker_call}),
                (d.time, 'sleep', {'side_effect': self.sleep})):
            self.stack.enter_context(patch.object(target, name, **kwargs))
        self.evidence = root / 'deploy.json'
        self.service = service
        self.root = root

    def test_custom_release_controls_config_manifest_image_workdir_and_mounts(self):
        sha = '1234567890abcdef1234567890abcdef12345678'
        release = self.service / 'releases' / sha
        evidence = self.root / 'custom-evidence'
        config_path = self.service / 'compose.env'
        config_path.write_text(config_path.read_text().replace(
            str(d.RELEASE), str(release)).replace(d.IMAGE, 'abg-runtime:1234567890ab'))
        for entry in self.entries.values():
            entry['Config']['WorkingDir'] = str(release)
            entry['Mounts'][0].update(Source=str(release), Destination=str(release))
        real_check = d.check_deploy
        def check():
            self.assertEqual(d.SHA, sha)
            self.assertEqual(d.RELEASE, release)
            self.assertEqual(d.IMAGE, 'abg-runtime:1234567890ab')
            self.assertEqual(d.EVIDENCE, evidence)
            real_check()
            d.verify_release.assert_called_with(
                release, self.service / 'manifests' / (sha + '.sha256'))
            for role in ('api', 'monitor'):
                entry = self.entries[role]
                entry['Config']['WorkingDir'] = '/old-release'
                with self.assertRaisesRegex(d.CheckError, '^container_identity$'):
                    real_check()
                entry['Config']['WorkingDir'] = str(release)
                entry['Mounts'][0]['Source'] = '/old-release'
                with self.assertRaisesRegex(d.CheckError, '^container_mounts$'):
                    real_check()
                entry['Mounts'][0]['Source'] = str(release)
            config_path.write_text(config_path.read_text().replace(
                'abg-runtime:1234567890ab', 'abg-runtime:old'))
            with self.assertRaisesRegex(d.CheckError, '^compose_env_mismatch$'):
                real_check()
        with patch.object(d, 'SHA'), patch.object(d, 'IMAGE'), patch.object(d, 'EVIDENCE'), \
             patch.object(d, 'check_deploy', side_effect=check), \
             patch.object(d.sys, 'stdout', io.StringIO()):
            self.assertEqual(run_main(['--check-deploy', '--release', sha,
                                     '--evidence', str(evidence)]), 0)
        self.assertTrue((evidence / 'runner.lock').exists())
        self.assertEqual(json.loads(self.evidence.read_text())['release_sha'], sha)

    def sleep(self, seconds):
        self.slept += seconds

    def run_docker(self, args, **kwargs):
        self.assertEqual(args[0], 'docker')
        command = args[1:]
        stdout, stderr, rc = '', '', 0
        if command == ['ps', '-aq', '--filter', 'label=com.docker.compose.project=ai-browser-gateway']:
            stdout = 'api\nmonitor\n'
        elif command[0] == 'inspect':
            stdout = json.dumps([self.entries[command[1]]])
        elif command == ['image', 'inspect', d.IMAGE]:
            stdout = json.dumps([{'Id': 'image-id'}])
        elif command[0] == 'logs':
            self.log_commands.append(command)
            if command == ['logs', '--since', '150s', 'monitor']:
                self.assertGreaterEqual(self.slept, 130)
                stdout, stderr = self.recent_logs
                rc = self.recent_rc
            else:
                self.assertIn(command, (['logs', 'api'], ['logs', 'monitor']))
                stdout, stderr = self.full_logs[command[1]]
        elif command in (['--version'], ['compose', 'version'],
                         ['exec', 'api', 'python3', '--version']):
            stdout = 'test-version\n'
        else:
            self.fail(f'unexpected Docker command: {command}')
        return subprocess.CompletedProcess(args, rc, stdout, stderr)

    def worker_call(self, action, **payload):
        if action == 'scan':
            self.scanned = payload['metadata']
            return {'ok': True}
        if action == 'health':
            return {'status': 200, 'body': {'ok': True}}
        if action == 'unauthorized':
            return {'status': 401}
        self.fail(f'unexpected worker action: {action}')

    def test_old_error_outside_window_passes_and_full_logs_are_scanned(self):
        d.check_deploy()
        self.assertEqual([row['logs'] for row in self.scanned],
                         ['api stdout\napi stderr\n', 'old URLError\n'])
        self.assertIn(['logs', '--since', '150s', 'monitor'], self.log_commands)
        evidence = json.loads(self.evidence.read_text())
        self.assertIs(evidence['monitor_recent_logs_empty'], True)
        self.assertEqual(evidence['monitor_log_window_seconds'], 150)
        self.assertNotIn('monitor_logs_empty', evidence)

    def test_recent_error_in_either_stream_rejects_deployment(self):
        # The error arrives between the full-log read and the window read.
        self.full_logs['monitor'] = ('', '')
        for streams in (('URLError\n', ''), ('', 'URLError\n')):
            self.recent_logs = streams
            with self.subTest(streams=streams), self.assertRaisesRegex(
                    d.CheckError, '^monitor_delivery_errors$'):
                d.check_deploy()
        self.assertFalse(self.evidence.exists())

    def test_recent_log_command_failure_is_not_an_empty_window(self):
        self.full_logs['monitor'] = ('', '')
        self.recent_rc = 1
        with self.assertRaisesRegex(d.CheckError, '^docker_logs_failed$'):
            d.check_deploy()
        self.assertFalse(self.evidence.exists())


class WorkerTests(unittest.TestCase):
    def test_module_loads_at_container_root_mount(self):
        # Docker binds the single file at /runner.py, with only one parent.
        with patch.object(Path, 'resolve', return_value=Path('/runner.py')):
            module = runpy.run_path(d.__file__)
        self.assertTrue(callable(module['worker']))

    def invoke(self, payload):
        output = io.StringIO()
        with patch.object(d.sys, 'stdin', io.StringIO(json.dumps(payload))), \
             patch.object(d.sys, 'stdout', output):
            d.worker()
        return json.loads(output.getvalue())

    def test_http_connection_failure_is_external_only_for_echo(self):
        with patch('http.client.HTTPConnection.request', side_effect=OSError('secret')):
            result = self.invoke({'action': 'echo'})
        self.assertEqual(result['error'], 'connection_error')
        self.assertNotIn('internal_error', result)

    def test_missing_profile_file_is_internal_not_proxy_failure(self):
        with patch.object(Path, 'read_text', side_effect=OSError('secret')):
            result = self.invoke({'action': 'echo', 'name': 'ms1'})
        self.assertIn('internal_error', result)

    def test_api_connection_failure_is_internal(self):
        with patch.object(Path, 'read_text', return_value='fake-token'), \
             patch('urllib.request.OpenerDirector.open', side_effect=OSError('fake-token')):
            result = self.invoke({'action': 'api', 'request': {'expected_text': 'expected'}})
        self.assertIn('internal_error', result)
        self.assertNotIn('fake-token', json.dumps(result))

    def test_api_http_error_preserves_status(self):
        from urllib.error import HTTPError
        error = HTTPError('http://gateway.invalid/', 500, 'secret-tok', {},
                          io.BytesIO(b'secret response body'))
        with patch.object(Path, 'read_text', return_value='fake-token'), \
             patch('urllib.request.OpenerDirector.open', side_effect=error):
            result = self.invoke({'action': 'api', 'request': {}})
        expected = {'internal_error': 'worker_check', 'cause': 'api_http_error:500'}
        self.assertEqual(result, expected)

    def test_api_parse_failures_preserve_code_and_status(self):
        for action in ('api', 'bizprofile'):
            for status, body, cause in (
                    (500, b'private body', 'api_http_error:500'),
                    (200, b'{"ok": true}', 'api_invalid_schema:200'),
                    (200, b'invalid json', 'api_invalid_json:200')):
                with self.subTest(action=action, cause=cause):
                    response = MagicMock()
                    response.__enter__.return_value = response
                    response.status = status
                    response.read.return_value = body
                    with patch.object(Path, 'read_text', return_value='fake-token'), \
                         patch('urllib.request.OpenerDirector.open', return_value=response):
                        result = self.invoke({'action': action, 'request': {}})
                    self.assertEqual(result, {'internal_error': 'worker_check', 'cause': cause})

    def test_worker_transport_and_unexpected_failures(self):
        for error, expected in (
                (OSError('secret-tok'), {'internal_error': 'worker_connection'}),
                (TimeoutError('secret-tok'), {'internal_error': 'worker_timeout'}),
                (ValueError('secret-tok'),
                 {'internal_error': 'worker_failure', 'cause': 'ValueError'})):
            with self.subTest(error=type(error).__name__):
                with patch.object(Path, 'read_text', return_value='fake-token'), \
                     patch('urllib.request.OpenerDirector.open', side_effect=error):
                    result = self.invoke({'action': 'api', 'request': {}})
                self.assertEqual(result, expected)
                self.assertNotIn('secret-tok', json.dumps(result))

    def test_worker_check_outside_api_preserves_static_code(self):
        self.assertEqual(self.invoke({'action': 'unknown'}),
                         {'internal_error': 'worker_check', 'cause': 'unknown_worker_action'})

    def test_worker_call_reports_failure_cause(self):
        results = []
        for payload in (
                {'internal_error': 'worker_check', 'cause': 'api_http_error:500'},
                {'internal_error': 'worker_connection'},
                {'internal_error': 'worker_timeout'},
                {'internal_error': 'worker_failure', 'cause': 'ValueError'}):
            with patch.object(d, 'docker', return_value=json.dumps(payload)), \
                 self.assertRaises(d.CheckError) as raised:
                d.worker_call('api', request={})
            results.append(str(raised.exception))
        expected = [
            'worker_internal_error:worker_check:api_http_error:500',
            'worker_internal_error:worker_connection',
            'worker_internal_error:worker_timeout',
            'worker_internal_error:worker_failure:ValueError',
        ]
        self.assertEqual(results, expected)

    def test_worker_call_redacts_secrets_in_cause(self):
        for cause, redacted in (
                ('token=secret-tok', 'token=[redacted]'),
                ('https://user:secret-tok@example.invalid/path', '[url]'),
                ('Bearer secret-tok', 'Bearer [redacted]'),
                ('a' * 64, '[redacted]')):
            with self.subTest(cause=cause):
                payload = {'internal_error': 'worker_check', 'cause': cause}
                with patch.object(d, 'docker', return_value=json.dumps(payload)), \
                     self.assertRaises(d.CheckError) as raised:
                    d.worker_call('api', request={})
                message = str(raised.exception)
                self.assertEqual(message, 'worker_internal_error:worker_check:' + redacted)
                self.assertNotIn(cause, message)
                self.assertNotIn('secret-tok', message)

    def test_worker_call_rejects_non_dictionary_response(self):
        for payload in ([], None, 'response', 42):
            with self.subTest(payload=payload), \
                 patch.object(d, 'docker', return_value=json.dumps(payload)), \
                 self.assertRaisesRegex(d.CheckError, '^worker_invalid_schema$'):
                d.worker_call('health')

    def test_http_actions_send_authorization_only_for_api_requests(self):
        for action, endpoint, authorization, status, body in (
                ('bizprofile', '/v1/fetch', 'Bearer worker-token', 200, outcome(True)),
                ('api', '/v1/fetch', 'Bearer worker-token', 200, outcome(True)),
                ('health', '/health', None, 200, {'ok': True}),
                ('unauthorized', '/v1/fetch', None, 401, {'detail': 'Unauthorized'})):
            with self.subTest(action=action):
                response = MagicMock()
                response.__enter__.return_value = response
                response.status = status
                response.read.return_value = json.dumps(body).encode()
                with patch.object(Path, 'read_text', autospec=True,
                                  return_value=' \tworker-token\r\n') as read_token, \
                     patch('urllib.request.OpenerDirector.open',
                           return_value=response) as http:
                    result = self.invoke({'action': action,
                                          'request': {'expected_text': '203.0.113.2'},
                                          'marker': '203.0.113.2'})
                http.assert_called_once()
                request = http.call_args.args[0]
                self.assertEqual(request.full_url, 'http://127.0.0.1:8765' + endpoint)
                # Assert outside worker(), which catches AssertionError as worker_failure.
                self.assertEqual(request.get_header('Authorization'), authorization)
                if authorization is None:
                    read_token.assert_not_called()
                    self.assertEqual(result['status'], status)
                else:
                    read_token.assert_called_once_with(Path('/run/token'))
                self.assertNotIn('internal_error', result)
                self.assertNotIn('worker-token', json.dumps(result))

    def test_fake_http_refusal_preserves_attempts_but_drops_body(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(outcome()).encode()
        with patch.object(Path, 'read_text', return_value='fake-token'), \
             patch('urllib.request.OpenerDirector.open', return_value=Response()):
            result = self.invoke({'action': 'api', 'request': {'expected_text': 'expected'}})
        self.assertFalse(result['ok'])
        self.assertEqual(result['attempts'][1]['status'], 403)
        self.assertNotIn('content', result)


class ArgumentTests(unittest.TestCase):
    def test_defaults_remain_compatible_without_creating_default_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            folder = Path(tmp)
            for name in ('SHA', 'RELEASE', 'IMAGE', 'EVIDENCE'):
                stack.enter_context(patch.object(d, name, getattr(d, name)))
            stack.enter_context(patch.object(d.sys, 'stdout', io.StringIO()))
            def check():
                self.assertEqual(d.SHA, '929bded313e371808b0747fd9a400696a36638aa')
                self.assertEqual(d.IMAGE, 'abg-runtime:929bded313e3')
                self.assertEqual(d.RELEASE, d.SERVICE / 'releases' / d.SHA)
                self.assertEqual(d.EVIDENCE, Path('/home/user/.cache/abg-coord-20260917/m12b'))
            stack.enter_context(patch.object(d, 'check_deploy', side_effect=check))
            stack.enter_context(patch.object(Path, 'mkdir'))
            stack.enter_context(patch.object(d.os, 'chmod'))
            stack.enter_context(patch.object(d, 'save'))
            real_open = Path.open
            stack.enter_context(patch.object(Path, 'open', lambda path, *a, **kw:
                real_open(folder / path.name, *a, **kw)))
            self.assertEqual(run_main(['--check-deploy']), 0)

    def test_invalid_arguments_fail_before_any_disk_or_external_action(self):
        for option, value in [('--release', '123'), ('--release', 'A' * 40),
                              ('--release', 'g' * 40), ('--evidence', 'relative/path')]:
            with self.subTest(option=option, value=value), ExitStack() as stack:
                output = io.StringIO()
                stack.enter_context(patch.object(d.sys, 'stderr', output))
                for target, names in ((Path, ('mkdir', 'open', 'write_text', 'write_bytes')),
                                      (os, ('open', 'chmod', 'mkdir')),
                                      (d.subprocess, ('run',)), (d, ('worker_call',))):
                    for name in names:
                        stack.enter_context(patch.object(target, name,
                            side_effect=AssertionError('side effect before validation')))
                with self.assertRaises(SystemExit) as raised:
                    run_main(['--check-deploy', option, value])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(option, output.getvalue())
                self.assertNotIn('unrecognized', output.getvalue())


class BizprofileTests(unittest.TestCase):
    urls = ('https://bizprofile.net/',
            'https://bizprofile.net/ny/albany/elevate-electric-llc')
    markers = ('Comprehensive Directory of Registered Businesses', 'Elevate Electric LLC')

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / 'evidence'
        for name in ('SHA', 'RELEASE', 'IMAGE', 'EVIDENCE'):
            self.stack.enter_context(patch.object(d, name, getattr(d, name)))
        self.clock = 100.0
        self.calls = []
        self.values = []
        for marker in self.markers:
            value = outcome(True)
            value.update(provider='scrapling', content=marker + ' private page body')
            value['attempts'][-1]['provider'] = 'scrapling'
            self.values.append(value)
        self.stack.enter_context(patch.object(d.time, 'time', side_effect=lambda: self.clock))
        self.stack.enter_context(patch.object(d.time, 'sleep', side_effect=self.sleep))
        self.stack.enter_context(patch.object(d, 'docker', side_effect=self.fake_docker))
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.stack.enter_context(patch.object(d.sys, 'stdout', self.stdout))
        self.stack.enter_context(patch.object(d.sys, 'stderr', self.stderr))

    def sleep(self, seconds):
        self.clock += seconds

    def fake_docker(self, *args, input=None, **kwargs):
        self.assertIn('/runner.py', ' '.join(args))
        self.assertEqual(args[args.index('--network') + 1], 'host')
        output = io.StringIO()
        with patch.object(d.sys, 'stdin', io.StringIO(input)), \
             patch.object(d.sys, 'stdout', output), \
             patch.object(Path, 'read_text', return_value='fake-token'), \
             patch('urllib.request.OpenerDirector.open', side_effect=self.fake_http):
            d.worker()
        raw = output.getvalue()
        for secret in ('fake-token', 'private page body', *self.urls):
            self.assertNotIn(secret, raw)
        return raw

    def fake_http(self, request, **kwargs):
        self.assertEqual(request.full_url, 'http://127.0.0.1:8765/v1/fetch')
        body = json.loads(request.data)
        self.calls.append((body, self.clock))
        value = self.values[len(self.calls) - 1]
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(value).encode()
        return Response()

    def run_check(self):
        return run_main(['--check-bizprofile', '--release', 'a' * 40,
                       '--evidence', str(self.folder)])

    def evidence(self):
        latest = self.folder / 'bizprofile.json'
        evidence = json.loads(latest.read_text())
        self.assertEqual(evidence['release_sha'], 'a' * 40)
        self.assertEqual(len(evidence['pages']), 2)
        for row in evidence['pages']:
            self.assertIn('api_evidence', row)
            self.assertIs(type(row['marker_found']), bool)
        safe = json.dumps(evidence)
        for forbidden in ('"content":', '"url":', 'private page body', *self.urls):
            self.assertNotIn(forbidden, safe)
        archives = list(self.folder.glob('bizprofile-*.json'))
        self.assertEqual(len(archives), 1)
        self.assertRegex(archives[0].name, r'^bizprofile-\d{8}T\d{6}Z\.json$')
        self.assertEqual(archives[0].read_bytes(), latest.read_bytes())
        return evidence

    def test_green_requests_are_sequential_spaced_and_without_expected_text(self):
        self.assertEqual(self.run_check(), 0, self.stderr.getvalue())
        self.assertEqual(len(self.calls), 2)
        for (body, stamp), url in zip(self.calls, self.urls):
            self.assertEqual(body, dict(url=url, allow_browser=True, budget_ms=120000,
                                        format='text', max_age_hours=0))
        self.assertGreaterEqual(self.calls[1][1] - self.calls[0][1], 30)
        self.assertEqual(json.loads((self.folder / 'request-times.json').read_text()),
                         {'bizprofile.net': self.calls[1][1]})
        self.assertTrue((self.folder / 'runner.lock').exists())
        evidence = self.evidence()
        self.assertTrue(all(row['marker_found'] for row in evidence['pages']))
        self.assertEqual(evidence['pages'][0]['api_evidence']['attempts'], self.values[0]['attempts'])

    def test_each_failure_records_both_pages_without_retry(self):
        mutations = [lambda v: v.update(ok=False), lambda v: v.update(provider='curl'),
                     lambda v: v['attempts'][-1].update(provider='curl'),
                     lambda v: v['attempts'][-1].update(challenge='suspected'),
                     lambda v: v['attempts'][-1].update(success=False),
                     lambda v: v['attempts'][-1].update(error_type='http_403'),
                     lambda v: v.update(content='missing marker'),
                     lambda v: v.update(attempts=[])]
        for index, mutate in enumerate(mutations):
            for page in (0, 1):
                with self.subTest(mutation=index, page=page):
                    original = copy.deepcopy(self.values)
                    mutate(self.values[page])
                    self.folder = self.folder.parent / f'failure-{index}-{page}'
                    self.calls.clear()
                    self.stderr.seek(0)
                    self.stderr.truncate()
                    self.assertEqual(self.run_check(), 1)
                    self.assertIn('bizprofile_not_passed', self.stderr.getvalue())
                    self.assertEqual([body['url'] for body, stamp in self.calls], list(self.urls))
                    self.evidence()
                    self.values = original

    def test_malformed_api_response_is_parsed_and_second_page_still_measured(self):
        self.values[0]['ok'] = 'true'
        self.assertEqual(self.run_check(), 1)
        self.assertIn('bizprofile_not_passed', self.stderr.getvalue())
        self.assertEqual(len(self.calls), 2)
        evidence = self.evidence()
        self.assertFalse(evidence['pages'][0]['marker_found'])
        self.assertTrue(evidence['pages'][1]['marker_found'])

    def test_archive_collision_never_overwrites_previous_measurement(self):
        self.folder.mkdir()
        archive = self.folder / 'bizprofile-20260917T120000Z.json'
        archive.write_text('previous measurement\n')
        real_open = os.open
        flags_seen = []
        def open_file(path, flags, *args, **kwargs):
            if Path(path).name.startswith('bizprofile-'):
                flags_seen.append(flags)
            return real_open(path, flags, *args, **kwargs)
        with patch.object(d, 'datetime') as dates, patch.object(os, 'open', side_effect=open_file):
            dates.now.side_effect = [datetime(2026, 9, 17, 12, tzinfo=timezone.utc),
                                     datetime(2026, 9, 17, 12, 0, 1, tzinfo=timezone.utc)]
            self.assertEqual(self.run_check(), 0, self.stderr.getvalue())
        self.assertEqual(archive.read_text(), 'previous measurement\n')
        self.assertEqual(len(flags_seen), 2)
        self.assertTrue(all(flags & os.O_EXCL for flags in flags_seen))
        self.assertEqual((self.folder / 'bizprofile-20260917T120001Z.json').read_bytes(),
                         (self.folder / 'bizprofile.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
