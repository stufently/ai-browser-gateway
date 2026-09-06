"""Twelve stand-A scenarios with distinct sentinels."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass


def _brotli_available() -> bool:
    return importlib.util.find_spec("brotli") is not None


_COMPRESSION_DESCRIPTION = (
    "gzip + brotli: body is compressed when Accept-Encoding asks for gzip or br"
    if _brotli_available()
    else (
        "gzip + brotli: gzip is served when requested; brotli (br) is not advertised "
        "and not served — the standard library has no brotli module"
    )
)


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    path: str
    sentinel: str
    requires_js: bool
    expected_status: int
    description: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="static",
        path="/static",
        sentinel="ABG_TEST_STATIC_OK",
        requires_js=False,
        expected_status=200,
        description="static HTML: provider overhead, lower bound",
    ),
    Scenario(
        id="redirect",
        path="/redirect",
        sentinel="ABG_TEST_REDIRECT_OK",
        requires_js=False,
        expected_status=200,
        description="chain of three 302 redirects, then the sentinel page",
    ),
    Scenario(
        id="compression",
        path="/compression",
        sentinel="ABG_TEST_COMPRESSION_OK",
        requires_js=False,
        expected_status=200,
        description=_COMPRESSION_DESCRIPTION,
    ),
    Scenario(
        id="js",
        path="/js",
        sentinel="ABG_TEST_JS_OK",
        requires_js=True,
        expected_status=200,
        description="sentinel is inserted by JS after load; absent from raw HTML",
    ),
    Scenario(
        id="spa",
        path="/spa",
        sentinel="ABG_TEST_SPA_OK",
        requires_js=True,
        expected_status=200,
        description="SPA: navigation + fetch + DOM patch",
    ),
    Scenario(
        id="iframe",
        path="/iframe",
        sentinel="ABG_TEST_IFRAME_OK",
        requires_js=True,
        expected_status=200,
        description="sentinel lives in a same-origin iframe child, not the parent",
    ),
    Scenario(
        id="shadow",
        path="/shadow",
        sentinel="ABG_TEST_SHADOW_OK",
        requires_js=True,
        expected_status=200,
        description="sentinel in a closed Shadow DOM (attachShadow mode=closed)",
    ),
    Scenario(
        id="session",
        path="/session/start",
        sentinel="ABG_TEST_SESSION_OK",
        requires_js=False,
        expected_status=200,
        description="request A sets a cookie; request B requires it",
    ),
    Scenario(
        id="errors",
        path="/errors",
        sentinel="ABG_TEST_ERRORS_OK",
        requires_js=False,
        expected_status=403,
        description=(
            "deterministic 403/429/503 from the sub-path; sentinel is only on "
            "/errors/explain so success on the error URLs is impossible by construction"
        ),
    ),
    Scenario(
        id="slow",
        path="/slow",
        sentinel="ABG_TEST_SLOW_OK",
        requires_js=False,
        expected_status=200,
        description="slow response; delay comes from the query string, default 0",
    ),
    Scenario(
        id="broken_js",
        path="/broken-js",
        sentinel="ABG_TEST_BROKEN_JS_OK",
        requires_js=True,
        expected_status=200,
        description="JS throws before inserting the sentinel",
    ),
    Scenario(
        id="large_dom",
        path="/large-dom",
        sentinel="ABG_TEST_LARGE_DOM_OK",
        requires_js=False,
        expected_status=200,
        description="large DOM; node count comes from the query string, default small",
    ),
)

_BY_ID = {item.id: item for item in SCENARIOS}


def by_id(scenario_id: str) -> Scenario:
    return _BY_ID[scenario_id]
