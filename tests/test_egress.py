"""Proxy profiles stay out of git; missing or empty is not_measured."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from bench.egress import load_profiles, profile_url

PROXY_URL = "http://user:pass@proxy.invalid:8080"


def _write_profiles(directory: Path, body: str, mode: int = 0o600) -> Path:
    path = directory / "proxies.toml"
    path.write_text(body, encoding="utf-8")
    os.chmod(path, mode)
    return path


class LoadProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_file_is_empty_dict_not_an_error(self):
        self.assertEqual(load_profiles(self.root / "missing.toml"), {})

    def test_missing_profile_and_empty_url_are_none(self):
        path = _write_profiles(
            self.root,
            "[profile.gold]\nurl = \"\"\nnote = \"empty\"\n",
        )
        profiles = load_profiles(path)
        self.assertEqual(profiles.get("gold"), "")
        self.assertIsNone(profile_url(profiles, "gold"))
        self.assertIsNone(profile_url(profiles, "absent"))
        self.assertIsNone(profile_url({}, "gold"))

    def test_named_profile_url_is_returned(self):
        path = _write_profiles(
            self.root,
            "[profile.gold]\n"
            f'url = "{PROXY_URL}"\n'
            'note = "GoldProxy, residential"\n'
            "[profile.direct]\n"
            'url = ""\n',
        )
        profiles = load_profiles(path)
        self.assertEqual(profile_url(profiles, "gold"), PROXY_URL)
        self.assertIsNone(profile_url(profiles, "direct"))

    def test_permissions_wider_than_0600_are_refused(self):
        path = _write_profiles(
            self.root,
            f'[profile.gold]\nurl = "{PROXY_URL}"\n',
            mode=0o644,
        )
        with self.assertRaises((PermissionError, ValueError)) as ctx:
            load_profiles(path)
        message = str(ctx.exception)
        self.assertNotIn("pass", message)
        self.assertNotIn(PROXY_URL, message)
        self.assertNotIn("user:pass", message)

    def test_permissions_0600_are_accepted(self):
        path = _write_profiles(
            self.root,
            f'[profile.gold]\nurl = "{PROXY_URL}"\n',
            mode=0o600,
        )
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(load_profiles(path)["gold"], PROXY_URL)

    def test_group_readable_0604_is_refused(self):
        path = _write_profiles(
            self.root,
            f'[profile.gold]\nurl = "{PROXY_URL}"\n',
            mode=0o604,
        )
        with self.assertRaises((PermissionError, ValueError)):
            load_profiles(path)

    def test_invalid_toml_error_does_not_include_url(self):
        path = _write_profiles(self.root, f'url = "{PROXY_URL}"\n[broken', mode=0o600)
        with self.assertRaises(ValueError) as ctx:
            load_profiles(path)
        self.assertNotIn("pass", str(ctx.exception))
        self.assertNotIn(PROXY_URL, str(ctx.exception))

    def test_no_function_puts_url_in_an_exception(self):
        path = _write_profiles(
            self.root,
            f'[profile.gold]\nurl = "{PROXY_URL}"\n',
            mode=0o666,
        )
        with self.assertRaises(Exception) as ctx:
            load_profiles(path)
        self.assertNotIn("pass", str(ctx.exception))
        self.assertNotIn("@", str(ctx.exception))
