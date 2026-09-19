"""Offline MCP contract tests; the HTTP boundary never reaches the network."""
import contextlib
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
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
    if not ok:
        content = {'links': [], 'meta': {}}.get(mode, '')
    return dict(ok=ok, url='https://example.org/', final_url='https://example.org/final',
                provider='curl' if ok else None, age_hours=None,
                error_type='none' if ok else 'http_403', step='stop' if ok else 'human',
                elapsed_ms=17, format=mode, content=content,
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

    def call(self, args=None, version='2025-11-25'):
        return self.exchange(self.initialize(version), request('tools/call', dict(
            name='fetch_page', arguments={'url': 'https://example.org/'} if args is None else args)))[1]

    def stub(self, value, status=200):
        self.open.side_effect = lambda *a, **kw: Response(value, status)

    @contextlib.contextmanager
    def running_exchange(self, release):
        incoming, outgoing, errors = queue.Queue(), queue.Queue(), queue.Queue()
        eof = threading.Event()

        def lines():
            for message in iter(incoming.get, None):
                yield json.dumps(message) + '\n'
            eof.set()

        class Output:
            def write(self, line):
                # Every write must contain exactly one complete JSON-RPC line.
                if not line.endswith('\n') or len(line.splitlines()) != 1:
                    raise AssertionError('partial or interleaved output')
                outgoing.put(json.loads(line))

            def flush(self):
                pass

        def run():
            try:
                mcp_stdio.serve(lines(), Output())
            except Exception as exc:
                errors.put(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            yield incoming, outgoing, eof, thread
        finally:
            release.set()
            incoming.put(None)
            thread.join(10)
            self.assertFalse(thread.is_alive(), 'stdio server did not finish')
            if not errors.empty():
                raise errors.get_nowait()

    def test_worker_output_failure_triggers_handler(self):
        handled = threading.Event()
        before_eof = []
        writing_threads = []
        serving_thread = threading.current_thread()

        def lines():
            yield json.dumps(request('tools/call', dict(
                name='fetch_page', arguments={}))) + '\n'
            # Keep stdin open until the handler runs; a missing handler must
            # fail an assertion rather than leave the test runner hanging.
            before_eof.append(handled.wait(2))

        class Output:
            def write(self, line):
                writing_threads.append(threading.current_thread())
                raise BrokenPipeError(TOKEN)

            def flush(self):
                pass

        with self.assertRaises(BrokenPipeError):
            mcp_stdio.serve(lines(), Output(), on_output_error=handled.set)
        self.assertEqual(before_eof, [True])
        self.assertEqual(len(writing_threads), 1)
        self.assertIsNot(writing_threads[0], serving_thread)
        self.open.assert_not_called()

    def test_ping_answered_during_slow_call(self):
        started, release = threading.Event(), threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(10)
            return Response(reply())

        self.open.side_effect = slow
        with self.running_exchange(release) as (incoming, outgoing, eof, thread):
            incoming.put(request('tools/call', dict(name='fetch_page', arguments={
                'url': 'https://example.org/'}), ident=2))
            self.assertTrue(started.wait(5))
            incoming.put(request('ping', ident=3))
            try:
                first = outgoing.get(timeout=1)
            except queue.Empty:
                first = None
            self.assertEqual(first, dict(jsonrpc='2.0', id=3, result={}))
            release.set()
            self.assertEqual(outgoing.get(timeout=5)['id'], 2)

    def test_tool_calls_run_concurrently_and_bounded(self):
        started, release = queue.Queue(), threading.Event()
        active = peak = 0
        lock = threading.Lock()

        def slow(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            started.put(True)
            try:
                release.wait(10)
                return Response(reply())
            finally:
                with lock:
                    active -= 1

        self.open.side_effect = slow
        with self.running_exchange(release) as (incoming, outgoing, eof, thread):
            for ident in range(20):
                incoming.put(request('tools/call', dict(name='fetch_page', arguments={
                    'url': 'https://example.org/'}), ident=ident))
            count = 0
            try:
                for _ in range(8):
                    started.get(timeout=5)
                    count += 1
            except queue.Empty:
                pass
            self.assertEqual(count, 8, 'tool calls did not run concurrently')
            incoming.put(request('ping', ident='ping'))
            incoming.put(request('tools/list', ident='list'))
            self.assertEqual(outgoing.get(timeout=1), dict(jsonrpc='2.0', id='ping', result={}))
            self.assertEqual(outgoing.get(timeout=1)['id'], 'list')
            with self.assertRaises(queue.Empty):
                started.get(timeout=0.1)
            incoming.put(None)
            self.assertTrue(eof.wait(5), 'queued calls blocked stdin')
            release.set()
            messages = [outgoing.get(timeout=5) for _ in range(20)]
            self.assertEqual({m['id'] for m in messages}, set(range(20)))
            self.assertTrue(all(m['result']['structuredContent']['content'] == 'Page ✓'
                                for m in messages))
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(peak, 8)
        self.assertEqual(self.open.call_count, 20)

    def test_eof_waits_for_inflight_calls(self):
        started, release = threading.Event(), threading.Event()

        def slow(*args, **kwargs):
            started.set()
            release.wait(10)
            return Response(reply())

        self.open.side_effect = slow
        with self.running_exchange(release) as (incoming, outgoing, eof, thread):
            incoming.put(request('tools/call', dict(name='fetch_page', arguments={
                'url': 'https://example.org/'}), ident=9))
            self.assertTrue(started.wait(5))
            incoming.put(None)
            self.assertTrue(eof.wait(5))
            self.assertTrue(thread.is_alive())
            self.assertTrue(outgoing.empty())
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            result = outgoing.get(timeout=1)
            self.assertEqual(result['id'], 9)
            self.assertEqual(result['result']['structuredContent']['content'], 'Page ✓')

    def test_negotiates_requested_old_version(self):
        result = self.exchange(self.initialize('2025-06-18'))[0]['result']
        self.assertEqual(result['protocolVersion'], '2025-06-18')

    def test_negotiates_latest_and_unknown_versions(self):
        for version in ('2025-11-25', '2026-07-28', '1999-01-01'):
            with self.subTest(version=version):
                result = self.exchange(self.initialize(version))[0]['result']
                self.assertEqual(result['protocolVersion'], '2025-11-25')
                self.assertTrue(result['capabilities']['tools'])
                project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
                self.assertEqual(result['serverInfo'], dict(name='ai-browser-gateway',
                                                           version=project['version']))

    def test_supported_revisions_omit_new_fields(self):
        for version in ('2025-11-25', '2025-06-18'):
            with self.subTest(version=version):
                results = self.exchange(self.initialize(version), request('tools/list'),
                                        request('ping'))
                for ok in (True, False):
                    self.stub(reply(ok=ok))
                    results.append(self.call(version=version))
                for message in results:
                    self.assertFalse({'resultType', 'cacheScope', 'ttlMs'} & message['result'].keys())

    def test_ping_returns_empty_result(self):
        result = self.exchange(self.initialize('2025-11-25'), request('ping', ident=3))[1]
        self.assertEqual(result, dict(jsonrpc='2.0', id=3, result={}))
        self.open.assert_not_called()

    def test_claude_code_initialize_frame(self):
        wire = ('{"method":"initialize","params":{"protocolVersion":"2025-11-25",'
                '"capabilities":{"roots":{"listChanged":true},"elicitation":{}},'
                '"clientInfo":{"name":"claude-code","title":"Claude Code",'
                '"version":"2.1.278","description":"Anthropic agentic coding tool",'
                '"websiteUrl":"https://claude.com/claude-code"}},"jsonrpc":"2.0","id":0}\n')
        proc = subprocess.run([sys.executable, '-m', 'gateway.mcp_stdio'], input=wire,
                              text=True, capture_output=True, cwd=ROOT, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, '')
        messages = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['id'], 0)
        self.assertEqual(messages[0]['result']['protocolVersion'], '2025-11-25')

    def test_list_and_schema(self):
        result = self.exchange(self.initialize('2025-11-25'), request('tools/list'))[1]['result']
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
        for version in ('2025-11-25', '2025-06-18'):
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
                    self.assertEqual(result['structuredContent'], dict(content=text, **{
                        k: value[k] for k in ('ok', 'provider', 'step', 'error_type',
                                              'elapsed_ms', 'final_url', 'attempts')}))

    def test_structured_content_carries_page_text(self):
        self.stub(reply())
        result = self.call()['result']
        self.assertEqual(result['structuredContent'].get('content'), 'Page ✓')
        for version in ('2025-11-25', '2025-06-18'):
            for mode in ('text', 'html', 'markdown', 'links', 'meta'):
                for ok in (True, False):
                    with self.subTest(version=version, mode=mode, ok=ok):
                        value = reply(mode, ok)
                        self.stub(value)
                        result = self.call(dict(url='https://example.org/', format=mode), version)['result']
                        expected = (json.dumps(value['content'], ensure_ascii=False)
                                    if mode in ('links', 'meta') else value['content'])
                        if not ok:
                            expected = 'fetch_failed: http_403; step: human'
                        self.assertEqual(result['content'], [dict(type='text', text=expected)])
                        self.assertEqual(result['structuredContent']['content'], expected)

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

    def test_argument_errors_are_tool_errors(self):
        message = request('tools/call', dict(name='fetch_page', arguments={}))
        result = self.exchange(message)[0]
        self.assertNotIn('error', result)
        cases = [{}, {'url': 1}, {'url': 'https://user:pass@example.org/'},
                 {'url': 'file:///tmp/a'}]
        for key, values in dict(format=['pdf', [], None], budget_ms=[0, 180001, True, 1.5],
                                expected_text=[1, '', ' '], allow_browser=[0, 'true'],
                                max_age_hours=[-1, True, '1'], unknown=[1]).items():
            cases.extend(dict(url='https://example.org/', **{key: v}) for v in values)
        for args in cases:
            with self.subTest(args=args):
                message = request('tools/call', dict(name='fetch_page', arguments=args))
                self.assertEqual(self.exchange(message)[0], dict(jsonrpc='2.0', id=1,
                    result=dict(content=[dict(type='text', text='invalid_arguments')],
                                structuredContent=dict(content='invalid_arguments'), isError=True)))
        self.assertTrue(self.exchange(request('tools/call', dict(name='fetch_page')))[0]
                        ['result']['isError'])
        self.open.assert_not_called()

    def test_invalid_call_envelopes_are_rpc_errors_without_http(self):
        cases = [dict(name='fetch_page', arguments=args) for args in ([], None, 'bad', 1, True)]
        cases.extend([[], 'bad', 1, True, dict(name='other', arguments={}), {}])
        for params in cases:
            with self.subTest(params=params):
                result = self.exchange(request('tools/call', params))[0]
                self.assertEqual(result['error']['code'], -32602)
                self.assertEqual(result['id'], 1)
        self.assertEqual(self.exchange(dict(request('tools/call'), params=None))[0]
                         ['error']['code'], -32602)
        self.open.assert_not_called()

    def test_transport_status_and_invalid_responses_are_tool_errors(self):
        failures = [URLError(TOKEN), HTTPError('http://user:pass@host/', 302, TOKEN, {}, None)]
        for exc in failures:
            with self.subTest(exc=type(exc).__name__):
                self.open.side_effect = exc
                result = self.call()
                self.assertIs(result['result']['isError'], True)
                self.assertEqual(result['result']['structuredContent']['content'],
                                 result['result']['content'][0]['text'])
                self.assertNotIn(TOKEN, json.dumps(result))
                self.assertNotIn('user:pass', json.dumps(result))
        for value, status in ((reply(), 201), (reply(), 302), (b'bad ' + TOKEN.encode(), 200),
                              (b'{"ok":true,"ok":false}', 200), (b'{"x":NaN}', 200),
                              ({}, 200), (dict(reply(), content=[]), 200)):
            with self.subTest(status=status, value=value):
                self.stub(value, status)
                result = self.call()['result']
                self.assertIs(result['isError'], True)
                self.assertEqual(result['structuredContent']['content'], result['content'][0]['text'])
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_invalid_configuration_does_not_leak(self):
        for env in ({'ABG_TOKEN': ''}, {'ABG_TOKEN': 'bad\nsecret'},
                    {'ABG_TOKEN_FILE': '/missing-secret'},
                    {'ABG_TOKEN': TOKEN, 'ABG_URL': 'http://user:pass@host/'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                result = self.call()['result']
                self.assertIs(result['isError'], True)
                self.assertEqual(result['structuredContent']['content'], result['content'][0]['text'])
                self.assertNotIn('user:pass', json.dumps(result))
                self.assertNotIn('secret', json.dumps(result))
        self.open.assert_not_called()

    def test_http_error_response_is_closed_without_secret_warning(self):
        error = HTTPError('http://user:pass@host/', 403, TOKEN, {}, io.BytesIO(b'error'))
        self.open.side_effect = error
        try:
            self.assertIs(self.call()['result']['isError'], True)
            self.assertTrue(error.closed)
        finally:
            error.close()

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
            result = self.call()['result']
            self.assertEqual(result['structuredContent']['content'], result['content'][0]['text'])
            wire = json.dumps(result)
            self.assertNotIn(TOKEN, wire)
            self.assertNotIn('user:pass@', wire)

    def test_parse_error_and_recovery(self):
        wire = '\n{\n{"a":1,"a":2}\nNaN\n' + json.dumps(request('tools/list')) + '\n'
        output = self.exchange(raw=wire)
        self.assertEqual([m['error']['code'] for m in output[:3]], [-32700] * 3)
        self.assertTrue(all('id' not in m for m in output[:3]))
        self.assertIn('result', output[3])

    def test_errors_without_id_omit_id(self):
        result = self.exchange(raw='{not json\n')[0]
        self.assertNotIn('id', result)
        self.assertEqual(result['error']['code'], -32700)
        for message in (request('ping', ident=None), request('ping', ident=True),
                        request('ping', ident=1.5), request('ping', ident=[]),
                        dict(jsonrpc='1.0', method='ping', id=7), {}, [], None):
            with self.subTest(message=message):
                result = self.exchange(message)[0]
                self.assertFalse('id' in result)
                self.assertEqual(result['error']['code'], -32600)
        for ident in (0, 'request-1'):
            result = self.exchange(request('missing', ident=ident))[0]
            self.assertEqual(result['id'], ident)
            self.assertEqual(result['error']['code'], -32601)
        self.open.assert_not_called()

    def test_redacts_apostrophe_in_password(self):
        url = "https://user:pa'ss@example.org/x"
        self.assertEqual(mcp_stdio.redact(url, None), '[redacted-url]')
        value = reply()
        value['content'] = url
        value['final_url'] = url
        value['attempts'][0]['extension'] = {url: [url]}
        self.stub(value)
        result = self.call()['result']
        self.assertEqual(result['content'], [dict(type='text', text='[redacted-url]')])
        self.assertEqual(result['structuredContent']['content'], '[redacted-url]')
        self.assertNotIn("pa'ss", json.dumps(result))

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
            request('tools/list', ident=2)) + '\n' + json.dumps(request('ping', ident=3)) + '\n'
        for command in ([sys.executable, '-m', 'gateway.mcp_stdio'], [str(ROOT / 'scripts/abg-mcp')]):
            with self.subTest(command=command):
                proc = subprocess.run(command, input=wire, text=True, capture_output=True,
                                      cwd=ROOT, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stderr, '')
                messages = [json.loads(line) for line in proc.stdout.splitlines()]
                self.assertEqual([m['id'] for m in messages], [1, 2, 3])
                self.assertTrue(all(m['jsonrpc'] == '2.0' for m in messages))
                self.assertEqual(messages[0]['result']['protocolVersion'], '2025-06-18')
                self.assertNotIn('resultType', messages[1]['result'])
                self.assertEqual(messages[2], dict(jsonrpc='2.0', id=3, result={}))


if __name__ == '__main__':
    unittest.main()
