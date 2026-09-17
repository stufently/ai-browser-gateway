"""Offline contract checks: no Docker daemon, network or real credentials."""
import copy
from contextlib import ExitStack
import hashlib
import io
import json
import os
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.escalate import Step
from bench.models import ChallengeType, FailureReason
from tests import deployed_m12b as d


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
                moved = path.with_name(path.name + '.original')
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


if __name__ == '__main__':
    unittest.main()
