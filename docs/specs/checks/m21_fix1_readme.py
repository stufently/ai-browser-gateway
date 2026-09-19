"""M21-fix1 checker: public README commands work for a stranger, Russian README links resolve.

Owned by the coordinator; the executor must not edit it. Run from the repo root:
  python3 docs/specs/checks/m21_fix1_readme.py   ->  prints `ok` on success.
"""
import os
import re
import sys

PYTHON_IMAGE = ('python:3.14.7-slim-bookworm@sha256:'
                '82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56')
README = open('README.md', encoding='utf-8').read()
RU = open('docs/README.ru.md', encoding='utf-8').read()


def need(condition, message):
    if not condition:
        sys.exit(f'FAIL: {message}')


# Every docker run/build line names a pullable image, never a bare local image ID.
for line in README.splitlines():
    if line.startswith('docker run'):
        need(not re.search(r'\ssha256:[0-9a-f]{64}\s', line), f'bare image digest: {line[:80]}')
tests = [line for line in README.splitlines() if 'python3 -m unittest' in line]
need(len(tests) == 2, f'expected two test commands, found {len(tests)}')
for line in tests:
    need(f' {PYTHON_IMAGE} python3 -m unittest' in line, f'test command not on the public image: {line[:80]}')

# The image is published; the README must not say otherwise.
need('scheduled for publication' not in README, 'stale publication notice')
need('Until it is available' not in README, 'stale publication notice')

# No command in the README points at a real third-party site behind Cloudflare.
for line in README.splitlines():
    if line.startswith('docker run'):
        urls = re.findall(r'https?://[^\s]+', line)
        need(all(u.startswith(('https://example.com/', 'https://cloudflare-protected.example/'))
                 for u in urls), f'real site in a command: {line[:100]}')
need('https://cloudflare-protected.example/' in README, 'placeholder Cloudflare example missing')
need('--budget-ms 90000' in README, 'Cloudflare budget advice missing')

# Relative markdown links in the moved Russian README resolve from docs/.
links = [link.split('#')[0] for link in re.findall(r'\]\(([^)\s]+)\)', RU)
         if not link.startswith(('http://', 'https://', '#', 'mailto:'))]
need(len(links) >= 3, f'Russian README lost its links: {links}')
missing = [link for link in links if not os.path.exists(os.path.join('docs', link))]
need(not missing, f'broken links in docs/README.ru.md: {missing}')

print('ok')
