# Benchmark targets

Two kinds of target files feed the benchmark.

- **Public targets** — [`targets.toml`](targets.toml). Tracked in git. A small,
  reviewed set that anyone can re-run.
- **Local targets** — `local.toml`. Ignored by git. Sites you measure but must
  not publish by name: monitored sites, your own shops, anything private. Start
  from [`local.example.toml`](local.example.toml).

## Run both

`--targets` takes several files. Their targets are merged, and target ids must
be unique across all of them. Raw runs go to `bench/local-runs/`, which git
also ignores:

```sh
python3 -m bench run \
  --targets bench/targets/targets.toml bench/targets/local.toml \
  --providers curl curl_cffi patchright scrapling \
  --output bench/local-runs/$(date -u +%Y%m%d-%H%M).jsonl
```

The target rules still apply: one request per provider and target, and at
least 30 seconds between requests to the same host.

## Publish only the summary

```sh
python3 -m bench aggregate bench/local-runs/<run>.jsonl \
  --targets bench/targets/targets.toml bench/targets/local.toml
```

`aggregate` prints one row per target class with the number of targets each
provider fetched out of those it measured. It never prints target ids, URLs,
egress addresses or ASNs, and its error messages do not repeat values from the
input files. Every target needs a `class`: lower-case words joined by `+` or
`-`, without dots.

**Do not commit** the raw JSONL of a run that includes local targets, or the
output of `python3 -m bench report` for it: both contain target ids, final
URLs and the egress address. Only the `aggregate` output is meant for the
repository.
