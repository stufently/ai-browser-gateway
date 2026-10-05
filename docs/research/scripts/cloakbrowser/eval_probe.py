"""Evaluation-only probe for CloakBrowser (docs/research/11-cloakbrowser.md).

Reuses bench/providers/docker/probe.py unchanged and adds one adapter; the
bench registry is not touched. Environment switches:
  CB_HEADLESS=1  headless launch (default: headed under xvfb, like patchright)
  CB_WAIT_MS=N   after `load`, poll up to N ms for the sentinel (challenge wait)
  CB_CLICK=1     with CB_WAIT_MS: humanize=True and one click on the Turnstile
                 iframe; prints `cloak-eval:` diagnostics to stderr
"""
import contextlib
import json
import os
import sys
import time

sys.path.insert(0, "/opt/abg")
import probe  # noqa: E402


class CloakBrowserAdapter(probe.PlaywrightAdapter):
    package = "cloakbrowser"

    def start(self) -> None:
        from cloakbrowser import launch

        self.version = probe._version("cloakbrowser")
        options = {"headless": os.environ.get("CB_HEADLESS", "0") == "1",
                   "humanize": os.environ.get("CB_CLICK") == "1"}
        proxy = probe._proxy_url()
        if proxy:
            options["proxy"] = proxy
        self.browser = launch(**options)
        self.page = self.browser.new_page()

    def navigate(self, url):
        wait_ms = int(os.environ.get("CB_WAIT_MS", "0"))
        if not wait_ms:
            return super().navigate(url)
        documents = []

        def on_response(resp):
            # Only main-frame document responses: the challenge page and,
            # if the challenge clears, the page that replaces it.
            if resp.request.is_navigation_request() and resp.frame == self.page.main_frame:
                documents.append(resp)

        self.page.on("response", on_response)
        response = self.page.goto(url, wait_until="load",
                                  timeout=probe._bound_timeout_ms(120_000))
        deadline = time.monotonic() + probe._bound_timeout_ms(wait_ms) / 1000
        clicked = False
        while time.monotonic() < deadline:
            body = probe._playwright_body(self.page, "", 0)
            if self.sentinel and self.sentinel in body:
                break
            if os.environ.get("CB_CLICK") == "1" and not clicked:
                for frame in self.page.frames:
                    if "challenges.cloudflare.com" in frame.url:
                        try:
                            box = frame.frame_element().bounding_box()
                            if box:
                                self.page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
                                clicked = True
                                print("cloak-eval: clicked", box, file=sys.stderr)
                        except Exception:
                            pass
            self.page.wait_for_timeout(1000)
        if os.environ.get("CB_CLICK") == "1":
            print("cloak-eval: frames", [f.url[:80] for f in self.page.frames],
                  "clicked", clicked, file=sys.stderr)
        last = documents[-1] if documents else response
        status = last.status if last is not None else None
        headers = None if last is None else probe._normalize_headers(last.headers)
        body = probe._playwright_body(self.page, self.sentinel, 0)
        return probe._result(status, self.page.url, body.encode(), 0, self.page.title(), headers=headers)

    def close(self) -> None:
        if hasattr(self, "browser"):
            self.browser.close()


def factory(name):
    if name == "cloakbrowser":
        return CloakBrowserAdapter()
    return probe.make_adapter(name)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("sentinel", nargs="?")
    parser.add_argument("--content-only", action="store_true")
    parser.add_argument("--mode", choices=("cold", "warm"), default="cold")
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--budget-ms", type=int, default=None)
    args = parser.parse_args(argv)
    with contextlib.redirect_stdout(sys.stderr):
        payload = probe.run_probe(
            "cloakbrowser", args.url, args.sentinel, mode=args.mode,
            adapter_factory=factory, include_content=args.include_content,
            budget_ms=args.budget_ms, content_only=args.content_only)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
