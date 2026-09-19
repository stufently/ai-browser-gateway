# AI Browser Gateway

Единый шлюз доступа к веб-страницам для агентов и автоматизации: один API, за
которым спрятаны все способы достать страницу — от обычного HTTP-запроса до
браузера с антидетектом, — и который выбирает **самый дешёвый достаточный**.

Проект заводится вместо того, чтобы в пятый раз повторять один и тот же бой с
Cloudflare в очередном проекте: сейчас скрапинг размазан по `cf-fetch`,
`gpt-web-gateway`, мониторингу и SEO-парсерам, и каждый решает его заново.

## Статус: фаза 1 измерена

Стек выбран **по числам, а не по описаниям**. Главный вывод замера 06.09.2026:

> **Браузер окупается рендерингом, а не обходом блокировок.**

Ни один из пяти движков (playwright, patchright с настоящим Chrome, camoufox,
pydoll, playwright+stealth) не добавил **ни одной** цели к обычному `curl` с
браузерными заголовками. Зато на стенде способностей браузер берёт 7 сценариев из
12 против 5 — и вся разница там, где нужен JS. Признак для запуска браузера,
следовательно, не отказ, а `content_missing`: ответ пришёл, а содержимого в нём
нет.

Лестница по итогам замера:

```
обходной вход (RSS, sitemap, JSON, архив) → HTTP с браузерными заголовками →
patchright → смена egress → человек
```

14.09.2026 замер M8: `scrapling` с `solve_cloudflare` взял `cf-bizprofile`,
которую patchright на том же прогоне не взял (incremental 1). В лестницу ядра
ещё не встроен — это следующий шаг, если владелец подтвердит. Числа:
`docs/research/05-scrapling.md`.

| Документ | Что в нём |
|---|---|
| `docs/research/05-scrapling.md` | M8: scrapling vs patchright vs curl, в том числе живой Instagram |
| `docs/research/04-phase1-verdict.md` | вердикт: кто остаётся, кто исключён и на каком основании |
| `docs/research/03-stand-b-results.md` | измеренные таблицы: проходимость и способности |
| `docs/research/01-candidates.md` | 25 кандидатов, сверенных с реестрами |
| `docs/research/02-egress-and-managed-browser.md` | свой egress и managed-браузер Cloudflare |
| `docs/BENCHMARK_PLAN.md` | как меряем: два стенда, 12 сценариев, признак успеха |
| `TASKS.md` | статус работ |

## Ядро шлюза

Пакет `gateway/` исполняет лестницу для одного URL: `curl`, затем по решению
`bench.escalate.next_step` — `patchright` для рендеринга или `curl` через другой
egress. После повторной блокировки на новом egress требуется человек.
При `max_age_hours > 0` перед HTTP пробуются `rss` и `wayback`; успех входа
требует найденного sentinel и известного возраста не больше заданного допуска.
При нулевом допуске входов в плане нет.

```python
from gateway.engine import run
from gateway.fetch import BenchFetcher
from gateway.models import GatewayRequest

request = GatewayRequest(url="https://example.invalid/page", sentinel="PAGE_OK")
fetcher = BenchFetcher(request.url, request.sentinel)
outcome = run(request, fetcher)
print(outcome.ok, outcome.provider, outcome.step)
```

`BenchFetcher` запускает провайдер в Docker (`--user 1002:1002`, образы из
реестра). Нужен работающий Docker; провайдерам не монтируется Docker socket.
Ядро требует sentinel. Python-вход M10:

```python
from gateway.fetch import ProductFetcher
from gateway.product import ProductRequest, run_product

request = ProductRequest("https://example.org")
outcome = run_product(request, ProductFetcher(request.url))
```

URL-only не подтверждает смысл. `expected_text` клиента — точная подстрока
HTML/text; HTTP-ошибки и interactive challenge она не отменяет.
Trace с challenge — `outcome.attempts`; отказ: пустые html/text,
причина `error_type`, решение `step`.
Docker UID/GID `1002:1002`; live: `python3 tests/live_m10_product.py`.
[Контракт M10](specs/m10-product-contract.md).
HTTP API/CLI — M11, сервис — M12.

Имена `profiles` и `entrances` у `BenchFetcher` обязаны совпадать с именами в
`GatewayRequest` (`egress_profiles` и входы плана). Несовпадение сейчас даёт
`not_measured` на транспорте, а ядро M7 на этом reason не продолжает лестницу —
это ограничение согласованного контракта, а не безопасный продуктовый запрос.

Контракт транспорта: `fetcher(step, budget_ms) -> ProviderReply`. Ядро передаёт
остаток общего бюджета перед каждой попыткой, записывает её результат и решение
в `outcome.attempts`. На отказе содержимое пустое, `provider` и `age_hours` равны
`None`, а `error_type` и `step` объясняют остановку. Исключения адаптера выходят
вызывающему; штатные отказы адаптер возвращает как `FetchResult`.

## Харнесс

```bash
python3 -m bench.server            # поднять стенд A (12 детерминированных сценариев)
python3 -m unittest discover -s tests -t .
python3 tests/mutation_gate.py     # 17 мутаций, каждая обязана быть убита
python3 tests/mutation_gate_gateway.py  # 5 мутаций ядра M7
```

Ни одной сторонней зависимости: только стандартная библиотека Python.

## Правила проекта

- **Сначала измерить, потом выбрать.** Провайдер попадает в стек не потому, что
  хорошо выглядит, а потому что закрывает страницы, которые не закрывают более
  дешёвые.
- **HTTP 200 успехом не считается.** Заглушка Cloudflare тоже приходит с 200 и
  бывает длиннее настоящей страницы. Успех — найденный sentinel на ответе,
  который не является отказом.
- **Строка ожидания не должна встречаться на странице отказа.** Оплачено:
  `expect = "bizprofile"` совпадал с заглушкой, которая называет заблокированный
  хост, и провал засчитывался успехом.
- **Замер без egress ничего не доказывает.** Один и тот же образ с одним
  отпечатком получает 200 с одного адреса и 403 с другого.

## M11 HTTP / CLI

Local interfaces; deployed service/pool/monitoring belong to M12.
From the clone root, with an existing test `ABG_TOKEN`:

```bash
docker run --rm --user 1002:1002 \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -p 127.0.0.1:8765:8765 -v "$PWD:$PWD:ro" -w "$PWD" \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e ABG_TOKEN \
  python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 \
  python3 -m gateway.httpapi
scripts/abg-fetch https://example.org markdown
```

`abg-fetch URL [text|html|markdown|links|meta]` defaults to text. Docker client:
UID1002, host network, RO file, symlinks supported; image override `ABG_CLIENT_IMAGE`.
`ABG_TOKEN` precedes `ABG_TOKEN_FILE`. CLI mounts the file (default host
`$HOME/.config/abg/client-token`); server needs a RO mount readable by UID1002.
Missing/invalid token fails closed. No token values in argv/repo.

Env defaults (all names prefixed `ABG_`): server `BIND=0.0.0.0`, `PORT=8765`,
`BROWSER_LIMIT=1`; client `URL=http://127.0.0.1:8765/v1/fetch`, `BUDGET_MS=30000`
(cap 180000), `MAX_AGE_HOURS=0`, `ALLOW_BROWSER=1` (only 0/1), `EXPECTED_TEXT` unset/null.

`GET /health` needs no auth. `POST /v1/fetch` requires Bearer, Content-Length,
application/json: `url`, optional `format`, `budget_ms`, `max_age_hours`,
`allow_browser`, `expected_text`. Invalid input: 400; product outcomes: 200,
even `ok:false` (empty content). CLI prints selected strings or JSON links/meta.
HTTP/network/schema/okfalse: nonzero rc, empty stdout, static JSON stderr; no redirects.
Trace `attempts`: provider/profile names, status/challenge, timing, decisions;
no proxy credentials/intermediate pages. Total budget includes shared browser-slot
waiting; HTTP/RSS/Wayback/health bypass slots. M10 owns policy.
Live JS/Docker assertions: `python3 tests/live_m11_api.py`.

## MCP server

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
        "ABG_TOKEN_FILE": "/home/you/.config/abg/client-token"
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

## M12a local service

Local Docker API + profile pool + health sidecar. Production/15-proxy is M12b.

```bash
docker build -t abg-runtime:m12a -f deploy/Dockerfile .
scripts/abg-release prepare --repo . --sha <40-char-sha> --root "$HOME/services/ai-browser-gateway"
# 0600 token, proxies.toml, ping file; values never in argv/env
export ABG_RELEASE="$HOME/services/ai-browser-gateway/releases/<40-char-sha>"
export ABG_TOKEN_FILE=... ABG_PROFILES_FILE=... ABG_PING_FILE=...
export ABG_INSTANCE=local-m12a ABG_RUNTIME_IMAGE=abg-runtime:m12a
export ABG_DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
docker compose -f deploy/compose.yaml -p ai-browser-gateway up -d
scripts/abg-fetch https://example.org text
docker compose -f deploy/compose.yaml -p ai-browser-gateway down
# rollback: ABG_RELEASE=.../releases/<older-sha> and up again
```

`GET /health` unauthenticated; `POST /v1/fetch` is M11 Bearer JSON.
Host publish `127.0.0.1:8765`. Live: `python3 tests/live_m12_service.py`.

SIGTERM closes provider admission immediately, drains already admitted Docker
calls, then performs the final owner/instance/role-scoped cleanup. Compose allows
260 seconds before SIGKILL to cover the existing 180-second request budget,
Docker launcher's 30-second timeout cleanup and final bounded sweeps. Normal
shutdown removes running providers while draining and finishes sooner.

## M12b deployed service

Stand-host runs release `db4fc359171c304470d7edae3d60cb13394e7881`
under `/home/user/services/ai-browser-gateway`, with the API published at
`127.0.0.1:8765`. Measured outcomes and image identity:
[M16c deployment results](research/04-phase1-verdict.md#после-выкладки-m16c).
Deployment and target checks passed. The executor's AC-954 run hit
`worker_internal_error`, a catch-all the harness reports for any worker failure
— including a gateway HTTP 500 — so that one request stays unexplained. The
coordinator reran the same egress-rotation check on this release and it passed;
the release was accepted with AC-954 open.
The [M12b report](research/07-deployed-service.md) retains the original
profile-pool and target measurements.

Start or stop the service using its explicit configuration:

```bash
service_root=/home/user/services/ai-browser-gateway
release_sha=db4fc359171c304470d7edae3d60cb13394e7881
env -u ABG_RELEASE -u ABG_RUNTIME_IMAGE docker compose --env-file "$service_root/compose.env" \
  -f "$service_root/releases/$release_sha/deploy/compose.yaml" \
  -p ai-browser-gateway up -d
env -u ABG_RELEASE -u ABG_RUNTIME_IMAGE docker compose --env-file "$service_root/compose.env" \
  -f "$service_root/releases/$release_sha/deploy/compose.yaml" \
  -p ai-browser-gateway stop
```

`compose.env` contains paths and non-secret settings. Private files are
`secrets/token`, `secrets/proxies.toml`, and the coordinator-managed
`secrets/hc-ping` (files `0600`, directory `0700`). Preserve these files across
releases. The monitor mounts only its ping file and release; API credentials
and Docker socket are absent. Production leaves `ABG_PROVIDER_NETWORK` unset.

The client reads `~/.config/abg/client-token`, a symlink to `secrets/token`:

```bash
scripts/abg-fetch https://example.com/ text
```

The retained rollback release is `ae72bfe1bae927a0297edfa273632df14ac89689`,
with image `abg-runtime:ae72bfe1bae9`. M16c preserves the earlier releases,
their manifests and images, and `compose.env.pre-m13c` /
`compose.env.pre-m14b` / `compose.env.pre-m15b` / `compose.env.pre-m16b`.
The configuration before M16c is saved as `compose.env.pre-m16c`
(mode `0600`, never overwritten). Restore that file byte for byte to roll back:

```bash
cp "$service_root/compose.env.pre-m16c" "$service_root/compose.env"
rollback_sha=ae72bfe1bae927a0297edfa273632df14ac89689
env -u ABG_RELEASE -u ABG_RUNTIME_IMAGE docker compose --env-file "$service_root/compose.env" \
  -f "$service_root/releases/$rollback_sha/deploy/compose.yaml" \
  -p ai-browser-gateway up -d
python3 tests/deployed_m12b.py --check-deploy --release "$rollback_sha" \
  --evidence /home/user/.cache/abg-coord-20260918/m16c-rollback
```

Clearing these two variables prevents earlier shell exports from overriding
`compose.env`. Keep the secret paths, project name and instance unchanged.
Prepare a release with host Python and Git, then build its runtime image:

```bash
python3 scripts/abg-release prepare --repo "$PWD" --sha "$release_sha" --root "$service_root"
docker build -t "abg-runtime:${release_sha:0:12}" \
  -f "$service_root/releases/$release_sha/deploy/Dockerfile" "$service_root/releases/$release_sha"
```

For M16c, run these checks sequentially from the clone, with no other API clients:

```bash
evidence=/home/user/.cache/abg-coord-20260918/m16c
python3 tests/deployed_m12b.py --check-deploy --release "$release_sha" --evidence "$evidence"
python3 tests/deployed_m12b.py --check-profiles --release "$release_sha" --evidence "$evidence"
python3 tests/deployed_m12b.py --check-api-egress --release "$release_sha" --evidence "$evidence"
python3 tests/deployed_m12b.py --check-bizprofile --release "$release_sha" --evidence "$evidence"
python3 tests/deployed_m12b.py --run-targets --release "$release_sha" --evidence "$evidence"
```

`--release` requires 40 lowercase hex characters; `--evidence` requires an
absolute path. Omitting them preserves the M12b defaults: release
`929bded313e371808b0747fd9a400696a36638aa` and evidence directory
`/home/user/.cache/abg-coord-20260917/m12b/`. The existing `--check-profiles`
and `--check-api-egress` modes accept the same options; run profiles first
when measuring rotation. Profile checks take at least eight minutes.

Network checks run inside Docker and write sanitized JSON. Bizprofile checks
request the homepage and Elevate Electric LLC card without `expected_text`,
then check their content markers locally. Both pages must succeed through
Scrapling with `challenge=none`. Each run preserves `bizprofile-<UTC>.json`
exclusively and updates `bizprofile.json`; failed pages are recorded without
retrying. Page content and URLs are omitted from this evidence. Requests to
the same hostname are spaced by at least 30 seconds across runner launches.

Run the API rotation and target checks with no other API clients. Refusals in
the six-target matrix are recorded as outcomes; Docker/API transport failures
fail the check. Healthchecks history and automatic failure/recovery verification
remain the coordinator's checks.

M16c deploys browser-parity normalization in the detector: NUL replacement,
ASCII-only class-token splitting, backslash handling in relative script URLs,
and linear-time edge trimming. AC-956 imports the deployed `probe.py` offline
and checks four fixtures plus a 32,000-space input against a two-second budget.
Provider images are preserved; `probe.py` is mounted from the release directory.
The single additional M16c request to `https://lowendtalk.com/` omits
`expected_text`; its full response is retained as `lowendtalk.json` in the
M16c evidence directory. Keep that measurement separate from the target matrix,
which supplies expected text, and do not repeat it during acceptance.

## One-shot image

Самодостаточный образ запускает лестницу `curl_cffi → patchright → scrapling`
локальными процессами. Развёрнутый API и Docker-демон внутри контейнера не нужны.
Внутри только direct: без прокси, входов RSS/Wayback, токенов и кэша.
Переменные окружения `http_proxy`, `https_proxy`, `all_proxy`, `ftp_proxy` и
`no_proxy` в любом регистре игнорируются: образ всегда ходит direct.

Сборка из корня репозитория и запуск:

```sh
docker build -f deploy/Dockerfile.oneshot -t abg-oneshot:m19 .
docker run --rm abg-oneshot:m19 https://example.org/ --format meta
```

CLI: `python3 -m gateway.oneshot URL [--format text|html|markdown|links|meta]
[--expected-text TEXT] [--budget-ms N] [--no-browser]`. По умолчанию формат
`text`, бюджет 30000 мс; `--no-browser` оставляет только HTTP-провайдер.
Для локального запуска нужны зависимости и probe из образа.

stdout содержит одну строку JSON с теми же полями, что `/v1/fetch`, включая
`content` и `attempts`. Коды возврата: `0` — `ok=true`; `1` — `ok=false`;
`2` — неверные аргументы; `3` — внутренняя ошибка; `4` — прерван сигналом
SIGTERM, SIGINT или SIGHUP во время прогона лестницы. При кодах `2`, `3` и `4`
stdout пуст, stderr содержит одну строку `{"error": "invalid_request"}`,
`{"error": "internal_error"}` или `{"error": "interrupted"}` соответственно.
При прерывании группы всех активных probe уничтожаются SIGKILL.
Образ работает от root и от UID 1002 без увеличения `/dev/shm`.
