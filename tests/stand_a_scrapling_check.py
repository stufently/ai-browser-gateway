#!/usr/bin/env python3
"""AC-802: scrapling probe against local stand A, no external network."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "abg-scrapling:m8"
SCENARIOS = (
    ("static", "/static", "ABG_TEST_STATIC_OK"),
    ("js", "/js", "ABG_TEST_JS_OK"),
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_http(url: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"stand A did not start: {last}")


def _last_json(stdout: str) -> dict:
    candidates = [line for line in stdout.splitlines() if line.startswith("{")]
    if not candidates:
        raise ValueError(f"no JSON in probe output: {stdout[:200]!r}")
    payload = json.loads(candidates[-1])
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def main() -> int:
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    server = subprocess.Popen(
        [sys.executable, "-m", "bench.server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/static")
        ok = True
        for name, path, sentinel in SCENARIOS:
            url = f"http://127.0.0.1:{port}{path}"
            completed = subprocess.run(
                [
                    "docker", "run", "--rm", "--user", "1002:1002",
                    "--shm-size=1g", "--network", "host",
                    IMAGE, url, sentinel,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            payload = _last_json(completed.stdout)
            payload["_scenario"] = name
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            if completed.returncode != 0 or not payload.get("ok"):
                ok = False
        return 0 if ok else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
