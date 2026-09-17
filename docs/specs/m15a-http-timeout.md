# M15a — лимит HTTP-ступени и переход дальше при её таймауте

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `dc604c9141c5eabc1f7658f8180323f1d671cac8` — main после выкладки M14b (curl_cffi в лестнице, release `b31a36b` на stand-host).
Клон /home/user/exec-clones/abg-m15a-http-timeout-20260917, ветка m15a-http-timeout, origin push DISABLED. Исполнитель — cx
(директива владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать: выкладка — отдельная веха M15b. Push/merge запрещены. Продукт,
импорт и assertions — только Docker 1002:1002 с `--network none`; host —
git/файлы/оркестрация. Live-запросы запрещены.

## Задача

Решение владельца 17.09.2026 («Лимит + переход дальше»). Проблема замерена в
M14b: `cf-spa-chatgpt-share` — единственная попытка `curl_cffi/direct`
зависла, съела весь бюджет запроса 120 с и дала `timeout` → `retry_later`;
браузер не запускался (на повторе та же цель — `curl_cffi` 200 за 4,1 с).

В `gateway/product.py`:

1. Модульная константа `HTTP_STEP_BUDGET_MS = 15_000`. В `run_product` для
   ступеней с `purpose` `'http'` и `'egress'` фетчер получает
   `min(remaining, HTTP_STEP_BUDGET_MS)`; для `'entrance'` и `'browser'` —
   `remaining`, как сейчас. Проверка `remaining <= 0` и `late` (общий
   дедлайн запроса) не меняются.
2. Таймаут HTTP-ступени больше не терминальный, если дальше есть куда идти.
   Если `reason == F.timeout`, запрос не опоздал (`late` ложно), и ступень
   `'http'` — следующая ступень выбирается как для `http_403`/`content_missing`
   (первая дальше по плану с `purpose` в `('browser', 'egress')`, решение
   `Step.browser` или `Step.change_egress`); ступень `'egress'` — следующая
   `'egress'` (решение `Step.change_egress`). Если такой ступени нет —
   прежнее поведение: `F.timeout`, `Step.retry_later`. Прочие причины
   (`connection_error`, `dns_error`, `tls_error`, `http_5xx`, `provider_error`
   и т.д.), `late`-таймаут и таймаут entrance/browser — без изменений.

Frozen probe: в `tests/probe_m10_product.py` разрешена РОВНО одна правка в
`test_terminal_timeout_clears_body_and_keeps_original_url` — строка
`out = _run(_request(egress_profiles=("gold",)), fetcher)` заменяется на
`out = _run(_request(allow_browser=False), fetcher)` (такая же строка есть в `test_content_mismatch_gives_up_without_further_fetch` — её НЕ трогать; таймаут там должен оставаться
терминальным, а с egress-профилем он теперь ведёт к браузеру; смысл теста —
очистка тела и исходный URL — сохраняется). Координатор проверил прототипом
на копии: при описанной политике падает только этот тест из 125 frozen и ни
один из 532 unit. Других правок frozen probes нет.

Тесты (`tests/test_gateway_product.py`): лимит 15000 передаётся http и egress
ступеням и не передаётся entrance/browser; при `remaining` < 15000 передаётся
`remaining`; таймаут http → patchright (`next_step == Step.browser`), при
`allow_browser=False` и профилях → первый egress (`Step.change_egress`);
таймаут egress → следующий egress, у последнего → `retry_later`; таймаут
http без следующей ступени → `retry_later`; `connection_error` http остаётся
`retry_later`; опоздавший ответ (late) остаётся `timeout/retry_later`.
Документы: `docs/specs/m10-product-contract.md` не менять; в CHANGELOG/TASKS
не писать; в `docs/research/04-phase1-verdict.md` — короткий раздел
«Лимит HTTP-ступени (M15a)» с причиной и правилом.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: чтение `run_product`
(`gateway/product.py` 100–175): таймаут сейчас → `Step.retry_later` и выход;
`api_limit.limit_fetcher` ограничивает только браузерные ступени слотом.
Прототип политики на копии BASE: 532 unit OK, frozen — 1 падение (названный
тест). `ScriptedFetcher` в probe M10 записывает переданный budget; тест
`test_remaining_budget_shrinks_and_late_success_is_timeout` передаёт 100 и 89
(< 15000) — не затрагивается. Улики зависания: M14b `targets-initial.json`.
Предположение: 15 с хватает HTTP-ступени на обычных целях (замеры M14b:
0,85–4,1 с полного времени API).

## Разрешения

Правка `gateway/product.py` (константа и `run_product`), одна строка
`tests/probe_m10_product.py` (см. выше), `tests/test_gateway_product.py`,
раздел в `docs/research/04-phase1-verdict.md`. Commit в клоне.

## Не трогать

`plan_product`, `accept_page`, `bench/**`, остальной `gateway/**`, прочие
frozen probes и tests, deploy/**, scripts/**, контракт M10, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m15a-http-timeout.md`).

## Критерии приёмки

- **AC-841.** Unit и frozen probes зелёные:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-842.** Frozen probe M10 изменён ровно одной строкой:
  `bash -c 'diff <(git show dc604c9141c5eabc1f7658f8180323f1d671cac8:tests/probe_m10_product.py) tests/probe_m10_product.py > /tmp/m15a-probe.diff; test "$(grep -c "^[<>]" /tmp/m15a-probe.diff)" = 2 && grep -qxF "<         out = _run(_request(egress_profiles=(\"gold\",)), fetcher)" /tmp/m15a-probe.diff && grep -qxF ">         out = _run(_request(allow_browser=False), fetcher)" /tmp/m15a-probe.diff && git diff --exit-code dc604c9141c5eabc1f7658f8180323f1d671cac8 HEAD -- tests/probe_m9_transport.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/probe_m13_late_container.py'`
- **AC-843.** Зависшая HTTP-ступень ограничена 15 с и ведёт в браузер:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import json; from gateway.product import ProductRequest, run_product, HTTP_STEP_BUDGET_MS; from gateway.models import ProviderReply; from bench.models import FetchResult, FailureReason as F, ChallengeType as C; from bench.escalate import Step; assert HTTP_STEP_BUDGET_MS == 15000; page=lambda p, e, s=None, t=\"\": FetchResult(provider=p, provider_version=\"t\", requested_url=\"https://a.test\", final_url=\"https://a.test\", status=s, html=t, text=t, elapsed_ms=1, startup_ms=0, cpu_ms=0, peak_rss_mb=0.0, bytes_received=0, redirects=0, error_type=e, challenge=C.none); now=[0]; calls=[]; script={\"curl_cffi\": page(\"curl_cffi\", F.timeout), \"patchright\": page(\"patchright\", F.none, 200, \"real\")}; f=lambda step, budget: (calls.append((step.provider, step.egress_profile, budget)), now.__setitem__(0, now[0] + (15000 if step.provider == \"curl_cffi\" else 1000)), ProviderReply(script[step.provider]))[-1]; out=run_product(ProductRequest(\"https://a.test\", budget_ms=120000), f, clock=lambda: now[0]); assert calls == [(\"curl_cffi\", \"direct\", 15000), (\"patchright\", \"direct\", 105000)], calls; assert out.ok and out.provider == \"patchright\" and out.attempts[0].next_step == Step.browser, out"'`
- **AC-844.** Прочие места не изменены:
  `bash -c 'git diff --exit-code dc604c9141c5eabc1f7658f8180323f1d671cac8 HEAD -- bench deploy scripts gateway/api_limit.py gateway/fetch.py gateway/service.py gateway/api_http.py && diff <(git show dc604c9141c5eabc1f7658f8180323f1d671cac8:gateway/product.py | sed -n "/^def plan_product/,/^def _clock_ms/p") <(sed -n "/^def plan_product/,/^def _clock_ms/p" gateway/product.py) && diff <(git show dc604c9141c5eabc1f7658f8180323f1d671cac8:gateway/product.py | sed -n "/^def accept_page/,/^def plan_product/p") <(sed -n "/^def accept_page/,/^def plan_product/p" gateway/product.py)'`
- **AC-845.** Research дополнен:
  `bash -c 'grep -q "Лимит HTTP-ступени (M15a)" docs/research/04-phase1-verdict.md'`
- **AC-846.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code dc604c9141c5eabc1f7658f8180323f1d671cac8 HEAD -- . ":(exclude)gateway/product.py" ":(exclude)tests/probe_m10_product.py" ":(exclude)tests/test_gateway_product.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m15a-http-timeout.md"'`
- **AC-847.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m15a-http-timeout.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base dc604c9141c5eabc1f7658f8180323f1d671cac8 --range dc604c9141c5eabc1f7658f8180323f1d671cac8..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-841…AC-847,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"dc604c9141c5eabc1f7658f8180323f1d671cac8","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-841","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m15a-http-timeout-20260917 --spec /home/user/exec-clones/abg-m15a-http-timeout-20260917/docs/specs/m15a-http-timeout.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: политика ломает frozen
probe сверх названной строки (имя теста и assertion); нужна правка вне
`run_product`/константы; AC-843 не проходит без изменения описанного
правила. Спеку, AC, BASE и оснастку не менять, rc не выдумывать.
