# M2 runner

The host runner uses only the Python standard library. Browser and HTTP provider
packages are installed only by the Dockerfiles. Docker builds and live measurements
are deliberately outside M2's automated acceptance; no benchmark results are
included in this change.

## Local stand A

In separate terminals:

```bash
python3 -m bench.server
python3 -m bench providers
python3 -m bench plan --providers curl playwright --cells scenario:static scenario:js --cold 2 --warm 3
python3 -m bench run --providers curl playwright --cells scenario:static scenario:js --cold 2 --warm 3 --output stand.jsonl
python3 -m bench report stand.jsonl --order curl playwright --output stand.md
```

`run` and `report --output` use a new output file and refuse to overwrite an earlier run. Defaults:
all seven implemented providers, all twelve stand scenarios, one cold request,
one warm request for browsers, timeout 180 seconds, pause 20 seconds per repeated
host. `--base-url` changes the stand URL. Scenario cells use Docker host networking;
external target cells use the default Docker network. Each item starts a fresh
container as UID/GID `1002:1002`, with no repository mounts.

Warm starts the browser and opens `about:blank` before the target timer starts.
It navigates to the target once. Cold includes browser startup. Neither mode shares
a target cache or browser session across plan items.

## Explicit external targets

```bash
python3 -m bench plan --targets bench/targets/targets.toml --providers curl playwright
python3 -m bench run --targets bench/targets/targets.toml --providers curl playwright --output targets.jsonl
python3 -m bench report targets.jsonl --order curl playwright
```

Only `valid != false` targets are included. As required by that target file, the
CLI enforces one cold request per provider and target and at least 30 seconds
between requests to the same host, including after failures. Target URLs are never
requested by `providers`, `plan`, or `report`. `wayback` has a registry descriptor
and can appear in plans; its adapter/image belong to the next milestone and it is
excluded from defaults.

## Container preparation (operator, not executed by acceptance)

Build from the shared probe directory, for example:

```bash
docker build -f bench/providers/docker/Dockerfile.curl -t abg-curl:m2 bench/providers/docker
docker build -f bench/providers/docker/Dockerfile.playwright -t abg-playwright:m2 bench/providers/docker
```

The same naming applies to `curl_cffi`, `primp`, `patchright`, `camoufox`, and
`pydoll`. Images select their adapter with `ABG_PROVIDER`. The probe interface is
`probe.py URL SENTINEL [--mode cold|warm]`; a completed probe prints normalized JSON,
including failures. The runner also accepts noisy stdout and parses the last line
that starts with `{`. Package versions are observed by the probe; image tags identify
the operator-built artifacts. Provider package pins match the operator’s existing
local build recipes. Base images, OS packages, and browser downloads still need
retained image digests for exact replay: these recipes do not promise byte-identical
rebuilds. Retain built images and their digests alongside live results.

## Interpreting results

The report shows every observed environment value, successes/attempts for each
provider and cell, timing and peak RSS by provider and mode, and incremental
coverage using the unchanged M1 implementation. Median and nearest-rank p95 include
measured failures. Failed launch/protocol records with no numeric measurements use
zero placeholders required by M1 and are omitted from metric summaries; they remain
failures in coverage. Missing measurements display as `unknown`, never as estimated
provider performance. Browser `bytes` counts extracted UTF-8 content, not all network
traffic including subresources. RSS is the peak observed sum of process RSS in the container, sampled every 10 ms
with getrusage fallback. Shared pages can be counted by more than one process;
shorter peaks between samples can be missed. It is not the image size or cgroup
page-cache-inclusive memory usage. CPU includes startup and live browser descendants
when cgroup CPU accounting is available, including in warm mode.

Date and kernel are observed locally and Docker version crosses the same launcher
boundary as execution. Egress and ASN default to `unknown`; provide `--egress-ip`
and `--asn` only from an actual observation. No public IP/ASN service is contacted
implicitly. `environment.collect(reader=...)` accepts a callable receiving each
field name, so a deployment can supply its own verified reader.

The builder passes a generator to M1 `incremental()`. M1 internally materializes
records; that protected implementation is unchanged. The builder retains timings
for exact median/p95 rather than approximate streaming quantiles.

All new test timing/RSS observations are local fixture operations, not measurements
of Docker providers or real targets. Fake launchers exercise protocol and failure
behavior without issuing requests.
