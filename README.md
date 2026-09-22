# AI Browser Gateway

Fetch web pages for AI agents with HTTP first, a headless browser when needed, and a provider ladder for JavaScript rendering and Cloudflare challenges.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Container: GHCR](https://img.shields.io/badge/Container-GHCR-blue)](https://github.com/stufently/ai-browser-gateway/pkgs/container/ai-browser-gateway-oneshot)

## Why

Use the cheapest sufficient way to read a page: start with HTTP and browser
headers, then launch a browser when the response needs it. The initial benchmark
found that browsers added value through JavaScript rendering; they did not
improve coverage over HTTP with browser headers on that set of live targets.
A later Scrapling measurement added a Cloudflare target that Patchright could
not fetch. See [Benchmarks](#benchmarks) for the evidence and its limits.

The one-shot container runs the provider ladder locally. It needs no gateway
API, token, or Docker daemon inside the container.

## When a plain fetch is not enough

A one-line HTTP client is enough when the response already contains the page.
It is not enough when the body is a refusal or a shell. The signs below are
the ones this repository already records.

- An HTTP 403, often with a challenge signal. The ladder treats HTTP 403 and
  a suspected challenge as a reason to try a browser, when browsers are
  allowed and budget remains. That next step is an attempt, not a guarantee.
- An interstitial instead of the page. A Cloudflare interstitial recorded in
  the research notes is titled `Just a moment`. HTTP 200 is not proof of
  success: the [Russian notes](docs/README.ru.md) say a Cloudflare stub can
  also arrive as 200, and it can be longer than the real page.
- A response that arrived without the page text, because that text is
  produced by JavaScript. The Russian notes call this `content_missing`:
  the bytes came back, and the content was not in them. The initial
  benchmark found the browser's value in that rendering, not in extra
  coverage over HTTP that already sent browser headers.
- A page behind a login wall. This gateway does not log in. [Responsible use](#responsible-use)
  states the same limit for interactive challenges: no CAPTCHA-solving
  service is integrated, and a challenge that needs a person stops here.

## Quick start

Read a page as Markdown:

```sh
docker run --rm ghcr.io/stufently/ai-browser-gateway-oneshot:latest https://example.com/ --format markdown
```

For a site behind Cloudflare, allow a larger budget; the default 30 seconds
leaves little room for the browser steps:

```sh
docker run --rm ghcr.io/stufently/ai-browser-gateway-oneshot:latest https://cloudflare-protected.example/ --format markdown --budget-ms 90000
```

Or build and run from the repository root:

```sh
docker build -f deploy/Dockerfile.oneshot -t ai-browser-gateway-oneshot .
docker run --rm ai-browser-gateway-oneshot https://example.com/ --format markdown
```

## CLI reference

The container entry point runs `python3 -m gateway.oneshot`:

```text
python3 -m gateway.oneshot URL [--format MODE] [--expected-text TEXT] [--budget-ms N] [--no-browser]
```

`URL` is required. Running the module outside the image requires the image's
dependencies and probe setup.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--format` | `text` | Output content as `text`, `html`, `markdown`, `links`, or `meta`. |
| `--expected-text` | Unset (`null`) | Require this nonblank text in the page HTML or text. |
| `--budget-ms` | `30000` | Total request budget in milliseconds, from 1 to 180000. |
| `--no-browser` | Off (browsers allowed) | Use only the HTTP provider. |

For exit codes 0 and 1, stdout contains one JSON line with fields `ok`, `url`,
`final_url`, `provider`, `age_hours`, `error_type`, `step`, `elapsed_ms`, `format`,
`content`, and `attempts`. The selected format changes `content`; the surrounding
JSON remains. `attempts` records provider outcomes and ladder decisions.

| Exit code | Meaning | stderr |
| --- | --- | --- |
| 0 | `ok=true`: page accepted. | No CLI error. |
| 1 | `ok=false`: page not delivered. Inspect the JSON outcome. | No CLI error. |
| 2 | Invalid arguments. | `{"error": "invalid_request"}` |
| 3 | Internal error. | `{"error": "internal_error"}` |
| 4 | Interrupted by SIGTERM, SIGINT, or SIGHUP during the ladder. | `{"error": "interrupted"}` |

For codes 2 through 4, stdout is empty and stderr contains the single JSON error
line shown above. `--help` is not supported: it returns code 2 and
`invalid_request` instead of usage text.

## How the provider ladder works

The one-shot ladder stops as soon as a page is accepted, or when policy or the
budget prevents further attempts. An HTTP 200 alone does not establish success:
the gateway also checks content and challenge signals.

| Provider | What it does | When it runs |
| --- | --- | --- |
| `curl_cffi` | HTTP with browser headers and TLS impersonation. | First; its attempt is capped at 15000 ms within the total budget. |
| `patchright` | Browser rendering for JavaScript pages. | After an eligible HTTP failure, such as missing content, a suspected challenge, HTTP 403, or an HTTP timeout, if browsers are allowed and budget remains. |
| `scrapling` | Stealthy browser session with `solve_cloudflare=True`. | After an eligible Patchright failure, if budget remains. |

Some outcomes stop escalation: interactive challenges need human action;
HTTP 429 skips browser attempts; connection errors and browser timeouts do not
automatically advance to the next browser. The ladder does not guarantee access
to every Cloudflare-protected page.

`--no-browser` removes both browser providers. The one-shot image makes direct
requests, with no proxy profiles, RSS/Wayback entrances, or cache. Environment
variables `http_proxy`, `https_proxy`, `all_proxy`, `ftp_proxy`, and `no_proxy`
are ignored in every letter case.

## MCP server for AI agents

`scripts/abg-mcp` (Python 3.12+, stdlib only) exposes one MCP tool, `fetch_page`,
over stdio. It calls the existing gateway API and its full provider ladder.
Add a stdio server to your MCP client's configuration, using absolute paths:

```json
{
  "mcpServers": {
    "ai-browser-gateway": {
      "command": "/path/to/ai-browser-gateway/scripts/abg-mcp",
      "env": {
        "ABG_URL": "http://127.0.0.1:8765/v1/fetch",
        "ABG_TOKEN_FILE": "/path/to/abg/client-token"
      }
    }
  }
}
```

From the checkout, `python3 -m gateway.mcp_stdio` is equivalent. The API must
already be running; the adapter opens no listening socket. `ABG_TOKEN` takes
precedence over `ABG_TOKEN_FILE`, whose default is `~/.config/abg/client-token`.
The API URL above is the default. HTTP uses no system proxy or redirects.

`fetch_page` requires `url`; optional arguments are `format`
(`text|html|markdown|links|meta`, default `text`), `expected_text` (default null),
`budget_ms` (1–180000, default 30000), `allow_browser` (default true), and
`max_age_hours` (default 0). Fetch options come from tool arguments.
Results include page content plus provider/attempt metadata; gateway and
transport failures are tool errors. Credentials are redacted from results.
Tool calls run concurrently (up to 8), while ping is answered immediately.
Invalid tool arguments are reported as tool errors with `isError: true`.
Page text (or error text) appears in both the text content block and
`structuredContent.content`, alongside the available provider/attempt metadata.
The server negotiates MCP `2025-11-25` or `2025-06-18`, falling back to
`2025-11-25` for an unsupported version. Stdout carries only JSON-RPC lines.

## Self-hosted HTTP API

The gateway service exposes `POST /v1/fetch` with Bearer authentication and a
JSON request containing `url` and optional fetch settings. Use
`scripts/abg-fetch URL [text|html|markdown|links|meta]` to call it from the shell.
The MCP adapter uses this service too. See the
[Russian deployment documentation](docs/README.ru.md) for setup and operations.

## How it compares

This table compares only clients the repository runs. The first row is the
ordinary HTTP client that sits below the ladder. The other three rows are
the ladder itself, in the order [How the provider ladder works](#how-the-provider-ladder-works)
already states. No success rate is claimed here; the samples and their
limits are in [Benchmarks](#benchmarks).

| Approach | How it reaches the page | What it is for | When it runs | What you pay |
| --- | --- | --- | --- | --- |
| Ordinary HTTP client | HTTP with no TLS-fingerprint impersonation and no browser. | The lower bound. It reads a page only when the server already returns that page to a normal client. A challenge can end as HTTP 403 or an interstitial. | Not a ladder step. It is the request this project starts from. | One short request, and no browser process. |
| `curl_cffi` | HTTP with browser headers and TLS impersonation. | The first attempt inside the ladder. | First. That attempt is capped at 15000 ms within the total budget. | The cheapest step that still speaks HTTP. |
| `patchright` | A browser session that renders JavaScript. | An HTTP result that was not accepted: missing content, a suspected challenge, HTTP 403, or an HTTP timeout. | After an eligible HTTP failure, if browsers are allowed and budget remains. | A browser process, taken from the time that remains. |
| `scrapling` | A stealthier browser session with `solve_cloudflare=True`. | A page the Patchright attempt did not accept. | After an eligible Patchright failure, if budget remains. | A second browser session, and only while budget remains. |

Some outcomes never reach the next row. An interactive challenge needs a
person. HTTP 429 skips the browser steps. A connection error or a browser
timeout does not by itself move to the next browser. `--no-browser` removes
both browser providers and leaves the HTTP provider. The ladder does not
guarantee access to every Cloudflare-protected page.

## Benchmarks

- In the initial five-target live benchmark, HTTP with browser headers fetched
  four targets, and none of the tested browsers added another. The controlled
  scenarios showed the browser's value in JavaScript rendering. See the
  [phase 1 verdict](docs/research/04-phase1-verdict.md).
- In the later six-target comparison, Scrapling with `solve_cloudflare=True`
  fetched the Cloudflare-protected Bizprofile target that Patchright failed to
  fetch, adding one unique target. See the
  [Scrapling measurements](docs/research/05-scrapling.md).

These are small samples from specific runs and network conditions, not a general success-rate promise.

## FAQ

### Why does a plain HTTP client get 403 when a browser does not?

A plain client shows its own TLS fingerprint and does not run JavaScript,
so a check can answer it with HTTP 403 or an interstitial. A browser is
not an automatic win: on the measured set, browsers helped by rendering
JavaScript and did not improve coverage over HTTP with browser headers. See [Benchmarks](#benchmarks).

### Does this project solve CAPTCHA and interactive challenges?

No. No CAPTCHA-solving service is integrated. An interactive challenge
stops the ladder, because it needs a person. The same limit is stated in
[Responsible use](#responsible-use).

### Do I need a server and a token just to read a page?

No. The one-shot image in [Quick start](#quick-start) runs the provider
ladder locally. It needs no gateway API and no token. A token is only for
the self-hosted `POST /v1/fetch` API, and for the MCP adapter that calls it.

### How do I connect this to an MCP client?

Add `scripts/abg-mcp` as a stdio server. It exposes one tool, `fetch_page`,
and the gateway API has to be running already. Arguments, defaults, and
protocol versions `2025-11-25` and `2025-06-18` are in
[MCP server for AI agents](#mcp-server-for-ai-agents).

### Can it log in and read pages behind a login wall?

No. The gateway does not log in and does not read a page that requires an
authenticated session. A challenge that needs a person is the same kind of
stop, described in [Responsible use](#responsible-use).

### How long should I wait for a page behind Cloudflare?

The default budget is 30 seconds (`--budget-ms 30000`). Once the ladder
reaches a browser, that is often too short. [Quick start](#quick-start)
uses 90 seconds (`--budget-ms 90000`) for a Cloudflare-protected page.
The allowed range is 1 to 180000 milliseconds.

## Responsible use

Use this gateway for your own sites, monitoring, and page reading by AI agents.
Respect each site's terms and robots.txt. No CAPTCHA-solving services are
integrated; interactive challenges can require human action.

## Development

Run the unit suite and frozen probes from the repository root with the Python
image named in the commands below. Both containers run without network access:

```sh
docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm python3 -m unittest discover -q -s tests -t .
docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container
```

## Documentation

- [Russian README](docs/README.ru.md): deployment and operations notes.
- [Research](docs/research/): the phase-1 verdict, the Scrapling
  measurements, and the other write-ups already in the tree.
- [Changelog](CHANGELOG.md): what changed in the project.
- [Security](SECURITY.md): how to report a vulnerability.

## License

The project is licensed under the [MIT License](LICENSE). Google Chrome bundled
in the container image is distributed under Google's terms.
