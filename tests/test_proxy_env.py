"""Regression tests for proxy credentials at the probe's process boundaries."""

import io
import os
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tests.test_probe import load_probe


PROXY = "http://user1:s3cr%40t@proxy.invalid:8080"
TARGET = "https://target.invalid/"
CURL_RESPONSE = subprocess.CompletedProcess(
    [], 0, stdout=b"body\nABG_CURL_META:200\thttps://target.invalid/\t0\t{}", stderr=b"",
)


class ProxyEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.probe = load_probe()

    def run_main(self, run_probe):
        with patch.object(self.probe, "run_probe", side_effect=run_probe), redirect_stdout(io.StringIO()):
            self.assertEqual(self.probe.main([TARGET, "marker"]), 0)

    def test_main_removes_proxy_and_keeps_it_for_redaction(self):
        def run_probe(*args, **kwargs):
            self.assertNotIn("ABG_PROXY", os.environ)
            self.assertEqual(self.probe._proxy_url(), PROXY)
            self.assertEqual(
                self.probe.redact(f"raw=s3cr%40t decoded=s3cr@t url={PROXY}"),
                "raw=*** decoded=*** url=http://***@proxy.invalid:8080",
            )
            return {}

        with patch.dict(os.environ, {"ABG_PROXY": PROXY}):
            self.run_main(run_probe)

    def test_main_removes_proxy_before_argument_validation(self):
        with patch.dict(os.environ, {"ABG_PROXY": PROXY}), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.probe.main([])
            self.assertEqual(error.exception.code, 2)
            self.assertNotIn("ABG_PROXY", os.environ)

    def test_first_child_does_not_inherit_proxy(self):
        def run_child(*args, env=None, **kwargs):
            self.assertNotIn("ABG_PROXY", os.environ if env is None else env)

        def run_probe(*args, **kwargs):
            self.probe.subprocess.run(["child"])
            return {}

        with patch.dict(os.environ, {"ABG_PROXY": PROXY}), patch.object(
            self.probe.subprocess, "run", side_effect=run_child
        ) as child:
            self.run_main(run_probe)
        child.assert_called_once()

    def test_main_captures_empty_proxy_as_unconfigured(self):
        def run_probe(*args, **kwargs):
            self.assertNotIn("ABG_PROXY", os.environ)
            os.environ["ABG_PROXY"] = PROXY
            self.assertEqual(self.probe._proxy_url(), "")
            return {}

        with patch.dict(os.environ, {"ABG_PROXY": ""}):
            self.run_main(run_probe)

    def test_main_captures_missing_proxy_as_unconfigured(self):
        def run_probe(*args, **kwargs):
            os.environ["ABG_PROXY"] = PROXY
            self.assertEqual(self.probe._proxy_url(), "")
            return {}

        with patch.dict(os.environ, clear=True):
            self.run_main(run_probe)

    def test_urlopen_uses_the_same_proxy_before_and_after_main(self):
        def run_probe(*args, **kwargs):
            os.environ["ABG_PROXY"] = "http://other.invalid:8080"
            self.probe.urlopen(TARGET)
            return {}

        with patch.dict(os.environ, {"ABG_PROXY": PROXY}), patch.object(
            self.probe, "build_opener"
        ) as build_opener:
            self.probe.urlopen(TARGET)
            self.run_main(run_probe)

        self.assertEqual(build_opener.call_count, 2)
        for (handler,), _ in build_opener.call_args_list:
            self.assertIsInstance(handler, self.probe.ProxyHandler)
            self.assertEqual(handler.proxies, {"http": PROXY, "https": PROXY})

    def test_curl_passes_escaped_proxy_on_stdin_and_filters_environment(self):
        password = r's3"cr\t'
        proxy = f"http://user1:{password}@proxy.invalid:8080"
        env = {
            "ABG_PROXY": proxy, "ALL_PROXY": proxy, "https_proxy": proxy, "Http_Proxy": proxy,
            "fTp_PrOxY": proxy, "ftps_proxy": proxy, "ws_proxy": proxy,
            "Abg_Egress_Proxy": proxy, "No_Proxy": "other.invalid",
            "FEATURE_PROXY": "enabled", "PATH": "/bin",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(
            self.probe.subprocess, "run", return_value=CURL_RESPONSE
        ) as run:
            self.probe.CurlAdapter().navigate(TARGET)
            self.assertEqual(dict(os.environ), env)

        command = run.call_args.args[0]
        self.assertIn("--config", command)
        index = command.index("--config")
        self.assertEqual(command[index + 1], "-")
        for arg in command:
            self.assertNotIn(proxy, arg)
            self.assertNotIn(password, arg)
        expected = br'proxy = "http://user1:s3\"cr\\t@proxy.invalid:8080"' + b"\n"
        self.assertEqual(run.call_args.kwargs["input"], expected)
        self.assertEqual(
            run.call_args.kwargs["env"],
            {"No_Proxy": "other.invalid", "PATH": "/bin"},
        )

    def test_curl_escapes_line_breaks_in_proxy_config(self):
        proxy = "http://user1:part1\rpart2\npart3@proxy.invalid:8080"
        with patch.dict(os.environ, {"ABG_PROXY": proxy}), patch.object(
            self.probe.subprocess, "run", return_value=CURL_RESPONSE
        ) as run:
            self.probe.CurlAdapter().navigate(TARGET)

        config = run.call_args.kwargs.get("input")
        expected = br'proxy = "http://user1:part1\rpart2\npart3@proxy.invalid:8080"' + b"\n"
        self.assertEqual(config, expected)
        self.assertEqual(config.count(b"\n"), 1)

    def test_curl_without_proxy_keeps_bypass_without_stdin_config(self):
        env = {"ABG_PROXY": "", "https_proxy": PROXY, "NO_PROXY": "target.invalid"}
        with patch.dict(os.environ, env, clear=True), patch.object(
            self.probe.subprocess, "run", return_value=CURL_RESPONSE
        ) as run:
            self.probe.CurlAdapter().navigate(TARGET)
            self.assertNotIn("--config", run.call_args.args[0])
            self.assertNotIn("input", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs.get("env", os.environ), {"NO_PROXY": "target.invalid"})

    def test_curl_version_child_keeps_bypass_and_filters_proxy_environment(self):
        env = {"ABG_PROXY": PROXY, "hTtPs_PrOxY": PROXY, "no_proxy": "target.invalid", "PATH": "/bin"}
        completed = subprocess.CompletedProcess([], 0, stdout="curl 7.88.1\n")
        with patch.dict(os.environ, env, clear=True), patch.object(
            self.probe.subprocess, "run", return_value=completed
        ) as run:
            self.probe.CurlAdapter().start()
            self.assertEqual(
                run.call_args.kwargs.get("env", os.environ), {"no_proxy": "target.invalid", "PATH": "/bin"}
            )
