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


def string(value):
    return isinstance(value, str)


def optional(check):
    return lambda v: v is None or check(v)


def member(choices):
    return lambda v: string(v) and v in choices


def fields(value, **rules):
    if not isinstance(value, dict) or any(k not in value or not check(value[k]) for k, check in rules.items()):
        raise ValueError


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
    fields(value, ok=lambda v: type(v) is bool, url=string, final_url=string,
           format=lambda v: v == mode, content=lambda v: True,
           provider=optional(string), age_hours=optional(number), error_type=member(FAILURES),
           step=member(STEPS), elapsed_ms=integer, attempts=lambda v: isinstance(v, list))
    for attempt in value['attempts']:
        fields(attempt, provider=string, egress_profile=string, success=lambda v: type(v) is bool,
               error_type=member(FAILURES), challenge=member(CHALLENGES), elapsed_ms=integer,
               status=optional(lambda v: type(v) is int and 100 <= v <= 599),
               age_hours=optional(number), next_step=optional(member(STEPS)))
    content = value['content']
    if mode in ('text', 'html', 'markdown'):
        if not isinstance(content, str):
            raise ValueError
    elif mode == 'links':
        if not isinstance(content, list):
            raise ValueError
        for link in content:
            fields(link, text=lambda v: string(v) and len(v) <= 100, href=string)
            if set(link) != {'text', 'href'}:
                raise ValueError
            parsed = urlsplit(link['href'])
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                raise ValueError
    elif not isinstance(content, dict):
        raise ValueError
    elif value['ok']:
        fields(content, title=string, h1=lambda v: isinstance(v, list) and all(map(string, v)))
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
