# Class-level results with local targets (2026-09-22)

This run adds targets that are measured but not published by name: sites
from a monitoring list, shops run by the maintainer, and social-network
profiles. They live in `bench/targets/local.toml`, which git ignores, and the
repository gets only the output of `python3 -m bench aggregate` — target
classes and counts, without ids, URLs or the egress address. See
[`bench/targets/README.md`](../../bench/targets/README.md) for the procedure.

## Setup

- 22.09.2026 UTC, one host, direct egress, one run.
- `python3 -m bench run --targets bench/targets/targets.toml bench/targets/local.toml --providers curl curl_cffi patchright scrapling`.
- Benchmark provider images, not the one-shot container: plain `curl`,
  `curl_cffi` with browser impersonation, Patchright and Scrapling browsers.
- One request per provider and target, at least 30 seconds between requests
  to the same host; 72 records, none of them an environment failure.
- A target counts as taken when its `expect` string is in the fetched
  content. Each `expect` was checked on the live page and does not occur on
  the challenge page.

Targets, 18 in total:

| Class | Public | Local | What it is |
| --- | --- | --- | --- |
| `none` | 2 | 6 | Pages without bot protection; the local ones are the maintainer's shops. |
| `cloudflare` | 2 | 0 | Cloudflare with a challenge for plain HTTP clients. |
| `cloudflare+spa` | 1 | 0 | Cloudflare plus content that is not in the first HTML response. |
| `cloudflare-passive` | 0 | 1 | A monitored site behind Cloudflare that serves plain clients. |
| `login-wall` | 1 | 5 | Public profile or post pages of social networks. |

The monitoring list had twelve Cloudflare-fronted URLs, but ten of them were
scripts and images on one CDN host, not pages, and one challenged page is
already a public target; the remaining page is the single
`cloudflare-passive` target.

## Result

Output of `python3 -m bench aggregate`, unchanged:

| Class | Targets | curl | curl_cffi | patchright | scrapling | Any provider |
|---|---|---|---|---|---|---|
| cloudflare | 2 | 0/2 | 1/2 | 1/2 | 2/2 | 2/2 |
| cloudflare+spa | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| cloudflare-passive | 1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| login-wall | 6 | 3/6 | 4/6 | 6/6 | 6/6 | 6/6 |
| none | 8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 |

Time per request across all 18 targets:

| Provider | Median, s | Max, s |
| --- | --- | --- |
| curl | 0.3 | 1.3 |
| curl_cffi | 0.4 | 1.2 |
| patchright | 2.1 | 6.4 |
| scrapling | 7.4 | 17.5 |

Failures were HTTP 403 and missing content; one `curl` request ended in a
provider error.

## Reading

- **No protection:** every provider took all eight pages. A browser adds
  seconds here and no coverage, which is why the ladder starts with HTTP.
- **Challenged Cloudflare:** only Scrapling took both targets; `curl_cffi`
  and Patchright took one each, and plain `curl` none.
- **Login walls:** both browsers took all six pages; HTTP clients took three
  or four. "Taken" means the public part of the page — the profile title or
  post metadata — not content that requires an account.

## Limits

One run from one address on 18 targets is a spot check, not a success rate.
Cloudflare decisions depend on the address and change over time, and the
local targets cannot be re-run by others. The class counts are published so
that the ladder's trade-offs can be checked against more than the public set.
