"""Standalone stdlib CLI: one authenticated API request, no product imports."""
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

MODES = ('text', 'html', 'markdown', 'links', 'meta')
FAILURES = set(('none dns_error timeout connection_error tls_error http_403 http_429 http_5xx '
                'javascript_required challenge_suspected interactive_challenge content_missing '
                'content_mismatch provider_error not_measured environment_error').split())
STEPS = set('stop retry_later investigate give_up human browser change_egress'.split())
CHALLENGES = set('none suspected javascript_required interactive captcha rate_limited access_denied'.split())


def valid_url(url):
    if (not isinstance(url, str) or not url or url != url.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in url)):
        raise ValueError
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.port == 0
            or parsed.username is not None or parsed.password is not None):
        raise ValueError


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def integer(value):
    return type(value) is int and value >= 0


def member(value, choices):
    return isinstance(value, str) and value in choices


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def reject(value):
    raise ValueError


def validate_response(value, mode):
    if not isinstance(value, dict):
        raise ValueError
    required = {'ok', 'url', 'final_url', 'format', 'content', 'provider', 'age_hours',
                'error_type', 'step', 'elapsed_ms', 'attempts'}
    if (not required <= value.keys() or type(value['ok']) is not bool or value['format'] != mode
            or not isinstance(value['url'], str) or not isinstance(value['final_url'], str)
            or not (value['provider'] is None or isinstance(value['provider'], str))
            or not (value['age_hours'] is None or number(value['age_hours']))
            or not member(value['error_type'], FAILURES) or not member(value['step'], STEPS)
            or not integer(value['elapsed_ms']) or not isinstance(value['attempts'], list)):
        raise ValueError
    valid_url(value['url'])
    valid_url(value['final_url'])
    for attempt in value['attempts']:
        keys = {'provider', 'egress_profile', 'success', 'error_type', 'challenge', 'status',
                'elapsed_ms', 'age_hours', 'next_step'}
        if (not isinstance(attempt, dict) or not keys <= attempt.keys()
                or not isinstance(attempt['provider'], str) or not isinstance(attempt['egress_profile'], str)
                or type(attempt['success']) is not bool or not member(attempt['error_type'], FAILURES)
                or not member(attempt['challenge'], CHALLENGES)
                or not (attempt['status'] is None or type(attempt['status']) is int and 100 <= attempt['status'] <= 599)
                or not integer(attempt['elapsed_ms'])
                or not (attempt['age_hours'] is None or number(attempt['age_hours']))
                or not (attempt['next_step'] is None or member(attempt['next_step'], STEPS))):
            raise ValueError
    content = value['content']
    if mode in ('text', 'html', 'markdown'):
        if not isinstance(content, str):
            raise ValueError
    elif mode == 'links':
        if not isinstance(content, list):
            raise ValueError
        for link in content:
            if (not isinstance(link, dict) or set(link) != {'text', 'href'}
                    or not isinstance(link['text'], str) or len(link['text']) > 100):
                raise ValueError
            valid_url(link['href'])
    elif not isinstance(content, dict):
        raise ValueError
    elif value['ok']:
        if not {'title', 'h1'} <= content.keys() or not isinstance(content['title'], str):
            raise ValueError
        if not isinstance(content['h1'], list) or any(not isinstance(h, str) for h in content['h1']):
            raise ValueError
        for key, item in content.items():
            if key != 'h1' and (key not in {'title', 'description', 'ogTitle', 'ogImage', 'canonical', 'lang'}
                                or not isinstance(item, str)):
                raise ValueError
    return content


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main(args=None):
    error = 'invalid_configuration'
    try:
        args = sys.argv[1:] if args is None else args
        if len(args) not in (1, 2) or len(args) == 2 and args[1] not in MODES:
            raise ValueError
        url, mode = args[0], args[1] if len(args) == 2 else 'text'
        valid_url(url)
        endpoint = os.environ.get('ABG_URL', 'http://127.0.0.1:8765/v1/fetch')
        valid_url(endpoint)
        budget = int(os.environ.get('ABG_BUDGET_MS', '30000'))
        age = float(os.environ.get('ABG_MAX_AGE_HOURS', '0'))
        allow = os.environ.get('ABG_ALLOW_BROWSER', '1')
        expected = os.environ.get('ABG_EXPECTED_TEXT')
        if not 1 <= budget <= 180000 or not number(age) or allow not in ('0', '1'):
            raise ValueError
        if expected is not None and not expected.strip():
            raise ValueError
        token = os.environ.get('ABG_TOKEN')
        if token is None:
            token = Path(os.environ.get('ABG_TOKEN_FILE', '~/.config/abg/client-token')).expanduser().read_text(
                encoding='ascii').rstrip('\r\n')
        if not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError
        body = json.dumps(dict(url=url, format=mode, budget_ms=budget, max_age_hours=age,
                               allow_browser=allow == '1', expected_text=expected)).encode('utf-8')
        error = 'transport_error'
        req = Request(endpoint, data=body, headers={'Authorization': 'Bearer ' + token,
                                                  'Content-Type': 'application/json'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=budget / 1000 + 5) as response:
            if response.status != 200:
                raise ValueError
            error = 'invalid_response'
            value = json.loads(response.read().decode('utf-8'), object_pairs_hook=unique, parse_constant=reject)
        content = validate_response(value, mode)
        if not value['ok']:
            error = 'fetch_failed'
            raise ValueError
        output = json.dumps(content, ensure_ascii=False) if mode in ('links', 'meta') else content
        # Encode before writing so malformed Unicode cannot leave partial stdout.
        output.encode('utf-8')
        sys.stdout.write(output + '\n')
        return 0
    except Exception:
        print(json.dumps({'error': error}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
