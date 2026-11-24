"""Чекер M24: пройденная Cloudflare-страница не отвергается детектором.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m24_cf_detector.py      ->  печатает `ok`

Без сети и без браузера: настоящие тела из tests/fixtures/ и поддельные
сессия scrapling и страница patchright. Каждая проверка отказа отделяет
ПРИЧИНУ: заголовок остаётся либо из-за тела, либо из-за отсутствия
cf_clearance, и это два разных случая.
"""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
GITLAB = "cf_passed_gitlab_signin_200.html"
COURSE = "cf_passed_scrapingcourse_200.html"
WIDGET = "cf_jsd_turnstile_widget_200.html"
INTERSTITIALS = ("cf_interstitial_200body_403.html", "cf_managed_interstitial_403.html")
CLEARANCE = ({"name": "cf_clearance", "value": "v", "domain": ".site.invalid"},)
OTHER_COOKIE = ({"name": "session", "value": "v", "domain": ".site.invalid"},)
FOREIGN_CLEARANCE = ({"name": "cf_clearance", "value": "v", "domain": ".other.invalid"},)
SUFFIX_CLEARANCE = ({"name": "cf_clearance", "value": "v", "domain": "ite.invalid"},)
SUBDOMAIN_CLEARANCE = ({"name": "cf_clearance", "value": "v", "domain": "site.invalid"},)
JSD = '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
LOADER = '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async></script>'
ORCHESTRATE = '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=x"></script>'
FAILURES = []


def load_probe():
    path = ROOT / "bench" / "providers" / "docker" / "probe.py"
    spec = importlib.util.spec_from_file_location("m24_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def body(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: ожидалось {expected!r}, получено {actual!r}")


def detector(probe):
    detect = probe.detect_challenge
    for headers in (None, {}):
        check(f"gitlab 200 headers={headers}", detect(200, headers, body(GITLAB))[0], "none")
        check(f"scrapingcourse 200 headers={headers}", detect(200, headers, body(COURSE))[0], "none")
        check(f"nowsecure 200 headers={headers}", detect(200, headers, body(WIDGET)),
              ("none", ("body_captcha_interactive",)))
    check("nowsecure 403", detect(403, {}, body(WIDGET))[0], "captcha")
    for name in INTERSTITIALS:
        for status in (200, 403):
            verdict, markers = detect(status, {}, body(name))
            check(f"{name} {status}", verdict, "suspected")
            for rule in ("body_just_a_moment", "body_cf_chl_opt",
                         "body_cf_challenge_platform", "body_cf_challenges_host"):
                check(f"{name} {status} {rule}", rule in markers, True)
    page = "<html><title>Shop</title><p>Real</p>"
    check("jsd+loader 200", detect(200, {}, page + JSD + LOADER), ("none", ()))
    check("jsd+loader 403", detect(403, {}, page + JSD + LOADER)[0], "access_denied")
    # The passive JSD path and the widget loader are the ONLY exceptions.
    check("orchestrate+cf_chl_opt", detect(200, {}, page + ORCHESTRATE + "cf_chl_opt"),
          ("suspected", ("body_cf_chl_opt", "body_cf_challenge_platform")))
    check("bare host+cf_chl_opt", detect(200, {}, page + "challenges.cloudflare.com; cf_chl_opt"),
          ("suspected", ("body_cf_challenges_host", "body_cf_chl_opt")))
    check("jsd+orchestrate+__cf_chl", detect(200, {}, page + JSD + ORCHESTRATE + "__cf_chl")[0],
          "suspected")
    check("loader+other host path+cf_chl_opt",
          detect(200, {}, page + LOADER + '<iframe src="https://challenges.cloudflare.com/cdn-cgi/x">'
                 + "cf_chl_opt")[0], "suspected")


class FakeRequest:
    def __init__(self, kind):
        self.resource_type = kind

    def is_navigation_request(self):
        return self.resource_type == "document"


class FakeResponse:
    def __init__(self, status, headers, frame, kind="document"):
        self.status = status
        self.headers = dict(headers)
        self.frame = frame
        self.request = FakeRequest(kind)

    def all_headers(self):
        return dict(self.headers)


def scrapling(probe, *, status, first_headers, html, cookies, events, calls_setup=True):
    """Run ScraplingAdapter.navigate against a fake StealthySession."""
    seen = {}

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def fetch(self, url, **kwargs):
            seen["kwargs"] = kwargs
            main, child = object(), object()
            handlers = []
            page = types.SimpleNamespace(main_frame=main, on=lambda name, cb: handlers.append((name, cb)))
            if calls_setup and callable(kwargs.get("page_setup")):
                kwargs["page_setup"](page)
                for code, headers, where, kind in events:
                    response = FakeResponse(code, headers, main if where == "main" else child, kind)
                    for name, callback in handlers:
                        if name == "response":
                            callback(response)
            return types.SimpleNamespace(status=status, url="https://site.invalid/", body=html.encode(),
                                         headers=dict(first_headers), history=(), cookies=cookies)

    fetchers = types.ModuleType("scrapling.fetchers")
    fetchers.StealthySession = Session
    package = types.ModuleType("scrapling")
    package.fetchers = fetchers
    with patch.dict(sys.modules, {"scrapling": package, "scrapling.fetchers": fetchers}):
        adapter = probe.ScraplingAdapter()
        adapter.start()
        try:
            result = adapter.navigate("https://site.invalid/")
        finally:
            adapter.close()
    return result, seen


STALE = {"cf-mitigated": "challenge", "server": "cloudflare"}
CHAIN = [(307, {"location": "/x"}, "main", "document"),
         (403, {"cf-mitigated": "challenge", "server": "cloudflare"}, "main", "document"),
         (200, {"server": "cloudflare", "x-final": "1"}, "main", "document"),
         (200, {"x-frame": "1"}, "child", "document"),
         (200, {"x-asset": "1"}, "main", "script")]


def scrapling_cases(probe):
    detect = probe.detect_challenge
    result, seen = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                             cookies=OTHER_COOKIE, events=CHAIN)
    check("page_setup передан в fetch", callable(seen["kwargs"].get("page_setup")), True)
    check("final document headers", result["headers"], {"server": "cloudflare", "x-final": "1"})
    check("final document verdict", detect(200, result["headers"], result["body"])[0], "none")

    result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(INTERSTITIALS[1]),
                          cookies=CLEARANCE, events=CHAIN)
    check("final headers do not hide an interstitial body",
          detect(200, result["headers"], result["body"])[0], "suspected")

    mismatch = [(403, {"cf-mitigated": "challenge"}, "main", "document")]
    result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                          cookies=OTHER_COOKIE, events=mismatch)
    check("recorded document with another status is not used", result["headers"], STALE)

    for name in (GITLAB, COURSE, WIDGET):
        result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(name),
                              cookies=CLEARANCE, events=(), calls_setup=False)
        check(f"fallback drops stale header: {name}", result["headers"], {"server": "cloudflare"})
    result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                          cookies=OTHER_COOKIE, events=(), calls_setup=False)
    check("fallback keeps header without cf_clearance", result["headers"], STALE)
    for label, cookies in (("other domain", FOREIGN_CLEARANCE), ("bare suffix", SUFFIX_CLEARANCE)):
        result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                              cookies=cookies, events=(), calls_setup=False)
        check(f"fallback keeps header with cf_clearance for {label}", result["headers"], STALE)
    result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                          cookies=SUBDOMAIN_CLEARANCE, events=(), calls_setup=False)
    check("fallback drops header with host-only cf_clearance", result["headers"], {"server": "cloudflare"})
    result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(GITLAB),
                          cookies=None, events=(), calls_setup=False)
    check("fallback keeps header when cookies are missing", result["headers"], STALE)
    for name in INTERSTITIALS:
        result, _ = scrapling(probe, status=200, first_headers=STALE, html=body(name),
                              cookies=CLEARANCE, events=(), calls_setup=False)
        check(f"fallback keeps header on interstitial body: {name}", result["headers"], STALE)
    for code in (403, 302, 500):
        result, _ = scrapling(probe, status=code, first_headers=STALE, html=body(GITLAB),
                              cookies=CLEARANCE, events=(), calls_setup=False)
        check(f"fallback keeps header outside 2xx: {code}", result["headers"], STALE)


class FakeFrame:
    def __init__(self, url, html):
        self.url = url
        self._html = html

    def content(self):
        return self._html


def patchright_body(probe):
    main = FakeFrame("https://site.invalid/", "<p>MAIN</p>")
    widget = FakeFrame("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/x",
                       "<p>WIDGET cf_chl_opt</p>")
    other = FakeFrame("https://ads.invalid/frame", "<p>OTHER</p>")
    page = types.SimpleNamespace(main_frame=main, frames=[main, widget, other],
                                 wait_for_timeout=lambda ms: None)
    text = probe._playwright_body(page, "")
    check("main frame read", "MAIN" in text, True)
    check("ordinary iframe read", "OTHER" in text, True)
    check("turnstile iframe skipped", "WIDGET" in text, False)
    on_cf = FakeFrame("https://challenges.cloudflare.com/", "<p>CFMAIN</p>")
    page = types.SimpleNamespace(main_frame=on_cf, frames=[on_cf], wait_for_timeout=lambda ms: None)
    check("main frame on the challenge host is still read", "CFMAIN" in probe._playwright_body(page, ""),
          True)


def main():
    probe = load_probe()
    for step in (detector, scrapling_cases, patchright_body):
        try:
            step(probe)
        except Exception as exc:  # a crash is a failed check, not a pass
            FAILURES.append(f"{step.__name__}: {type(exc).__name__}: {exc}")
    if FAILURES:
        sys.exit("m24_cf_detector:\n  " + "\n  ".join(FAILURES))
    print("ok")


if __name__ == "__main__":
    main()
