#!/usr/bin/env python3
"""Normalize one provider fetch into the M2 one-line JSON contract.

Only Python's standard library is imported at module load time. Provider
packages are imported lazily by their adapters inside the corresponding image.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import html as html_module
import json
import os
import re
import resource
import subprocess
import sys
import threading
import time
from typing import Any


PROVIDERS = frozenset(
    {"curl", "curl_cffi", "primp", "playwright", "patchright", "camoufox", "pydoll"}
)


def _live_rss_kb() -> int:
    total = 0
    try:
        entries = os.scandir("/proc")
    except OSError:
        return 0
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                with open(f"/proc/{entry.name}/status", encoding="ascii") as stream:
                    for line in stream:
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1])
                            break
            except (OSError, ValueError):
                pass
    return total


class _RssMonitor:
    def __init__(self) -> None:
        self.peak_kb = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak_kb = max(self.peak_kb, _live_rss_kb())
            self._stop.wait(0.01)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        self._thread.join()
        self.peak_kb = max(self.peak_kb, _live_rss_kb())
        return round(self.peak_kb / 1024, 3)


def _version(package: str) -> str:
    try:
        from importlib.metadata import version

        return version(package)
    except Exception:
        return "unknown"


def _title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title\s*>", body, re.I | re.S)
    if not match:
        return ""
    return html_module.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _challenge(body: str, status: int | None) -> str:
    lowered = body.lower()
    if status == 429:
        return "rate_limited"
    if "captcha" in lowered:
        return "captcha"
    if "cf-chl-" in lowered or "just a moment" in lowered:
        return "suspected"
    if status == 403 or "access denied" in lowered:
        return "access_denied"
    return "none"


def _metrics() -> tuple[int, float]:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = round(
        (own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime) * 1000
    )
    # A fresh container's cgroup CPU counter includes running browser and Xvfb
    # descendants, which RUSAGE_CHILDREN does not expose until they are reaped.
    try:
        with open("/sys/fs/cgroup/cpu.stat", encoding="ascii") as stream:
            for line in stream:
                key, _, value = line.partition(" ")
                if key == "usage_usec":
                    cpu_ms = round(int(value) / 1000)
                    break
    except (OSError, ValueError):
        pass
    # memory.peak includes page cache, so it is not RSS. Sum live process RSS
    # from /proc and retain ru_maxrss for the probe itself and reaped children.
    live_rss_kb = _live_rss_kb()
    peak_mb = max(live_rss_kb, own.ru_maxrss, children.ru_maxrss) / 1024
    return cpu_ms, round(peak_mb, 3)


class CurlAdapter:
    version = "unknown"

    def start(self) -> None:
        completed = subprocess.run(
            ["curl", "--version"], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False,
        )
        if completed.stdout:
            self.version = completed.stdout.split()[1]

    def navigate(self, url: str) -> dict[str, Any]:
        marker = "\nABG_CURL_META:"
        completed = subprocess.run(
            [
                "curl", "-L", "--cookie", "", "--silent", "--show-error", "--compressed",
                "--output", "-", "--write-out",
                marker + "%{http_code}\t%{url_effective}\t%{num_redirects}", url,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        raw_body, separator, raw_meta = completed.stdout.rpartition(marker.encode())
        if completed.returncode or not separator:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(detail or f"curl exited {completed.returncode}")
        status, final_url, redirects = raw_meta.decode("utf-8", "replace").split("\t")
        return _result(int(status), final_url, raw_body, int(redirects))

    def close(self) -> None:
        pass


class CurlCffiAdapter:
    version = "unknown"

    def start(self) -> None:
        self.version = _version("curl_cffi")

    def navigate(self, url: str) -> dict[str, Any]:
        from curl_cffi import requests

        response = requests.get(url, impersonate="chrome", allow_redirects=True, timeout=120)
        return _result(
            response.status_code, str(response.url), response.content, len(response.history)
        )

    def close(self) -> None:
        pass


class PrimpAdapter:
    version = "unknown"
    profile = "chrome"

    def start(self) -> None:
        if self.profile != "chrome":
            raise ValueError(f"unsupported primp profile: {self.profile}")
        import primp

        self.version = _version("primp")
        self.client = primp.Client(impersonate=self.profile)

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.client.get(url)
        body = response.content
        final_url = str(getattr(response, "url", url))
        history = getattr(response, "history", ())
        return _result(response.status_code, final_url, body, len(history))

    def close(self) -> None:
        pass


class PlaywrightAdapter:
    package = "playwright"

    def start(self) -> None:
        if self.package == "playwright":
            from playwright.sync_api import sync_playwright
        else:
            from patchright.sync_api import sync_playwright
        self.version = _version(self.package)
        self.runtime = sync_playwright().start()
        launch_options = {"headless": self.package == "playwright"}
        if self.package == "patchright":
            launch_options["channel"] = "chrome"
        self.browser = self.runtime.chromium.launch(**launch_options)
        self.page = self.browser.new_page()

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.page.goto(url, wait_until="load", timeout=120_000)
        body = _playwright_body(self.page, getattr(self, "sentinel", ""))
        status = response.status if response is not None else None
        return _result(status, self.page.url, body.encode(), 0, self.page.title())

    def close(self) -> None:
        if hasattr(self, "browser"):
            self.browser.close()
        if hasattr(self, "runtime"):
            self.runtime.stop()


class PatchrightAdapter(PlaywrightAdapter):
    package = "patchright"


class CamoufoxAdapter:
    version = "unknown"

    def start(self) -> None:
        from camoufox.sync_api import Camoufox

        self.version = _version("camoufox")
        self.manager = Camoufox(headless=False)
        self.browser = self.manager.__enter__()
        self.page = self.browser.new_page()

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.page.goto(url, wait_until="load", timeout=120_000)
        body = _playwright_body(self.page, getattr(self, "sentinel", ""))
        status = response.status if response is not None else None
        return _result(status, self.page.url, body.encode(), 0, self.page.title())

    def close(self) -> None:
        if hasattr(self, "manager"):
            self.manager.__exit__(None, None, None)


def _cdp_value(envelope: dict[str, Any]) -> Any:
    return envelope["result"]["result"]["value"]


class PydollAdapter:
    version = "unknown"

    def start(self) -> None:
        from pydoll.browser.chromium import Chrome
        from pydoll.browser.options import ChromiumOptions

        self.version = _version("pydoll-python")
        self.loop = asyncio.new_event_loop()
        options = ChromiumOptions()
        options.binary_location = "/usr/bin/chromium"
        options.headless = True
        options.start_timeout = 60
        self.browser = Chrome(options=options)
        self.tab = self.loop.run_until_complete(self.browser.start())

    def navigate(self, url: str) -> dict[str, Any]:
        self.loop.run_until_complete(self.tab.go_to(url, timeout=120))
        script = """(() => {
          const docs = [document];
          for (const frame of Array.from(window.frames)) {
            try { docs.push(frame.document); } catch (_) {}
          }
          return {html: docs.map(d => d.documentElement.outerHTML).join('\\n'),
                  title: document.title, url: location.href};
        })()"""

        async def snapshot():
            deadline = time.monotonic() + 5
            while True:
                current = await self.tab.execute_script(script, return_by_value=True)
                value = _cdp_value(current)
                if (
                    not getattr(self, "sentinel", "")
                    or self.sentinel in value["html"]
                    or time.monotonic() >= deadline
                ):
                    return current
                await asyncio.sleep(0.05)

        envelope = self.loop.run_until_complete(snapshot())
        value = _cdp_value(envelope)
        body = value["html"].encode()
        return _result(None, value["url"], body, 0, value["title"])

    def close(self) -> None:
        if hasattr(self, "browser"):
            self.loop.run_until_complete(self.browser.stop())
        if hasattr(self, "loop"):
            self.loop.close()


def _result(
    status: int | None,
    final_url: str,
    body: bytes,
    redirects: int,
    title: str | None = None,
) -> dict[str, Any]:
    text = body.decode("utf-8", "replace")
    return {
        "status": status,
        "final_url": final_url,
        "body": text,
        "bytes": len(body),
        "title": _title(text) if title is None else title,
        "redirects": redirects,
    }


def _playwright_body(page: Any, sentinel: str, timeout_ms: int = 5_000) -> str:
    """Collect main and iframe DOM, waiting briefly for asynchronous rendering."""
    deadline = time.monotonic() + timeout_ms / 1000
    body = ""
    while True:
        parts = []
        for frame in page.frames:
            try:
                parts.append(frame.content())
            except Exception:
                continue
        body = "\n".join(parts)
        if not sentinel or sentinel in body or time.monotonic() >= deadline:
            return body
        page.wait_for_timeout(50)


def make_adapter(provider: str):
    adapters = {
        "curl": CurlAdapter,
        "curl_cffi": CurlCffiAdapter,
        "primp": PrimpAdapter,
        "playwright": PlaywrightAdapter,
        "patchright": PatchrightAdapter,
        "camoufox": CamoufoxAdapter,
        "pydoll": PydollAdapter,
    }
    if provider not in adapters:
        raise ValueError(f"unknown provider: {provider}")
    return adapters[provider]()


def run_probe(
    provider: str,
    url: str,
    sentinel: str,
    *,
    mode: str,
    adapter_factory=make_adapter,
    clock=time.perf_counter,
    metrics=_metrics,
) -> dict[str, Any]:
    adapter = None
    rss_monitor = _RssMonitor() if metrics is _metrics else None
    if rss_monitor is not None:
        rss_monitor.start()
    start = clock()
    startup_ms = 0
    navigation_start = start
    try:
        if not sentinel:
            raise ValueError("empty sentinel")
        adapter = adapter_factory(provider)
        adapter.sentinel = sentinel
        adapter.start()
        started = clock()
        startup_ms = round((started - start) * 1000)
        if mode == "warm":
            adapter.sentinel = ""
            adapter.navigate("about:blank")
            adapter.sentinel = sentinel
            navigation_start = clock()
        response = adapter.navigate(url)
        finished = clock()
        elapsed_ms = round((finished - navigation_start) * 1000)
        body = response.get("body", "")
        found = sentinel in body
        status = response.get("status")
        challenge = _challenge(body, status)
        cpu_ms, peak_rss_mb = metrics()
        if rss_monitor is not None:
            peak_rss_mb = max(peak_rss_mb, rss_monitor.stop())
            rss_monitor = None
        return {
            "ok": found and (status is None or status < 400),
            "status": status,
            "final_url": response.get("final_url", url),
            "bytes": response.get("bytes", len(body.encode("utf-8"))),
            "sentinel": found,
            "challenge": challenge,
            "title": response.get("title", _title(body)),
            "startup_ms": startup_ms,
            "elapsed_ms": elapsed_ms,
            "peak_rss_mb": peak_rss_mb,
            "cpu_ms": cpu_ms,
            "err": "",
            "provider_version": getattr(adapter, "version", "unknown"),
            "redirects": response.get("redirects", 0),
        }
    except Exception as exc:
        finished = clock()
        cpu_ms, peak_rss_mb = metrics()
        if rss_monitor is not None:
            peak_rss_mb = max(peak_rss_mb, rss_monitor.stop())
            rss_monitor = None
        if startup_ms == 0:
            startup_ms = round((finished - start) * 1000)
        return {
            "ok": False, "status": None, "final_url": url, "bytes": 0,
            "sentinel": False, "challenge": "none", "title": "",
            "startup_ms": startup_ms,
            "elapsed_ms": round((finished - navigation_start) * 1000),
            "peak_rss_mb": peak_rss_mb, "cpu_ms": cpu_ms,
            "err": f"{type(exc).__name__}: {exc}",
            "provider_version": getattr(adapter, "version", "unknown"),
            "redirects": 0,
        }
    finally:
        if rss_monitor is not None:
            rss_monitor.stop()
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("sentinel")
    parser.add_argument("--mode", choices=("cold", "warm"), default="cold")
    args = parser.parse_args(argv)
    provider = os.environ.get("ABG_PROVIDER", "")
    with contextlib.redirect_stdout(sys.stderr):
        if provider not in PROVIDERS:
            payload = run_probe(
                provider, args.url, args.sentinel, mode=args.mode,
                adapter_factory=make_adapter,
            )
        else:
            payload = run_probe(provider, args.url, args.sentinel, mode=args.mode)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
