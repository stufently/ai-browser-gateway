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
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlparse, urlunparse
from urllib.request import ProxyHandler, Request, build_opener
from urllib.request import urlopen as _stdlib_urlopen
from xml.etree import ElementTree


PROVIDERS = frozenset(
    {"curl", "curl_cffi", "primp", "playwright", "patchright", "camoufox",
     "pydoll", "scrapling", "wayback", "rss"}
)


class _Deadline:
    """Shared remaining budget; None end keeps historical adapter timeouts."""

    __slots__ = ("end", "clock")

    def __init__(self, start: float, budget_ms: int | None, clock):
        self.clock = clock
        self.end = None if budget_ms is None else start + budget_ms / 1000.0

    def remaining_s(self) -> float:
        left = self.end - self.clock()
        if left <= 0:
            raise TimeoutError("budget exceeded")
        return left


_DEADLINE: _Deadline | None = None


def _bound_timeout_s(default: float) -> float:
    deadline = _DEADLINE
    if deadline is None or deadline.end is None:
        return default
    return min(default, deadline.remaining_s())


def _bound_timeout_ms(default: int) -> int:
    deadline = _DEADLINE
    if deadline is None or deadline.end is None:
        return default
    return max(1, min(default, int(deadline.remaining_s() * 1000)))


_INERT_TAGS = frozenset({"script", "style", "template"})
_BREAK_TAGS = frozenset({"br", "hr"})
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "body", "caption",
    "dd", "details", "dialog", "div", "dl", "dt", "fieldset", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hgroup", "html", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    "legend", "summary", "menu",
})


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _INERT_TAGS:
            self._skip += 1
        elif self._skip == 0 and tag in _BREAK_TAGS | _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if self._skip and tag in _INERT_TAGS:
            self._skip -= 1
        elif self._skip == 0 and tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data):
        if self._skip == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(body: str) -> str:
    parser = _VisibleText()
    parser.feed(body)
    parser.close()
    return parser.text()


def urlopen(url, timeout=120):
    timeout = _bound_timeout_s(timeout)
    proxy = os.environ.get("ABG_PROXY") or ""
    if proxy:
        return build_opener(ProxyHandler({"http": proxy, "https": proxy})).open(url, timeout=timeout)
    return _stdlib_urlopen(url, timeout=timeout)


def _proxy_url() -> str:
    return os.environ.get("ABG_PROXY") or ""


def playwright_proxy(url: str) -> dict[str, str]:
    """ProxySettings для playwright/patchright/camoufox: креды отдельно от server."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # hostname отдаёт IPv6 без скобок; без них "http://fd00::1:8080" разберётся
    # как хост fd00 с мусором, и прокси молча окажется другим.
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    settings = {
        "server": urlunparse((parsed.scheme, netloc, parsed.path, parsed.params,
                              parsed.query, parsed.fragment)),
    }
    if parsed.username is not None:
        settings["username"] = unquote(parsed.username)
    if parsed.password is not None:
        settings["password"] = unquote(parsed.password)
    return settings


def pydoll_proxy_flag(url: str) -> str:
    """--proxy-server= с кредами внутри: их вырезает и применяет сам pydoll."""
    return "--proxy-server=" + url


# Схема — любая: измерено, что curl печатает URL прокси в stderr и для socks5,
# а пароль от socks-прокси утекает ровно так же, как от http.
_USERINFO_URL = re.compile(r"([a-z][a-z0-9+.\-]*://)([^/@\s'\"]+)@", re.I)


def redact(text: str) -> str:
    """Убирает userinfo из любых URL в тексте: http://u:p@h → http://***@h."""
    return _USERINFO_URL.sub(r"\1***@", text)


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


# A decision must not hang on the FIRST <title> in the file: a commented-out or
# scripted one wins over the real one, and a forum post quoting a block page
# would be read as a block page. _title() itself stays untouched — it feeds the
# output field, and changing it would change the probe's output contract.
_INERT_MARKUP = re.compile(
    r"<!--.*?-->|<script\b.*?</script\s*>|<template\b.*?</template\s*>",
    re.I | re.S,
)


def _decisive_title(body: str) -> str:
    """Title used for RULE decisions: comments, scripts and templates removed."""
    return _title(_INERT_MARKUP.sub(" ", body))


# Where every rule comes from, machine-readable on purpose: "fixture:<name>"
# means the rule was seen in that real body under tests/fixtures/, "assumed"
# means it was never measured. A comment would be deleted without anyone
# noticing; flipping a value here has to be written by hand and shows up in the
# diff. Tests enforce two things: the named fixture exists, and an "assumed"
# rule never decides a verdict on its own.
CF_INTERSTITIAL = "fixture:cf_interstitial_200body_403.html"
ASSUMED = "assumed"
RULE_PROVENANCE = {
    "header_cf_mitigated": "measured:bizprofile.net 403, 2026-09-06",
    "body_cf_challenges_host": CF_INTERSTITIAL,
    "body_cf_chl_opt": CF_INTERSTITIAL,
    "body_cf_chl": CF_INTERSTITIAL,
    "body_cf_challenge_platform": CF_INTERSTITIAL,
    "body_just_a_moment": CF_INTERSTITIAL,
    "body_noindex_nofollow": CF_INTERSTITIAL,
    "body_captcha": ASSUMED,
    "body_captcha_interactive": ASSUMED,
    "status_403": "protocol:HTTP 403",
    "status_429": "protocol:HTTP 429",
}

# Title "just a moment" is enough on its own. The other four needles need two
# distinct body hits (title counts). noindex,nofollow is supporting only: it
# also appears on ordinary pages.
_BODY_RULES = (
    ("body_cf_challenges_host", "challenges.cloudflare.com"),
    ("body_cf_chl_opt", "cf_chl_opt"),
    ("body_cf_chl", "__cf_chl"),
    ("body_cf_challenge_platform", "/cdn-cgi/challenge-platform"),
    ("body_just_a_moment", "just a moment"),
)
_SUPPORTING_BODY_RULES = (
    ("body_noindex_nofollow", "noindex,nofollow"),
)
# No live captcha body has been measured. The attribute rule is kept, but the
# captcha verdict requires an independent challenge signal; the word alone
# is not enough.
_CAPTCHA_ATTR = re.compile(
    r'(?:src|class|id|name)\s*=\s*["\'][^"\']*captcha',
    re.I,
)
_CAPTCHA_WIDGET_CLASSES = frozenset({"g-recaptcha", "h-captcha", "cf-turnstile"})


def _header_value(raw: Any) -> str:
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    return str(raw)


def _normalize_headers(raw: Any) -> dict[str, str] | None:
    if raw is None:
        return None
    items = raw.items() if hasattr(raw, "items") else dict(raw).items()
    folded: dict[str, str] = {}
    for key, value in items:
        folded[str(key).lower()] = _header_value(value)
    return folded


def detect_challenge(status, headers, body) -> tuple[str, tuple[str, ...]]:
    """Return (challenge type, names of rules that fired). Pure: no I/O."""
    text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    lowered = text.lower()

    header_names: list[str] = []
    header_verdict: str | None = None
    if headers is not None:
        folded = {str(key).lower(): value for key, value in headers.items()}
        if "cf-mitigated" in folded:
            value = _header_value(folded["cf-mitigated"]).lower()
            header_names.append("header_cf_mitigated")
            if "interactive" in value:
                header_verdict = "interactive"
            else:
                header_verdict = "suspected"

    body_names: list[str] = []
    for name, needle in _BODY_RULES:
        haystack = _decisive_title(text).lower() if name == "body_just_a_moment" else lowered
        if needle in haystack:
            body_names.append(name)
    if body_names:
        for name, needle in _SUPPORTING_BODY_RULES:
            if needle in lowered:
                body_names.append(name)

    decisive_body = [name for name, _ in _BODY_RULES if name in body_names]
    body_enough = "body_just_a_moment" in body_names or len(decisive_body) >= 2

    # Widget markup is assumed evidence. Parse attributes so prose, comments
    # and script strings do not masquerade as widgets. Invisible v3 scripts
    # (render=<site key>) and grecaptcha.ready/execute calls are not interactive evidence.
    class InteractiveCaptcha(HTMLParser):
        found = False
        template_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag == "template":
                self.template_depth += 1
            if self.template_depth:
                return
            attributes = dict(attrs)
            classes = (attributes.get("class") or "").split()
            if "data-sitekey" in attributes or _CAPTCHA_WIDGET_CLASSES.intersection(classes):
                self.found = True
            if tag == "script":
                src = (attributes.get("src") or "").partition("#")[0]
                path, _, query = src.partition("?")
                render_values = [
                    part.partition("=")[2] for part in query.split("&")
                    if part.startswith("render=")
                ]
                if (path == "recaptcha/api.js" or path.endswith("/recaptcha/api.js")) and (
                    not render_values or "explicit" in render_values
                ):
                    self.found = True

        def handle_endtag(self, tag):
            if tag == "template" and self.template_depth:
                self.template_depth -= 1

    widget = InteractiveCaptcha(convert_charrefs=False)
    try:
        widget.feed(text)
    except Exception:
        # Malformed markup must not discard evidence already recognized.
        pass
    # CF body markers still win: the live interstitial remains suspected.
    captcha_names: list[str] = []
    if _CAPTCHA_ATTR.search(text):
        captcha_names.append("body_captcha")
    if widget.found:
        captcha_names.append("body_captcha_interactive")
    captcha_confirmed = bool(decisive_body or status in (403, 429))

    status_names: list[str] = []
    status_verdict: str | None = None
    if status == 429:
        status_names.append("status_429")
        status_verdict = "rate_limited"
    elif status == 403:
        status_names.append("status_403")
        status_verdict = "access_denied"

    if header_verdict is not None:
        return header_verdict, tuple(header_names + body_names + captcha_names)
    if body_enough:
        return "suspected", tuple(body_names + captcha_names)
    if "body_captcha_interactive" in captcha_names and captcha_confirmed:
        return "captcha", tuple(body_names + captcha_names)
    if status_verdict is not None:
        return status_verdict, tuple(body_names + captcha_names + status_names)
    return "none", tuple(body_names + captcha_names)


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


def parse_wayback(payload: dict) -> tuple[str, str] | None:
    """Return (snapshot URL, UTC timestamp), or None when no closest exists."""
    if not isinstance(payload, dict):
        raise ValueError("Wayback payload must be an object")
    snapshots = payload.get("archived_snapshots", {})
    if not isinstance(snapshots, dict):
        raise ValueError("archived_snapshots must be an object")
    if not snapshots or "closest" not in snapshots:
        return None
    closest = snapshots["closest"]
    if not isinstance(closest, dict) or any(
        not isinstance(closest.get(key), str) or not closest[key]
        for key in ("url", "timestamp")
    ):
        raise ValueError("closest requires a snapshot URL and timestamp")
    return closest["url"], closest["timestamp"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_hours(published: datetime, now: datetime) -> float:
    # A future source date can reflect clock skew; elapsed age cannot be negative.
    return max(0.0, (now - published).total_seconds() / 3600)


# Measured 07.09.2026 on lowendtalk.com/categories/offers/feed.rss: the library
# default "Python-urllib/3.14" is refused with 403, while curl and a browser
# string get 200. An entrance that introduces itself as a script is turned away
# before anything else about it matters.
ENTRANCE_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


def _fetch_entrance(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": ENTRANCE_USER_AGENT})
    try:
        response = urlopen(request, timeout=120)
    except HTTPError as exc:
        # HTTP refusals are measured responses, including their detector evidence.
        response = exc
    with response:
        return _result(response.status, response.geturl(), response.read(), 0,
                       headers=_normalize_headers(response.headers))


class WaybackAdapter:
    version = "stdlib-" + sys.version.split()[0]

    def start(self) -> None:
        self.now = _utcnow()

    def navigate(self, url: str) -> dict[str, Any]:
        discovery = _fetch_entrance("https://archive.org/wayback/available?" + urlencode({"url": url}))
        if discovery["status"] >= 400:
            return discovery
        snapshot = parse_wayback(json.loads(discovery["body"]))
        if snapshot is None:
            missing = _result(discovery["status"], discovery["final_url"], b"", 0)
            missing["err"] = "content_missing"
            return missing
        snapshot_url, timestamp = snapshot
        if not re.fullmatch(r"[0-9]{14}", timestamp):
            raise ValueError("invalid Wayback timestamp")
        published = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        response = _fetch_entrance(snapshot_url)
        response["entrance_age_hours"] = _age_hours(published, self.now)
        return response

    def close(self) -> None:
        pass


class RssAdapter:
    version = "stdlib-" + sys.version.split()[0]

    def start(self) -> None:
        self.now = _utcnow()

    def navigate(self, url: str) -> dict[str, Any]:
        response = _fetch_entrance(url)
        if response["status"] >= 400:
            return response
        root = ElementTree.fromstring(response["body"])
        dates = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "pubDate" or not element.text:
                continue
            try:
                published = parsedate_to_datetime(element.text.strip())
            except (TypeError, ValueError, OverflowError):
                continue
            # An absent timezone does not establish a UTC publication instant.
            if published.tzinfo is not None:
                dates.append(published)
        response["entrance_age_hours"] = _age_hours(max(dates), self.now) if dates else None
        return response

    def close(self) -> None:
        pass


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
        command = [
                "curl", "-L", "--cookie", "", "--silent", "--show-error", "--compressed",
                "--output", "-", "--write-out",
                marker + "%{http_code}\t%{url_effective}\t%{num_redirects}\t%{header_json}",
        ]
        if _DEADLINE is not None and _DEADLINE.end is not None:
            command.extend(["--max-time", str(_DEADLINE.remaining_s())])
        command.append(url)
        run_kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        proxy = _proxy_url()
        if proxy:
            env = os.environ.copy()
            env["ALL_PROXY"] = proxy
            run_kwargs["env"] = env
        completed = subprocess.run(command, **run_kwargs)
        raw_body, separator, raw_meta = completed.stdout.rpartition(marker.encode())
        if completed.returncode or not separator:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            if completed.returncode == 28:
                raise TimeoutError(detail or "curl timed out")
            raise RuntimeError(detail or f"curl exited {completed.returncode}")
        status, final_url, redirects, header_json = raw_meta.decode("utf-8", "replace").split("\t", 3)
        header_map = _normalize_headers(json.loads(header_json))
        return _result(int(status), final_url, raw_body, int(redirects), headers=header_map)

    def close(self) -> None:
        pass


class CurlCffiAdapter:
    version = "unknown"

    def start(self) -> None:
        self.version = _version("curl_cffi")

    def navigate(self, url: str) -> dict[str, Any]:
        from curl_cffi import requests

        kwargs = dict(impersonate="chrome", allow_redirects=True, timeout=_bound_timeout_s(120))
        proxy = _proxy_url()
        if proxy:
            kwargs["proxy"] = proxy
        try:
            response = requests.get(url, **kwargs)
        except Exception as exc:
            if any(cls.__name__ == "Timeout" and cls.__module__ == "curl_cffi.requests.exceptions"
                   for cls in type(exc).__mro__):
                raise TimeoutError("curl_cffi request timed out") from exc
            raise
        return _result(
            response.status_code, str(response.url), response.content, len(response.history),
            headers=_normalize_headers(response.headers),
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
        kwargs = dict(impersonate=self.profile)
        proxy = _proxy_url()
        if proxy:
            kwargs["proxy"] = proxy
        self.client = primp.Client(**kwargs)

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.client.get(url)
        body = response.content
        final_url = str(getattr(response, "url", url))
        history = getattr(response, "history", ())
        return _result(
            response.status_code, final_url, body, len(history),
            headers=_normalize_headers(getattr(response, "headers", None)),
        )

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
        proxy = _proxy_url()
        if proxy:
            launch_options["proxy"] = playwright_proxy(proxy)
        self.browser = self.runtime.chromium.launch(**launch_options)
        self.page = self.browser.new_page()

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.page.goto(url, wait_until="load", timeout=_bound_timeout_ms(120_000))
        body = _playwright_body(self.page, getattr(self, "sentinel", ""))
        status = response.status if response is not None else None
        headers = None if response is None else _normalize_headers(response.headers)
        return _result(status, self.page.url, body.encode(), 0, self.page.title(), headers=headers)

    def close(self) -> None:
        if hasattr(self, "browser"):
            self.browser.close()
        if hasattr(self, "runtime"):
            self.runtime.stop()


class PatchrightAdapter(PlaywrightAdapter):
    package = "patchright"


_SCRAPLING_STALE_CF_HEADER_RULES = frozenset({
    "body_cf_challenge_platform", "body_noindex_nofollow",
})
_SCRAPLING_CHALLENGE_STRINGS = frozenset({
    "turnstile", "cf-chl", "cf_chl", "challenge-platform",
    "challenges.cloudflare.com", "cf-challenge", "cf-captcha", "hcaptcha",
    "recaptcha", "g-recaptcha", "h-captcha", "/cdn-cgi/challenge",
})


def _scrapling_only_jsd_platform_paths(body) -> bool:
    """Allow only passive JSD paths after every challenge-platform marker."""
    text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    suffixes = text.lower().split("/cdn-cgi/challenge-platform")[1:]
    return all(suffix.startswith("/scripts/jsd/") for suffix in suffixes)


def _scrapling_has_challenge_strings(body) -> bool:
    """Check for challenge strings outside allowed passive JSD prefixes."""
    text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    remainder = text.lower().replace("/cdn-cgi/challenge-platform/scripts/jsd/", "")
    return any(marker in remainder for marker in _SCRAPLING_CHALLENGE_STRINGS)


class ScraplingAdapter:
    version = "unknown"
    solve_cloudflare = True

    def start(self) -> None:
        from scrapling.fetchers import StealthySession

        self.version = _version("scrapling")
        options: dict[str, Any] = {
            "headless": False,
            "real_chrome": True,
            "solve_cloudflare": self.solve_cloudflare,
            "google_search": False,
            "timeout": _bound_timeout_ms(120_000),
            "retries": 1,
        }
        proxy = _proxy_url()
        if proxy:
            options["proxy"] = playwright_proxy(proxy)
        self.session = StealthySession(**options)
        self.session.__enter__()

    def navigate(self, url: str) -> dict[str, Any]:
        if url == "about:blank":
            return _result(None, url, b"", 0, headers=None)
        fetch_kwargs: dict[str, Any] = {"solve_cloudflare": self.solve_cloudflare}
        if _DEADLINE is not None and _DEADLINE.end is not None:
            fetch_kwargs["timeout"] = _bound_timeout_ms(120_000)
        response = self.session.fetch(url, **fetch_kwargs)
        body = getattr(response, "body", b"")
        if callable(body):
            body = body()
        if not isinstance(body, bytes):
            body = b"" if body is None else str(body).encode("utf-8")
        headers = _normalize_headers(getattr(response, "headers", None))
        history = getattr(response, "history", None) or ()
        status = getattr(response, "status", None)
        if (status is not None and 200 <= status < 300
                and headers is not None and "cf-mitigated" in headers
                and (body_challenge := detect_challenge(status, None, body))[0] == "none"
                and set(body_challenge[1]) <= _SCRAPLING_STALE_CF_HEADER_RULES
                and ("body_cf_challenge_platform" not in body_challenge[1]
                     or _scrapling_only_jsd_platform_paths(body))
                and not _scrapling_has_challenge_strings(body)):
            # Scrapling can retain challenge headers after its solver reaches
            # the real page. Trust the body only for this successful response.
            headers.pop("cf-mitigated")
        final_url = str(getattr(response, "url", url) or url)
        return _result(status, final_url, body, len(history), headers=headers)

    def close(self) -> None:
        if hasattr(self, "session"):
            self.session.__exit__(None, None, None)


class CamoufoxAdapter:
    version = "unknown"

    def start(self) -> None:
        from camoufox.sync_api import Camoufox

        self.version = _version("camoufox")
        options = {"headless": False}
        proxy = _proxy_url()
        if proxy:
            options["proxy"] = playwright_proxy(proxy)
        self.manager = Camoufox(**options)
        self.browser = self.manager.__enter__()
        self.page = self.browser.new_page()

    def navigate(self, url: str) -> dict[str, Any]:
        response = self.page.goto(url, wait_until="load", timeout=_bound_timeout_ms(120_000))
        body = _playwright_body(self.page, getattr(self, "sentinel", ""))
        status = response.status if response is not None else None
        headers = None if response is None else _normalize_headers(response.headers)
        return _result(status, self.page.url, body.encode(), 0, self.page.title(), headers=headers)

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
        # Debian's chromium ships the setuid sandbox helper, which a container
        # without CAP_SYS_ADMIN cannot use: without these flags the browser never
        # starts and every cell fails with FailedToStartBrowser after start_timeout.
        for flag in ("--no-sandbox", "--disable-dev-shm-usage",
                     "--disable-gpu", "--disable-dbus"):
            options.add_argument(flag)
        proxy = _proxy_url()
        if proxy:
            options.add_argument(pydoll_proxy_flag(proxy))
        self.browser = Chrome(options=options)
        self.tab = self.loop.run_until_complete(self.browser.start())

    def navigate(self, url: str) -> dict[str, Any]:
        self.loop.run_until_complete(self.tab.go_to(url, timeout=_bound_timeout_s(120)))
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
        # pydoll navigates via CDP go_to(); there is no response object, so
        # headers are unavailable. None is distinct from {} ("no headers arrived").
        return _result(None, value["url"], body, 0, value["title"], headers=None)

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
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    text = body.decode("utf-8", "replace")
    return {
        "status": status,
        "final_url": final_url,
        "body": text,
        "bytes": len(body),
        "title": _title(text) if title is None else title,
        "redirects": redirects,
        "headers": headers,
    }


def _playwright_body(page: Any, sentinel: str, timeout_ms: int = 5_000) -> str:
    """Collect main and iframe DOM, waiting briefly for asynchronous rendering."""
    timeout_ms = _bound_timeout_ms(timeout_ms)
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
        "scrapling": ScraplingAdapter,
        "camoufox": CamoufoxAdapter,
        "pydoll": PydollAdapter,
        "wayback": WaybackAdapter,
        "rss": RssAdapter,
    }
    if provider not in adapters:
        raise ValueError(f"unknown provider: {provider}")
    return adapters[provider]()


def run_probe(
    provider: str,
    url: str,
    sentinel: str | None = None,
    *,
    mode: str,
    adapter_factory=make_adapter,
    clock=time.perf_counter,
    metrics=_metrics,
    include_content=False,
    budget_ms=None,
    content_only=False,
) -> dict[str, Any]:
    if budget_ms is not None and (type(budget_ms) is not int or budget_ms <= 0):
        raise ValueError("invalid budget")
    include_content = include_content or content_only
    adapter = None
    rss_monitor = _RssMonitor() if metrics is _metrics else None
    if rss_monitor is not None:
        rss_monitor.start()
    start = clock()
    startup_ms = 0
    navigation_start = start
    global _DEADLINE
    previous_deadline = _DEADLINE
    _DEADLINE = _Deadline(start, budget_ms, clock)
    try:
        if not content_only and not sentinel:
            raise ValueError("empty sentinel")
        if content_only:
            sentinel = ""
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
        found = not content_only and sentinel in body
        status = response.get("status")
        headers = response.get("headers")
        challenge, markers = detect_challenge(status, headers, body)
        cpu_ms, peak_rss_mb = metrics()
        if rss_monitor is not None:
            peak_rss_mb = max(peak_rss_mb, rss_monitor.stop())
            rss_monitor = None
        payload = {
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
            "err": response.get("err", ""),
            "entrance_age_hours": response.get("entrance_age_hours"),
            "provider_version": getattr(adapter, "version", "unknown"),
            "redirects": response.get("redirects", 0),
            "headers": headers,
            "challenge_markers": list(markers),
        }
        if include_content:
            html = body if isinstance(body, str) else ""
            payload["html"] = html
            payload["text"] = html_to_text(html)
        return payload
    except Exception as exc:
        finished = clock()
        cpu_ms, peak_rss_mb = metrics()
        if rss_monitor is not None:
            peak_rss_mb = max(peak_rss_mb, rss_monitor.stop())
            rss_monitor = None
        if startup_ms == 0:
            startup_ms = round((finished - start) * 1000)
        name = type(exc).__name__
        if (
            isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
            or name in ("TimeoutError", "TimeoutExpired")
        ):
            err = "timeout"
        else:
            err = redact(f"{name}: {exc}")
            if err.startswith(("TimeoutError:", "TimeoutExpired:")):
                err = "timeout"
        payload = {
            "ok": False, "status": None, "final_url": url, "bytes": 0,
            "sentinel": False, "challenge": "none", "title": "",
            "startup_ms": startup_ms,
            "elapsed_ms": round((finished - navigation_start) * 1000),
            "peak_rss_mb": peak_rss_mb, "cpu_ms": cpu_ms,
            "err": err,
            "provider_version": getattr(adapter, "version", "unknown"),
            "redirects": 0,
            "headers": None,
            "challenge_markers": [],
            "entrance_age_hours": None,
        }
        if include_content:
            payload["html"] = ""
            payload["text"] = ""
        return payload
    finally:
        _DEADLINE = previous_deadline
        if rss_monitor is not None:
            rss_monitor.stop()
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass


def _positive_budget(value: str) -> int:
    if not value.isdigit() or int(value) <= 0:
        raise argparse.ArgumentTypeError("budget-ms must be a positive integer")
    return int(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("sentinel", nargs="?")
    parser.add_argument("--content-only", action="store_true")
    parser.add_argument("--mode", choices=("cold", "warm"), default="cold")
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--budget-ms", type=_positive_budget, default=None)
    args = parser.parse_args(argv)
    if not args.content_only and not args.sentinel:
        parser.error("sentinel is required without --content-only")
    provider = os.environ.get("ABG_PROVIDER", "")
    with contextlib.redirect_stdout(sys.stderr):
        if provider not in PROVIDERS:
            payload = run_probe(
                provider, args.url, args.sentinel, mode=args.mode,
                adapter_factory=make_adapter,
                include_content=args.include_content,
                budget_ms=args.budget_ms,
                content_only=args.content_only,
            )
        else:
            payload = run_probe(
                provider, args.url, args.sentinel, mode=args.mode,
                include_content=args.include_content,
                budget_ms=args.budget_ms,
                content_only=args.content_only,
            )
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
