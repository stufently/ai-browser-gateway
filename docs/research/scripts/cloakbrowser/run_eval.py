"""Run the stock bench CLI with CloakBrowser registered in-process only.

  python3 docs/research/scripts/cloakbrowser/run_eval.py run \
      --targets bench/targets/targets.toml \
      --providers curl_cffi patchright scrapling cloakbrowser \
      --pause-s 30 --output cloak.jsonl
  python3 docs/research/scripts/cloakbrowser/run_eval.py report cloak.jsonl \
      --order curl_cffi patchright scrapling cloakbrowser

The registry module is patched before anything imports PROVIDERS by name, so
plan/run/report see the extra provider; bench/ itself is not modified.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from bench.providers import registry  # noqa: E402

_CLOAK = registry.Provider('cloakbrowser', 'abg-cloakbrowser:eval', 3, 'browser', True)
registry.PROVIDERS = registry.PROVIDERS + (_CLOAK,)
registry._BY_NAME[_CLOAK.name] = _CLOAK

from bench.cli import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
