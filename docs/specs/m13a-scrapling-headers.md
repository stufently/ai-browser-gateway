# M13a — устаревший cf-mitigated в ответе Scrapling

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `693400423b00eac6dd367c7fa54b64e9a20b94aa`. Клон /home/user/exec-clones/abg-m13a-scrapling-20260917,
ветка m13a-scrapling, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца», тест bizprofile.net через
продукт).

Работающий сервис `ai-browser-gateway` (127.0.0.1:8765) и
`/home/user/services/**` НЕ трогать: выкладка — отдельная веха. Push/merge
запрещены. Продукт, импорт и assertions — только Docker 1002:1002; host —
git/файлы/оркестрация. Провайдерские образы не пересобирать: probe.py
монтируется в них из дерева. Секреты не нужны.

## Задача

Владелец хочет, чтобы https://bizprofile.net/ (Cloudflare) отдавался продуктом
БЕЗ `expected_text`. Сейчас через deployed API: curl 403, patchright 403,
scrapling 200 с настоящей страницей, но `challenge=suspected` →
`challenge_suspected` → ступень egress (403) → `ok:false`. С `expected_text`
тот же запрос даёт `ok:true` (главная, каталог `/ny/albany`, карточка
`/ny/albany/elevate-electric-llc` — 21–24 с).

Корень найден координатором в образе `abg-scrapling:m8`:
`StealthySession.fetch(..., solve_cloudflare=True)` на карточке вернул
`status=200`, настоящее тело (title «Elevate Electric LLC Albany, NY - filing
information») и `history` с одним 307, но `response.headers` — заголовки
challenge-ответа, в том числе `cf-mitigated: challenge`.
`detect_challenge(200, headers, body)` → `('suspected', ('header_cf_mitigated',
'body_cf_challenge_platform'))`; `detect_challenge(200, None, body)` →
`('none', ('body_cf_challenge_platform',))`. Тело настоящей страницы содержит
только скрипт `/cdn-cgi/challenge-platform/scripts/jsd/main.js`.

Исправить в `ScraplingAdapter.navigate` (`bench/providers/docker/probe.py`):
если Scrapling вернул 2xx и само тело НЕ является interstitial
(`detect_challenge(status, None, body)` не `suspected`/`interactive`), то
заголовок `cf-mitigated` в переданных дальше headers устаревший и не
передаётся (остальные заголовки сохранить; `None` и `{}` не смешивать).
Настоящий challenge (не-2xx, или тело-interstitial) по-прежнему даёт тот же
вердикт, что сейчас. `detect_challenge`, его правила и
`tests/test_detect.py` (в т.ч. `test_cf_mitigated_header_outranks_clean_body`)
НЕ менять: заголовок остаётся решающим для прочих провайдеров. Policy
`gateway/product.py` (`accept_page`) не менять.

Тесты:
- `tests/test_probe.py` (`ScraplingAdapterTests`, фейковый `scrapling.fetchers`):
  2xx + чистое тело + `cf-mitigated` → headers без `cf-mitigated`, прочие
  заголовки на месте; 403 + тот же заголовок → заголовок сохранён; 200 +
  interstitial-тело (фикстура `tests/fixtures/cf_interstitial_200body_403.html`)
  + заголовок → сохранён; `headers=None` остаётся `None`. Проверять итоговый
  `challenge` через тот же путь, что CLI probe (не только словарь).
- `tests/live_m13a_bizprofile.py` (по образцу `tests/live_m10_product.py`:
  host-оркестрация, продукт в Docker с socket только у оркестратора, провайдеры
  через существующие образы и `DockerLauncher`, probe.py из дерева клона):
  лестница продукта без `expected_text`, budget 120000, browser разрешён, без
  egress-профилей, для `https://bizprofile.net/` и
  `https://www.bizprofile.net/ny/albany/elevate-electric-llc` с паузой ≥30 с;
  ожидается `ok:true`, provider `scrapling`, у успешной попытки
  `challenge=none`, контент содержит соответственно «Comprehensive Directory
  of Registered Businesses» и «Elevate Electric LLC». Печатает JSON-итог без
  тела страниц. Внешний отказ (403 у scrapling, таймаут) — rc≠0 с классом
  отказа, без ретраев.

Документ `docs/research/08-bizprofile-scrapling.md`: замер координатора до
правки (таблица выше: лестница, тайминги, роль `expected_text`), корень с
вердиктами детектора, результат после правки из live. Без cookie/заголовков
целиком и без тел страниц.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 04:55–05:10 UTC: три запроса через deployed
API (главная, `/ny/albany`, карточка) с `expected_text` — `ok:true`, scrapling
16.6–17.7 с на попытку; без `expected_text` главная — `ok:false` (curl 403,
patchright 403, scrapling 200 suspected, curl ms6 403). Прямой запуск
`ScraplingAdapter` в `abg-scrapling:m8` (entrypoint `tini -g -- xvfb-run …`,
`--shm-size=1g`, user 1002) — заголовки и вердикты выше.
Предположение: поведение Scrapling стабильно между запусками; Cloudflare сайта
может сменить режим — тогда live честно упадёт с классом отказа.

## Разрешения

Правка `bench/providers/docker/probe.py` (только `ScraplingAdapter` и при
необходимости маленький helper рядом), `tests/test_probe.py`, новые
`tests/live_m13a_bizprofile.py`, `docs/research/08-bizprofile-scrapling.md`.
Реальные запросы к bizprofile.net: не больше 6 за прогон live, пауза ≥30 с.

## Не трогать

`detect_challenge` и его правила, gateway/**, остальной bench/**, deploy/**,
scripts/**, остальные tests и frozen probes, контракты, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`, провайдерские образы. Сначала
закоммитить эту спеку byte-identical (`docs/specs/m13a-scrapling-headers.md`).

## Критерии приёмки

- **AC-901.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-902.** Frozen probes зелёные и неизменны:
  `bash -c 'git diff --exit-code 693400423b00eac6dd367c7fa54b64e9a20b94aa HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-903.** Live: bizprofile без expected_text через лестницу продукта:
  `bash -c 'python3 tests/live_m13a_bizprofile.py'`
- **AC-904.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 693400423b00eac6dd367c7fa54b64e9a20b94aa HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/live_m13a_bizprofile.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)docs/specs/m13a-scrapling-headers.md"'`
- **AC-905.** Чистое дерево, файлы в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-scrapling-headers.md tests/live_m13a_bizprofile.py docs/research/08-bizprofile-scrapling.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 693400423b00eac6dd367c7fa54b64e9a20b94aa --range 693400423b00eac6dd367c7fa54b64e9a20b94aa..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-901…AC-905,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"693400423b00eac6dd367c7fa54b64e9a20b94aa","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-901","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-scrapling-20260917 --spec /home/user/exec-clones/abg-m13a-scrapling-20260917/docs/specs/m13a-scrapling-headers.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: после правки Scrapling на
bizprofile всё равно не проходит (записать класс отказа и вердикт детектора без
тела); исправление требует менять `detect_challenge`, policy продукта или
frozen probes; нужен рестарт сервиса или пересборка образов. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
