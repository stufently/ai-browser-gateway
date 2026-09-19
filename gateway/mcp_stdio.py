"""Line-delimited MCP over stdio, backed by the existing gateway HTTP API."""
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from gateway.client import (MODES, NoRedirect, number, reject, unique,
                            valid_url, validate_response)


LATEST_VERSION = '2025-11-25'
SUPPORTED_VERSIONS = (LATEST_VERSION, '2025-06-18')
INPUT_SCHEMA = {
    'type': 'object', 'required': ['url'], 'additionalProperties': False,
    'properties': {
        'url': {'type': 'string', 'format': 'uri'},
        'format': {'type': 'string', 'enum': list(MODES), 'default': 'text'},
        'expected_text': {'type': ['string', 'null'], 'minLength': 1, 'default': None},
        'budget_ms': {'type': 'integer', 'minimum': 1, 'maximum': 180000, 'default': 30000},
        'allow_browser': {'type': 'boolean', 'default': True},
        'max_age_hours': {'type': 'number', 'minimum': 0, 'default': 0.0},
    },
}
# Redact userinfo wherever the API may reflect a URL, including page content.
_CREDENTIAL_URL = re.compile(r'https?://[^\s<>"/]*@[^\s<>"\']*', re.IGNORECASE)


def redact(value, token):
    """Sanitize all API-controlled strings (including extension field names)."""
    if isinstance(value, str):
        value = _CREDENTIAL_URL.sub('[redacted-url]', value)
        return value.replace(token, '[redacted]') if token else value
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    return value


def arguments(value):
    if not isinstance(value, dict) or set(value) - INPUT_SCHEMA['properties'].keys():
        raise ValueError
    body = dict(url=value.get('url'), format=value.get('format', 'text'),
                expected_text=value.get('expected_text'), budget_ms=value.get('budget_ms', 30000),
                allow_browser=value.get('allow_browser', True),
                max_age_hours=value.get('max_age_hours', 0.0))
    valid_url(body['url'])
    expected = body['expected_text']
    if (body['format'] not in MODES or type(body['budget_ms']) is not int
            or not 1 <= body['budget_ms'] <= 180000
            or type(body['allow_browser']) is not bool or not number(body['max_age_hours'])
            or expected is not None and (not isinstance(expected, str) or not expected.strip())):
        raise ValueError
    return body


def fetch_page(body):
    """Use the CLI's transport policy and validators; never expose exceptions."""
    error = 'invalid_configuration'
    try:
        endpoint = os.environ.get('ABG_URL', 'http://127.0.0.1:8765/v1/fetch')
        valid_url(endpoint)
        token = os.environ.get('ABG_TOKEN')
        if token is None:
            token = Path(os.environ.get('ABG_TOKEN_FILE', '~/.config/abg/client-token')).expanduser().read_text(
                encoding='ascii').rstrip('\r\n')
        if not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError
        payload = json.dumps(body).encode('utf-8')
        error = 'transport_error'
        req = Request(endpoint, data=payload, headers={'Authorization': 'Bearer ' + token,
                                                     'Content-Type': 'application/json'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(
                req, timeout=body['budget_ms'] / 1000 + 5) as response:
            if response.status != 200:
                raise ValueError
            error = 'invalid_response'
            value = json.loads(response.read().decode('utf-8'), object_pairs_hook=unique,
                               parse_constant=reject)
        content = validate_response(value, body['format'])
        content = redact(content, token)
        text = (json.dumps(content, ensure_ascii=False)
                if body['format'] in ('links', 'meta') else content)
        if not value['ok']:
            text = 'fetch_failed: ' + value['error_type'] + '; step: ' + value['step']
        result = dict(content=[dict(type='text', text=text)],
                      structuredContent={key: value[key] for key in (
                          'ok', 'provider', 'step', 'error_type', 'elapsed_ms', 'final_url', 'attempts')})
        result['structuredContent']['content'] = text
        if not value['ok']:
            result['isError'] = True
        result = redact(result, token)
        # Extension fields in attempts are not covered by the CLI's validator.
        # Reject non-finite JSON numbers here, while failures are still tool errors.
        json.dumps(result, allow_nan=False)
        return result
    except Exception as exc:
        # urllib raises before entering the response context manager on HTTP
        # failures. Close it explicitly: finalizer warnings can contain its URL.
        if isinstance(exc, HTTPError):
            exc.close()
        return dict(content=[dict(type='text', text=error)],
                    structuredContent=dict(content=error), isError=True)


class Server:
    def __init__(self):
        self.version = LATEST_VERSION

    def dispatch(self, method, params):
        if not isinstance(params, dict):
            raise ValueError
        if method == 'initialize':
            requested = params.get('protocolVersion')
            if not isinstance(requested, str):
                raise ValueError
            self.version = requested if requested in SUPPORTED_VERSIONS else LATEST_VERSION
            with (Path(__file__).resolve().parents[1] / 'pyproject.toml').open('rb') as handle:
                version = tomllib.load(handle)['project']['version']
            return dict(protocolVersion=self.version, capabilities=dict(tools=dict(listChanged=False)),
                        serverInfo=dict(name='ai-browser-gateway', version=version))
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return dict(tools=[dict(name='fetch_page',
                                   description='Fetch a page through the gateway provider ladder.',
                                   inputSchema=INPUT_SCHEMA)])
        if method == 'tools/call':
            if params.get('name') != 'fetch_page':
                raise ValueError
            value = params.get('arguments', {})
            if not isinstance(value, dict):
                raise ValueError
            try:
                body = arguments(value)
            except (ValueError, TypeError, OverflowError):
                return dict(content=[dict(type='text', text='invalid_arguments')],
                            structuredContent=dict(content='invalid_arguments'), isError=True)
            return fetch_page(body)
        raise LookupError

    def handle(self, message):
        if (not isinstance(message, dict) or message.get('jsonrpc') != '2.0'
                or not isinstance(message.get('method'), str)
                or 'id' in message and type(message['id']) not in (str, int)):
            return rpc_error(None, -32600, 'Invalid Request')
        # Notifications have neither a reply nor an HTTP side effect.
        if 'id' not in message:
            return None
        ident = message['id']
        try:
            result = self.dispatch(message['method'], message.get('params', {}))
            return dict(jsonrpc='2.0', id=ident, result=result)
        except (ValueError, TypeError, OverflowError):
            return rpc_error(ident, -32602, 'Invalid params')
        except LookupError:
            return rpc_error(ident, -32601, 'Method not found')
        except Exception:
            return rpc_error(ident, -32603, 'Internal error')


def rpc_error(ident, code, message):
    result = dict(jsonrpc='2.0', error=dict(code=code, message=message))
    if ident is not None:
        result['id'] = ident
    return result


def serve(stdin, stdout, *, on_output_error=None):
    server = Server()
    pending, failures = queue.Queue(), queue.Queue()
    output_lock = threading.Lock()
    workers = []

    def emit(result):
        if result is not None:
            # ASCII escaping handles malformed Unicode without partial output.
            line = json.dumps(result, allow_nan=False) + '\n'
            with output_lock:
                stdout.write(line)
                stdout.flush()

    def work():
        for message in iter(pending.get, None):
            try:
                emit(server.handle(message))
            except Exception as exc:
                # The CLI must exit even while stdin is blocked. In-process
                # callers can omit the handler and receive the error on EOF.
                if on_output_error is not None:
                    on_output_error()
                failures.put(exc)

    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line, object_pairs_hook=unique, parse_constant=reject)
            except (ValueError, RecursionError):
                emit(rpc_error(None, -32700, 'Parse error'))
                continue
            if isinstance(message, dict) and message.get('method') == 'tools/call':
                if not workers:
                    for _ in range(8):
                        worker = threading.Thread(target=work)
                        worker.start()
                        workers.append(worker)
                # An unbounded queue keeps stdin responsive when all eight
                # workers are busy; only the workers execute tool calls.
                pending.put(message)
            else:
                emit(server.handle(message))
    finally:
        # FIFO sentinels drain both active and waiting calls before EOF exits.
        for _ in workers:
            pending.put(None)
        for worker in workers:
            worker.join()
    if not failures.empty():
        raise failures.get_nowait()


def main():
    failure_lock = threading.Lock()

    def output_failed():
        # Only one worker reports the failure. Skip shutdown joins and stdout
        # flushing: pending calls cannot deliver their responses anymore.
        with failure_lock:
            try:
                print('MCP stdio error', file=sys.stderr, flush=True)
            finally:
                os._exit(1)

    try:
        serve(sys.stdin, sys.stdout, on_output_error=output_failed)
    except (OSError, UnicodeError):
        print('MCP stdio error', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
