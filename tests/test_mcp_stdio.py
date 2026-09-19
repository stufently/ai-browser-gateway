"""Offline MCP contract tests; the HTTP boundary never reaches the network."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from gateway import mcp_stdio


ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'test-mcp-secret-9842'


def request(method, params=None, ident=1):
    value = dict(jsonrpc='2.0', id=ident, method=method)
    if params is not None:
        value['params'] = params
    return value


def reply(mode='text', ok=True):
    content = {'text': 'Page ✓', 'html': '<h1>Page</h1>', 'markdown': '# Page',
               'links': [{'text': 'Page', 'href': 'https://example.org/'}],
               'meta': {'title': 'Page', 'h1': ['Page']}}[mode]
    return dict(ok=ok, url='https://example.org/', final_url='https://example.org/final',
                provider='curl' if ok else None, age_hours=None,
                error_type='none' if ok else 'http_403', step='stop' if ok else 'human',
                elapsed_ms=17, format=mode, content=content if ok else '',
                attempts=[dict(provider='curl', egress_profile='direct', success=ok,
                               error_type='none' if ok else 'http_403', challenge='none',
                               elapsed_ms=17, status=200 if ok else 403, age_hours=None,
                               next_step='stop' if ok else 'human')])


class Response(io.BytesIO):
    def __init__(self, value, status=200):
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode())
        self.status = status


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ABG_TOKEN': TOKEN,
            'PATH': os.environ.get('PATH', os.defpath), 'PYTHONDONTWRITEBYTECODE': '1'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.http = patch('urllib.request.OpenerDirector.open')
        self.open = self.http.start()
        self.addCleanup(self.http.stop)
        self.open.side_effect = AssertionError('Unexpected HTTP request')

    def exchange(self, *messages, raw=None):
        wire = raw if raw is not None else ''.join(json.dumps(m) + '\n' for m in messages)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            mcp_stdio.serve(io.StringIO(wire), stdout)
        self.assertEqual(stderr.getvalue(), '')
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def initialize(self, version):
        return request('initialize', dict(protocolVersion=version, capabilities={},
                                         clientInfo=dict(name='test', version='0')))

    def call(self, args=None, version='2026-07-28'):
        return self.exchange(self.initialize(version), request('tools/call', dict(
            name='fetch_page', arguments={'url': 'https://example.org/'} if args is None else args)))[1]

    def stub(self, value, status=200):
        self.open.side_effect = lambda *a, **kw: Response(value, status)

    def test_negotiates_requested_old_version(self):
        result = self.exchange(self.initialize('2025-06-18'))[0]['result']
        self.assertEqual(result['protocolVersion'], '2025-06-18')

    def test_negotiates_latest_and_unknown_versions(self):
        for version in ('2026-07-28', '1999-01-01'):
            with self.subTest(version=version):
                result = self.exchange(self.initialize(version))[0]['result']
                self.assertEqual(result['protocolVersion'], '2026-07-28')
                self.assertTrue(result['capabilities']['tools'])
                project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
                self.assertEqual(result['serverInfo'], dict(name='ai-browser-gateway',
                                                           version=project['version']))

    def test_old_list_omits_new_fields(self):
        result = self.exchange(self.initialize('2025-06-18'), request('tools/list'))[1]['result']
        self.assertFalse({'resultType', 'cacheScope', 'ttlMs'} & result.keys())

    def test_new_list_and_schema(self):
        result = self.exchange(self.initialize('2026-07-28'), request('tools/list'))[1]['result']
        self.assertEqual(result['resultType'], 'complete')
        self.assertEqual(result['cacheScope'], 'private')
        self.assertIs(type(result['ttlMs']), int)
        self.assertEqual([t['name'] for t in result['tools']], ['fetch_page'])
        schema = result['tools'][0]['inputSchema']
        self.assertEqual(schema['type'], 'object')
        self.assertEqual(schema['required'], ['url'])
        props = schema['properties']
        self.assertEqual(set(props), {'url', 'format', 'expected_text', 'budget_ms',
                                     'allow_browser', 'max_age_hours'})
        self.assertEqual(props['format']['enum'], ['text', 'html', 'markdown', 'links', 'meta'])
        self.assertEqual(props['format']['default'], 'text')

    def test_success_all_formats_and_revisions(self):
        for version in ('2026-07-28', '2025-06-18'):
            for mode in ('text', 'html', 'markdown', 'links', 'meta'):
                with self.subTest(version=version, mode=mode):
                    value = reply(mode)
                    self.stub(value)
                    result = self.call(dict(url='https://example.org/', format=mode), version)['result']
                    self.assertFalse(result.get('isError', False))
                    text = result['content'][0]['text']
                    self.assertEqual(result['content'][0]['type'], 'text')
                    self.assertEqual(json.loads(text) if mode in ('links', 'meta') else text,
                                     value['content'])
                    self.assertEqual(result['structuredContent'], {k: value[k] for k in (
                        'ok', 'provider', 'step', 'error_type', 'elapsed_ms', 'final_url', 'attempts')})
                    self.assertEqual(result.get('resultType'),
                                     'complete' if version == '2026-07-28' else None)

    def test_gateway_failure_is_tool_error(self):
        self.stub(reply(ok=False))
        result = self.call()['result']
        self.assertIs(result.get('isError'), True)
        self.assertIn('http_403', result['content'][0]['text'])
        self.assertIn('human', result['content'][0]['text'])
        self.assertFalse(result['structuredContent']['ok'])

    def test_request_defaults_and_transport_policy(self):
        self.stub(reply())
        with patch('gateway.mcp_stdio.build_opener', wraps=mcp_stdio.build_opener) as build:
            self.call()
        req = self.open.call_args.args[0]
        self.assertEqual(req.full_url, 'http://127.0.0.1:8765/v1/fetch')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertEqual(json.loads(req.data), dict(url='https://example.org/', format='text',
            expected_text=None, budget_ms=30000, allow_browser=True, max_age_hours=0.0))
        self.assertEqual(self.open.call_args.kwargs['timeout'], 35)
        proxy, redirect = build.call_args.args
        self.assertEqual(proxy.proxies, {})
        self.assertIsNone(redirect.redirect_request(req, None, 302, '', {}, 'http://other/'))

    def test_explicit_arguments_and_endpoint(self):
        self.stub(reply())
        args = dict(url='https://example.org/', format='text', expected_text='Page',
                    budget_ms=180000, allow_browser=False, max_age_hours=2.5)
        with patch.dict(os.environ, {'ABG_URL': 'http://localhost:9876/v1/fetch'}):
            self.call(args)
        req = self.open.call_args.args[0]
        self.assertEqual(req.full_url, 'http://localhost:9876/v1/fetch')
        self.assertEqual(json.loads(req.data), args)
        self.assertEqual(self.open.call_args.kwargs['timeout'], 185)

    def test_token_file_default_expansion_and_env_precedence(self):
        self.stub(reply())
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / '.config/abg/client-token'
            path.parent.mkdir(parents=True)
            path.write_text('file-secret\r\n', encoding='ascii')
            for env, expected in (({'HOME': home}, 'file-secret'),
                                  ({'ABG_TOKEN_FILE': str(path)}, 'file-secret'),
                                  ({'ABG_TOKEN': TOKEN, 'ABG_TOKEN_FILE': '/missing'}, TOKEN)):
                with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                    result = self.call()['result']
                    self.assertFalse(result.get('isError', False))
                    self.assertEqual(self.open.call_args.args[0].get_header('Authorization'),
                                     'Bearer ' + expected)

    def test_invalid_arguments_are_rpc_errors_without_http(self):
        cases = [{}, {'url': 1}, {'url': 'https://user:pass@example.org/'},
                 {'url': 'file:///tmp/a'}]
        for key, values in dict(format=['pdf', [], None], budget_ms=[0, 180001, True, 1.5],
                                expected_text=[1, '', ' '], allow_browser=[0, 'true'],
                                max_age_hours=[-1, True, '1'], unknown=[1]).items():
            cases.extend(dict(url='https://example.org/', **{key: v}) for v in values)
        cases.extend([[], None, 'bad'])
        for args in cases:
            with self.subTest(args=args):
                message = request('tools/call', dict(name='fetch_page', arguments=args))
                self.assertEqual(self.exchange(message)[0]['error']['code'], -32602)
        self.open.assert_not_called()

    def test_transport_status_and_invalid_responses_are_tool_errors(self):
        failures = [URLError(TOKEN), HTTPError('http://user:pass@host/', 302, TOKEN, {}, None)]
        for exc in failures:
            with self.subTest(exc=type(exc).__name__):
                self.open.side_effect = exc
                result = self.call()
                self.assertIs(result['result']['isError'], True)
                self.assertNotIn(TOKEN, json.dumps(result))
                self.assertNotIn('user:pass', json.dumps(result))
        for value, status in ((reply(), 201), (reply(), 302), (b'bad ' + TOKEN.encode(), 200),
                              (b'{"ok":true,"ok":false}', 200), (b'{"x":NaN}', 200),
                              ({}, 200), (dict(reply(), content=[]), 200)):
            with self.subTest(status=status, value=value):
                self.stub(value, status)
                result = self.call()['result']
                self.assertIs(result['isError'], True)
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_invalid_configuration_does_not_leak(self):
        for env in ({'ABG_TOKEN': ''}, {'ABG_TOKEN': 'bad\nsecret'},
                    {'ABG_TOKEN_FILE': '/missing-secret'},
                    {'ABG_TOKEN': TOKEN, 'ABG_URL': 'http://user:pass@host/'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                result = self.call()['result']
                self.assertIs(result['isError'], True)
                self.assertNotIn('user:pass', json.dumps(result))
                self.assertNotIn('secret', json.dumps(result))
        self.open.assert_not_called()

    def test_nonfinite_extension_in_response_is_tool_error(self):
        value = reply()
        value['attempts'][0]['extension'] = float('inf')
        self.stub(json.dumps(value).replace('Infinity', '1e999').encode())
        result = self.call()['result']
        self.assertIs(result['isError'], True)

    def test_response_secrets_are_redacted_in_content_and_trace(self):
        for mode in ('text', 'links', 'meta'):
            value = reply(mode)
            secret = 'Authorization: Bearer ' + TOKEN + ' https://user:pass@host/private'
            value['content'] = {'text': secret, 'links': [{'text': 'link',
                'href': 'https://user:pass@host/'}], 'meta': {'title': secret, 'h1': []}}[mode]
            value['final_url'] = 'https://user:pass@host/'
            value['attempts'][0]['egress_profile'] = secret
            self.stub(value)
            wire = json.dumps(self.call())
            self.assertNotIn(TOKEN, wire)
            self.assertNotIn('user:pass@', wire)

    def test_parse_error_and_recovery(self):
        wire = '\n{\n{"a":1,"a":2}\nNaN\n' + json.dumps(request('tools/list')) + '\n'
        output = self.exchange(raw=wire)
        self.assertEqual([m['error']['code'] for m in output[:3]], [-32700] * 3)
        self.assertTrue(all(m['id'] is None for m in output[:3]))
        self.assertIn('result', output[3])

    def test_unknown_method_and_invalid_envelopes(self):
        self.assertEqual(self.exchange(request('missing'))[0]['error']['code'], -32601)
        for value in ([], None, 1, {}, dict(jsonrpc='1.0', id=1, method='tools/list'),
                      request(1), request('tools/list', ident=[]), request('tools/list', ident=True)):
            with self.subTest(value=value):
                self.assertEqual(self.exchange(value)[0]['error']['code'], -32600)
        for message in (request('tools/call', []), request('tools/call', {'name': 'other'}),
                        request('initialize', {}), request('tools/list', [])):
            with self.subTest(message=message):
                self.assertEqual(self.exchange(message)[0]['error']['code'], -32602)

    def test_notifications_have_no_response_or_http_side_effect(self):
        messages = [dict(jsonrpc='2.0', method=m) for m in (
            'notifications/initialized', 'missing', 'tools/call')]
        self.assertEqual(self.exchange(*messages), [])
        self.open.assert_not_called()

    def test_process_entrypoints_emit_only_jsonrpc(self):
        wire = '\n' + json.dumps(self.initialize('2025-06-18')) + '\n' + json.dumps(
            dict(jsonrpc='2.0', method='notifications/initialized')) + '\n' + json.dumps(
            request('tools/list', ident=2)) + '\n'
        for command in ([sys.executable, '-m', 'gateway.mcp_stdio'], [str(ROOT / 'scripts/abg-mcp')]):
            with self.subTest(command=command):
                proc = subprocess.run(command, input=wire, text=True, capture_output=True,
                                      cwd=ROOT, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stderr, '')
                messages = [json.loads(line) for line in proc.stdout.splitlines()]
                self.assertEqual([m['id'] for m in messages], [1, 2])
                self.assertTrue(all(m['jsonrpc'] == '2.0' for m in messages))
                self.assertEqual(messages[0]['result']['protocolVersion'], '2025-06-18')
                self.assertNotIn('resultType', messages[1]['result'])


if __name__ == '__main__':
    unittest.main()
