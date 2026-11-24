"""Чекер M25: ступень patchright кликает по чекбоксу Turnstile на CF-заглушке.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m25_turnstile_click.py      ->  печатает `ok`

Без сети и без браузера: PatchrightAdapter.navigate идёт по поддельной
странице, которая ведёт себя как замеренная заглушка Cloudflare (403,
«Just a moment...», контейнер input[name="cf-turnstile-response"]). Время
настоящее: пауза между кликами и потолок ожидания меряются часами. Каждый
отказ отделяет причину: без cf_clearance, без клика, не та ступень, не та
заглушка.
"""
import importlib.util
import os
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
INTERSTITIAL = (FIXTURES / "cf_managed_interstitial_403.html").read_text(encoding="utf-8")
AKAMAI = (FIXTURES / "akamai_access_denied_403.html").read_text(encoding="utf-8")
REAL = "<html><head><title>Real page</title></head><body>REAL-CONTENT</body></html>"
CF_HEADERS = {"cf-mitigated": "challenge", "server": "cloudflare"}
FINAL_HEADERS = {"server": "cloudflare", "x-final": "1"}
# Depth 1 is too small to be the widget; depth 2 is the measured container.
BOXES = {1: {"x": 10, "y": 10, "width": 30, "height": 10},
         2: {"x": 100, "y": 200, "width": 300, "height": 65},
         3: {"x": 0, "y": 0, "width": 1280, "height": 720},
         4: {"x": 0, "y": 0, "width": 1280, "height": 720}}
CLICK_POINT = (125, 232.5)
FAILURES = []


def load_probe():
    path = ROOT / "bench" / "providers" / "docker" / "probe.py"
    spec = importlib.util.spec_from_file_location("m25_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: ожидалось {expected!r}, получено {actual!r}")


class Response:
    def __init__(self, status, headers, frame):
        self.status = status
        self.headers = dict(headers)
        self.frame = frame
        self.request = types.SimpleNamespace(resource_type="document",
                                             is_navigation_request=lambda: True)

    def all_headers(self):
        return dict(self.headers)


class Locator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def _depth(self):
        if "cf-turnstile-response" in self.selector and "ancestor" in self.selector:
            digits = [c for c in self.selector.rsplit("ancestor", 1)[1] if c.isdigit()]
            return int("".join(digits)) if digits else 1
        return None

    def count(self):
        if not self.page.up:
            return 0
        if "cf-turnstile-response" in self.selector:
            depth = self._depth()
            return 1 if depth is None or self.page.boxes.get(depth) else 0
        if "challenge-platform" in self.selector or "challenge" in self.selector:
            return 1
        return 0

    def bounding_box(self, timeout=None):
        depth = self._depth()
        return dict(self.page.boxes[depth]) if depth in self.page.boxes else None

    def input_value(self, timeout=None):
        return self.page.token

    def wait_for(self, *args, **kwargs):
        return None


class Mouse:
    def __init__(self, page):
        self.page = page
        self.at = None

    def move(self, x, y, **kwargs):
        self.at = (x, y)

    def down(self, **kwargs):
        self.page.downs.append((round(time.monotonic() - self.page.t0, 2), self.at))

    def up(self, **kwargs):
        self.page.on_click()


class Frame:
    def __init__(self, page):
        self.page = page
        self.url = "https://site.invalid/"

    def content(self):
        return INTERSTITIAL if self.page.up else REAL


class Page:
    """Measured CF interstitial: 403, then 200 and cf_clearance after a good click."""

    def __init__(self, *, pass_on_click_after_s=1.0, passes_by_itself_after_s=None,
                 sets_clearance=True, token="", boxes=None, body=None, status=403, headers=None):
        self.pass_on_click_after_s = pass_on_click_after_s
        self.passes_by_itself_after_s = passes_by_itself_after_s
        self.sets_clearance = sets_clearance
        self.token = token
        self.boxes = BOXES if boxes is None else boxes
        self.first_body = body
        self.first_status = status
        self.first_headers = CF_HEADERS if headers is None else headers
        self.handlers = []
        self.downs = []
        self.evaluates_while_up = 0
        self.cookies_list = [{"name": "__cf_bm", "value": "b", "domain": ".site.invalid", "path": "/"}]
        self.mouse = Mouse(self)
        self.main_frame = Frame(self)
        self.frames = [self.main_frame]
        self.url = "https://site.invalid/"
        self.up = True
        self.t0 = time.monotonic()
        self.context = types.SimpleNamespace(cookies=lambda *a, **k: list(self.cookies_list))

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def _emit(self, response):
        for handler in list(self.handlers):
            handler(response)

    def goto(self, url, **kwargs):
        self.t0 = time.monotonic()
        response = Response(self.first_status, self.first_headers, self.main_frame)
        self._emit(response)
        if self.first_body is not None:
            self.up = False
        return response

    def _pass(self):
        if not self.up:
            return
        self.up = False
        if self.sets_clearance:
            self.cookies_list.append({"name": "cf_clearance", "value": "c",
                                      "domain": ".site.invalid", "path": "/"})
        self._emit(Response(200, FINAL_HEADERS, self.main_frame))

    def _tick(self):
        if (self.up and self.passes_by_itself_after_s is not None
                and time.monotonic() - self.t0 >= self.passes_by_itself_after_s):
            self._pass()

    def on_click(self):
        if (self.pass_on_click_after_s is not None
                and time.monotonic() - self.t0 >= self.pass_on_click_after_s):
            self._pass()

    def title(self):
        self._tick()
        if self.first_body is not None:
            return "Access Denied"
        return "Just a moment..." if self.up else "Real page"

    def locator(self, selector):
        self._tick()
        return Locator(self, selector)

    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000)
        self._tick()

    def evaluate(self, expression, *args):
        self._tick()
        if self.up:
            self.evaluates_while_up += 1
        if "userAgent" in expression:
            return "Mozilla/5.0 fixture"
        return "complete"

    def content(self):
        return self.main_frame.content()


def run(probe, page, *, budget_ms, adapter="patchright"):
    base = probe.PatchrightAdapter if adapter == "patchright" else probe.PlaywrightAdapter

    class Fake(base):
        def start(self):
            self.version = "fixture"
            self.page = page

        def close(self):
            pass

    if page.first_body is not None:
        page.main_frame.content = lambda: page.first_body
    started = time.monotonic()
    result = probe.run_probe(adapter, "https://site.invalid/", mode="cold", content_only=True,
                             budget_ms=budget_ms, adapter_factory=lambda _: Fake(),
                             metrics=lambda: (0, 0))
    return result, time.monotonic() - started


def scenarios(probe):
    os.environ["ABG_SESSION_EXPORT"] = "1"
    page = Page(pass_on_click_after_s=1.0)
    result, _ = run(probe, page, budget_ms=30_000)
    check("pass: status", result["status"], 200)
    check("pass: verdict", result["challenge"], "none")
    check("pass: final document headers", result["headers"], FINAL_HEADERS)
    check("pass: body of the passed page", "REAL-CONTENT" in result["html"], True)
    check("pass: two clicks (first too early)", len(page.downs), 2)
    check("pass: click point x+25, middle", [at for _, at in page.downs], [CLICK_POINT] * 2)
    if len(page.downs) == 2:
        gap = page.downs[1][0] - page.downs[0][0]
        check("pass: retry after ~4 s", 3.5 <= gap <= 5.0, True)
    check("pass: no page scripts while the interstitial is up", page.evaluates_while_up, 0)
    names = [c["name"] for c in (result.get("session") or {}).get("cookies", [])]
    check("pass: session carries cf_clearance", "cf_clearance" in names, True)

    page = Page(pass_on_click_after_s=None, passes_by_itself_after_s=1.0, token="already-filled")
    result, _ = run(probe, page, budget_ms=30_000)
    check("token present: no click", page.downs, [])
    check("token present: status", result["status"], 200)

    # The first click already clears the interstitial; only the cookie is missing.
    page = Page(pass_on_click_after_s=0.0, sets_clearance=False)
    result, elapsed = run(probe, page, budget_ms=8_000)
    check("no cf_clearance: not accepted", (result["status"], result["challenge"]), (403, "suspected"))
    check("no cf_clearance: clicked once", len(page.downs), 1)
    check("no cf_clearance: bounded by half the budget", elapsed < 5.5, True)

    page = Page(pass_on_click_after_s=None)
    result, elapsed = run(probe, page, budget_ms=30_000)
    check("never passes: original 403 kept", (result["status"], result["challenge"], result["err"]),
          (403, "suspected", ""))
    check("never passes: kept clicking", len(page.downs) >= 2, True)
    check("never passes: capped at 12 s", 10.5 <= elapsed <= 14.0, True)

    page = Page(pass_on_click_after_s=0.0, boxes={1: BOXES[1]})
    result, elapsed = run(probe, page, budget_ms=6_000)
    check("no widget box in bounds: no click", page.downs, [])

    page = Page(pass_on_click_after_s=0.0)
    result, elapsed = run(probe, page, budget_ms=30_000, adapter="playwright")
    check("playwright adapter: no click", page.downs, [])
    check("playwright adapter: no wait", elapsed < 2.0, True)

    page = Page(pass_on_click_after_s=0.0, body=AKAMAI, headers={"server": "AkamaiGHost"})
    result, elapsed = run(probe, page, budget_ms=30_000)
    check("non-CF 403: no click", page.downs, [])
    check("non-CF 403: no wait", elapsed < 2.0, True)
    check("non-CF 403: verdict", result["challenge"], "ip_blocked")


def main():
    probe = load_probe()
    try:
        scenarios(probe)
    except Exception as exc:  # a crash is a failed check, not a pass
        FAILURES.append(f"{type(exc).__name__}: {exc}")
    if FAILURES:
        sys.exit("m25_turnstile_click:\n  " + "\n  ".join(FAILURES))
    print("ok")


if __name__ == "__main__":
    main()
