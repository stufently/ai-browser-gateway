# M14a — curl_cffi вместо curl на HTTP- и egress-ступенях лестницы продукта

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `82ab3e791deb168137d4b83fc7c2fcf3af66eb3b` — main после принятой и выкачанной M13.
Клон /home/user/exec-clones/abg-m14a-curl-cffi-20260917, ветка m14a-curl-cffi, origin push DISABLED. Исполнитель — cx
(директива владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать: выкладка — отдельная веха M14b. Push/merge запрещены. Продукт,
импорт и assertions — только Docker 1002:1002; host — git/файлы/оркестрация.
Провайдерские образы не пересобирать.

## Задача

Решение владельца 17.09.2026 на вопрос «усиливаем дешёвую HTTP-ступень?» —
«Сразу curl_cffi в лестницу». Это пересматривает вывод фазы 1
(`docs/research/04-phase1-verdict.md`: curl_cffi исключён, incremental 0 на 5
целях) решением владельца, а не новым замером.

В `gateway/product.py`, `plan_product`: провайдер `'curl'` на ступени
`PlanStep(..., 'direct', 'http')` и на ВСЕХ ступенях `'egress'` заменить на
`'curl_cffi'`. Порядок, виды ступеней, entrance (`rss`, `wayback`) и браузеры
(`patchright`, `scrapling`) не менять. Провайдер уже описан в
`bench/providers/registry.py` (`abg-curl_cffi:m2`, kind `http`), адаптер
`CurlCffiAdapter` в `bench/providers/docker/probe.py` (impersonate `chrome`,
прокси через `_proxy_url`). `gateway/plan.py` (старый движок M7) НЕ менять.

Контракт frozen probes меняется ТОЛЬКО в ожидаемом имени провайдера лестницы:
в `tests/probe_m10_product.py`, `tests/probe_m11_api_cli.py`,
`tests/probe_m12_service.py`, `tests/probe_m12_service_regressions.py`
разрешено заменить строковый литерал имени провайдера `curl` на `curl_cffi`
там, где он означает ступень лестницы продукта (ожидаемые `PlanStep`,
последовательности вызовов фабрики, `provider` в ожидаемых attempts/ответах).
Никаких других правок probes: ни логики, ни порогов, ни новых тестов. Тесты
транспорта, где `curl` — просто провайдер для `fetch_content`/`build_argv`
(например `tests/probe_m9_transport.py`, `by_name("curl")`), НЕ трогать.
Обратная подстановка `curl_cffi` → `curl` должна давать BASE байт-в-байт
(AC-862). Нефроузен тесты (`tests/test_gateway_product.py` и т.п.) обновить
так же по смыслу; новые тесты — на то, что при `allow_browser=False` и
профилях egress лестница `curl_cffi` direct → `curl_cffi` по профилям, и что
`curl` в плане продукта больше не встречается.

Документы: в `docs/research/04-phase1-verdict.md` в конец — короткий раздел
«Пересмотр 17.09.2026»: решение владельца, что изменено, и живой замер
координатора ниже; CHANGELOG/TASKS не трогать.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: `curl_cffi` 0.16.3 — последняя версия на
PyPI; образ `abg-curl_cffi:m2` есть на stand-host. Запуск образа с текущим
`probe.py` (bind, `--content-only`): example.com — 200, `challenge=none`,
106 мс; lowendtalk.com/categories/offers — 200, настоящая страница
«Offers — LowEndTalk», 271 мс, но детектор даёт `captcha`
(`body_captcha`, `body_cf_challenge_platform`), поэтому продукт по-прежнему
уйдёт в браузер — детектор в этой вехе НЕ менять, записать в research;
bizprofile.net — 403 `Just a moment...`. В frozen probes BASE строка
`curl_cffi` не встречается (проверено grep). Ссылки на `'curl'` в плане:
`gateway/product.py` строки 91 и 94.

Предположение: probes M11/M12 зависят от имени провайдера лестницы только
литералами; если зависимость глубже (логика, а не литерал) — blocker.

## Разрешения

Правка `gateway/product.py` (только `plan_product`), литералы имени провайдера
в перечисленных frozen probes, нефроузен тесты в `tests/`, раздел в
`docs/research/04-phase1-verdict.md`. Live-запросы не нужны и запрещены.
Commit в клоне.

## Не трогать

`bench/**` (registry, probe.py, Dockerfile), `gateway/plan.py`, детектор,
policy `accept_page`, остальной `gateway/**`, `tests/probe_m9_transport.py`,
`tests/probe_m13_late_container.py`, `tests/deployed_m12b.py`,
`tests/test_deployed_m12b.py`, deploy/**, scripts/**, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m14a-curl-cffi-ladder.md`).

## Критерии приёмки

- **AC-861.** Unit и frozen probes зелёные:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-862.** Frozen probes изменены только заменой имени провайдера:
  `bash -c 'for f in tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py; do diff <(git show 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b:$f) <(sed s/curl_cffi/curl/g $f) >/dev/null || exit 1; done && git diff --exit-code 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b HEAD -- tests/probe_m9_transport.py tests/probe_m13_late_container.py tests/deployed_m12b.py tests/test_deployed_m12b.py && git grep -q curl_cffi -- tests/probe_m10_product.py'`
- **AC-863.** План продукта использует curl_cffi и не использует curl:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "from gateway.product import ProductRequest, plan_product; s=plan_product(ProductRequest(url=\"https://a.test\", allow_browser=True, max_age_hours=1, egress_profiles=(\"p\",\"q\"))); n=[(x.provider, x.egress_profile, x.purpose) for x in s]; assert n==[(\"rss\",\"direct\",\"entrance\"),(\"wayback\",\"direct\",\"entrance\"),(\"curl_cffi\",\"direct\",\"http\"),(\"patchright\",\"direct\",\"browser\"),(\"scrapling\",\"direct\",\"browser\"),(\"curl_cffi\",\"p\",\"egress\"),(\"curl_cffi\",\"q\",\"egress\")], n"'`
- **AC-864.** Код вне плана не изменён:
  `bash -c 'git diff --exit-code 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b HEAD -- bench gateway/plan.py deploy scripts && test "$(git diff 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b HEAD -- gateway | grep -c "^[-+][^-+]")" -le 4'`
- **AC-865.** Research дополнен:
  `bash -c 'grep -q "Пересмотр 17.09.2026" docs/research/04-phase1-verdict.md && grep -q curl_cffi docs/research/04-phase1-verdict.md'`
- **AC-866.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b HEAD -- . ":(exclude)gateway/product.py" ":(exclude)tests" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m14a-curl-cffi-ladder.md"'`
- **AC-867.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m14a-curl-cffi-ladder.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b --range 82ab3e791deb168137d4b83fc7c2fcf3af66eb3b..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-861…AC-867,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"82ab3e791deb168137d4b83fc7c2fcf3af66eb3b","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-861","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m14a-curl-cffi-20260917 --spec /home/user/exec-clones/abg-m14a-curl-cffi-20260917/docs/specs/m14a-curl-cffi-ladder.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: frozen probe требует
правки сверх замены литерала имени провайдера (имя теста и строка);
`curl_cffi` не проходит через транспорт/фабрику без правки `bench/**` или
`gateway/**` вне `plan_product`; ломается детектор или policy. Спеку, AC, BASE
и оснастку не менять, rc не выдумывать, чужое не трогать.
