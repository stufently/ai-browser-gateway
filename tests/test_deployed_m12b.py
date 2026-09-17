"""Offline contract checks: no Docker daemon, network or real credentials."""
import copy
import io
import json
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            with self.subTest(error=error), self.assertRaises(d.CheckError):
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
