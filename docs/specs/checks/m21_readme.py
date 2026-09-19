"""M21 checker: the public README agrees with the code and leaks nothing internal.

Owned by the coordinator; the executor must not edit it. Run from the repo root:
  python3 docs/specs/checks/m21_readme.py   ->  prints `ok` on success.
"""
import os
import re
import sys

README = open('README.md', encoding='utf-8').read()
ONESHOT = open('gateway/oneshot.py', encoding='utf-8').read()


def need(condition, message):
    if not condition:
        sys.exit(f'FAIL: {message}')


# CLI flags: each documented flag exists in the parser, and every parser flag is documented.
parser_flags = set(re.findall(r"add_argument\('(--[a-z-]+)'", ONESHOT))
need(parser_flags == {'--format', '--expected-text', '--budget-ms', '--no-browser'},
     f'parser flags changed: {sorted(parser_flags)}')
for flag in parser_flags:
    need(flag in README, f'flag {flag} not documented')

for mode in ('text', 'html', 'markdown', 'links', 'meta'):
    need(f'`{mode}`' in README, f'format mode {mode} not documented')

# Exit codes 0-4 appear as rows of a markdown table.
for code in range(5):
    need(re.search(rf'^\|\s*`?{code}`?\s*\|', README, re.M), f'exit code {code} row missing')
for error in ('invalid_request', 'internal_error', 'interrupted'):
    need(error in README, f'stderr error {error} not documented')

for field in ('ok', 'url', 'final_url', 'provider', 'age_hours', 'error_type', 'step',
              'elapsed_ms', 'format', 'content', 'attempts'):
    need(f'`{field}`' in README, f'JSON field {field} not documented')

for snippet in (
        'docker run --rm ghcr.io/stufently/ai-browser-gateway-oneshot:latest https://example.com/ --format markdown',
        '--budget-ms 90000',
        'docker build -f deploy/Dockerfile.oneshot -t ai-browser-gateway-oneshot .',
        '"ABG_TOKEN_FILE"',
        'scripts/abg-mcp',
        '2025-11-25',
        'https://github.com/stufently/ai-browser-gateway/pkgs/container/ai-browser-gateway-oneshot',
):
    need(snippet in README, f'snippet missing: {snippet}')

for provider in ('curl_cffi', 'patchright', 'scrapling'):
    need(f'`{provider}`' in README, f'provider {provider} not documented')

# Relative links resolve to files in the repo.
links = [link.split('#')[0] for link in re.findall(r'\]\(([^)\s]+)\)', README)
         if not link.startswith(('http://', 'https://', '#', 'mailto:'))]
need(links, 'README has no relative links')
missing = [link for link in links if not os.path.exists(link)]
need(not missing, f'broken relative links: {missing}')
need('docs/README.ru.md' in links and 'LICENSE' in links, 'README must link LICENSE and docs/README.ru.md')

# Nothing internal in the new public files.
internal = re.compile(r'\b[\w.-]+\.ru\b|/home/\w|\b\d{1,3}(\.\d{1,3}){3}\b')
for path in ('README.md', 'LICENSE', 'SECURITY.md', 'pyproject.toml'):
    text = open(path, encoding='utf-8').read()
    hit = internal.search(text.replace('127.0.0.1', '').replace('README.ru.md', ''))
    need(hit is None, f'internal detail in {path}: {hit and hit.group(0)}')

print('ok')
