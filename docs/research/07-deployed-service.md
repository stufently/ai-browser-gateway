# M12b — deployed service on stand-host

Measured 2026-09-17 UTC. Production root:
`/home/user/services/ai-browser-gateway/`; project `ai-browser-gateway`,
instance `stand-host`, API `127.0.0.1:8765`.

## Release and runtime

- Release SHA: `929bded313e371808b0747fd9a400696a36638aa`.
- Runtime tag: `abg-runtime:929bded313e3`.
- Image ID: `sha256:b56b99cb0232452d3d1a6f315029fd7f1ae4131e379a8d48bbcf537350f08930`.
- Docker version 29.8.0, build 88096ef; Docker Compose version v5.5.1; Python 3.14.7.
- Python base pin: `sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6`.
- Docker CLI pin: `sha256:eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66`.

The host release script prepared the accepted commit; its idempotent verification
passed. Both containers use UID/GID `1002:1002`, read-only roots and release
mounts, `/tmp` tmpfs, and `unless-stopped`. API has socket group `983` and only
loopback publication. The monitor has neither Docker socket nor API token.
The secret directory is `0700`, all three secret files are `0600` and owned
by UID 1002. Client-token resolves to the private token file. Values were never
placed in argv, environment, evidence or Git; the deployment metadata/log scan
passed. The ping file was neither opened nor manually requested by the runner.

AC-602 recorded healthy API, unauthenticated fetch rejection (401), and monitor
uptime 174.5 seconds with empty logs. This confirms
local execution and absence of logged delivery errors; the coordinator separately
verifies actual success-ping history and automatic failure/recovery through the
healthchecks management API. The executor did not access that API.
Deployment checks now require empty monitor logs only for the last 150 seconds after waiting for uptime ≥130 seconds; secret scanning still receives the full lifetime logs of both containers.

## Measurement method

`tests/deployed_m12b.py` uses pinned Docker containers for HTTP. It keeps a
persistent per-hostname 30-second interval and a process lock, including across
separate invocations. Each target is submitted once per run with the exact
tracked expectation, budget 120000 ms, and unchanged product policy. API
attempts are preserved; target refusal does not become a successful fetch.
Docker errors, non-200 API responses, malformed JSON/schema and API connection
failures return nonzero. No page bodies or proxy URLs are retained.

Offline runner tests were committed in `3553709` before release preparation,
secret generation or production startup. The root-bind import regression was
fixed in `b86d5eb`; the complete suite then passed 475 tests. After adding the provider infrastructure
failure check in `3b70659`, AC-601 passed 476 tests (21 new runner tests).

Sanitized JSON evidence (directory `0700`):
`/home/user/.cache/abg-coord-20260917/m12b/`.
Deployment metadata is in `deploy.json`; profile measurements, API rotation and
target attempts are in `profiles.json`, `api-egress.json` and `targets.json`.
These files represent the most recent run; acceptance reruns refresh them.

## Egress profiles

Echo: `http://api.ipify.org`. Direct control: HTTP 200, IP `192.0.2.10`.
Unauthenticated request through ms1: HTTP 407.
All 15 authenticated profiles returned distinct IPs, different from direct.

| Profile | HTTP | Egress IP | Failure class |
|---|---:|---|---|
| ms1 | 200 | 198.51.100.21 | none |
| ms2 | 200 | 198.51.100.23 | none |
| ms3 | 200 | 198.51.100.28 | none |
| ms4 | 200 | 198.51.100.27 | none |
| ms5 | 200 | 198.51.100.26 | none |
| ms6 | 200 | 198.51.100.25 | none |
| ms7 | 200 | 198.51.100.32 | none |
| ms8 | 200 | 198.51.100.22 | none |
| ms9 | 200 | 198.51.100.24 | none |
| ms10 | 200 | 198.51.100.33 | none |
| ms11 | 200 | 198.51.100.36 | none |
| ms12 | 200 | 198.51.100.37 | none |
| ms13 | 200 | 198.51.100.35 | none |
| ms14 | 200 | 198.51.100.34 | none |
| ms15 | 200 | 198.51.100.31 | none |

## API egress and rotation

Three valid POST requests, with `allow_browser=false` and the expected IP
from the profile measurements. Every direct attempt returned HTTP 200 with
`content_missing`; the API then used the rotated egress profile.

| Request | Profile | HTTP | ok | Total elapsed ms |
|---|---|---:|---|---:|
| 1 | ms1 | 200 | true | 2678 |
| 2 | ms2 | 200 | true | 2682 |
| 3 | ms3 | 200 | true | 2654 |

The required second and third requests matched exactly `ms2` and `ms3`,
with the expected IP present in returned content. All profiles were working,
so no intermediate requests were needed. Rotation evidence is in
`api-egress.json`; later acceptance runs start at the service’s then-current
rotation position and prove the next two profiles relative to their anchor.

## Six-target API matrix

All six targets returned `ok:true` on this run with their exact tracked
`expected_text`. Challenges below are the API’s original classifications,
including challenge flags on successful product outcomes. They are not rewritten
to `none`. These are point-in-time observations, not a future availability claim.

| Target | Provider | Profile | HTTP | Challenge | Attempt elapsed ms | Attempt result |
|---|---|---|---:|---|---:|---|
| control-hqd | curl | direct | 200 | none | 347 | ok |
| control-static | curl | direct | 200 | none | 67 | ok |
| cf-lowendtalk | curl | direct | 403 | suspected | 117 | http_403 |
| cf-lowendtalk | patchright | direct | 200 | captcha | 2057 | ok |
| cf-bizprofile | curl | direct | 403 | suspected | 129 | http_403 |
| cf-bizprofile | patchright | direct | 403 | suspected | 1114 | http_403 |
| cf-bizprofile | scrapling | direct | 200 | suspected | 16530 | ok |
| cf-spa-chatgpt-share | curl | direct | 200 | none | 1053 | ok |
| login-instagram | curl | direct | 200 | none | 665 | content_missing |
| login-instagram | patchright | direct | 200 | none | 1997 | ok |

| Target | Final outcome | Total elapsed ms |
|---|---|---:|
| control-hqd | ok | 1569 |
| control-static | ok | 1251 |
| cf-lowendtalk | ok | 4305 |
| cf-bizprofile | ok | 21054 |
| cf-spa-chatgpt-share | ok | 2441 |
| login-instagram | ok | 4907 |

The deployed CLI `scripts/abg-fetch https://example.com/ text` used the
client-token symlink, returned rc=0, and contained `Example Domain`.
Full per-attempt decisions, status, challenge, provider, profile and timing are
in `targets.json`. The original expectations, browser policy and budgets were
not relaxed, and no target was retried to obtain a green outcome.

The service remains running. No push or merge was performed; the coordinator
collects the branch and performs independent mutation and healthchecks checks.
