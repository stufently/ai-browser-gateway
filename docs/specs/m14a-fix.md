# M14a-fix — таймаут curl_cffi и live-проверки после смены провайдера

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `7e49529513444d7d140d69c61ed2adc1a0907fe6` — FINAL M14a (curl_cffi в лестнице).
Клон /home/user/exec-clones/abg-m14a-fix-20260917, ветка m14a-fix, origin push DISABLED. Исполнитель — cx
(директива владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002 с `--network none`; host — git/файлы/оркестрация. Провайдерские
образы не пересобирать (сервис монтирует `probe.py` из release,
`bench/runner/fetch.py`, `probe_bind`). Live-запросы запрещены.

## Задача

Codex result review M14a нашёл, координатор подтвердил:

1. **Таймаут curl_cffi классифицируется как `provider_error`.** В образе
   `abg-curl_cffi:m2` MRO `curl_cffi.requests.exceptions.Timeout` —
   `Timeout → RequestException → CurlError → OSError`, не `TimeoutError`.
   Классификатор исключений `run_probe` (`bench/providers/docker/probe.py`,
   блок `except Exception` около строки 932) распознаёт только
   `TimeoutError`/`TimeoutExpired`, поэтому `err` = `"Timeout: …"` →
   `bench/runner/fetch.py` даёт `provider_error` → продукт `investigate`
   (у системного `curl` rc=28 даёт `timeout` → `retry_later`), а deployed
   runner считает `provider_error` инфраструктурной ошибкой.
   Исправить в `CurlCffiAdapter.navigate`: исключение, чей класс по MRO
   называется `Timeout` из `curl_cffi.requests.exceptions` (импорт внутри
   `navigate`, как сейчас), перевыбрасывать как `TimeoutError` (`raise
   TimeoutError(...) from exc`, текст без URL прокси/кредов). Прочие ошибки
   curl_cffi не менять (паритет с `CurlAdapter`, где они тоже
   `provider_error`).
2. **Live-проверки ждут `curl`.** `tests/live_m10_product.py` (строки
   100–104), `tests/live_m11_api.py:75`, `tests/live_m13a_bizprofile.py:74`
   ожидают `curl` как ступень лестницы продукта. Заменить только этот литерал
   на `curl_cffi` (обратная подстановка даёт BASE байт-в-байт). Прочие
   `tests/live_*.py` проверить grep'ом и поступить так же, если литерал
   означает ступень лестницы продукта; транспортные использования `curl` не
   трогать.

Тесты в `tests/test_probe.py` (стиль существующих тестов с поддельным модулем
`curl_cffi` около строк 314 и 664): поддельный `Timeout(RequestException(OSError))`
из `navigate` → payload `err == "timeout"`; поддельный `ConnectionError`
того же семейства → `err` не `timeout` (как раньше); реальный `TimeoutError`
по-прежнему `timeout`. Тест падает на BASE по причине.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: MRO исключений в `abg-curl_cffi:m2`
(команда `docker run --entrypoint python3 abg-curl_cffi:m2 -c …`):
`Timeout`, `ConnectionError`, `SSLError`, `DNSError`, `ProxyError` — все от
`RequestException → CurlError → OSError`. Сопоставление `err` →
`FailureReason` — `bench/runner/fetch.py` строки 95–100; политика шагов —
`gateway/product.py` строки 146–149. Live-тесты с `curl` — grep.

## Разрешения

Правка `bench/providers/docker/probe.py` (только `CurlCffiAdapter`),
`tests/test_probe.py`, литералы в `tests/live_*.py`. Commit в клоне.

## Не трогать

`gateway/**`, `bench/runner/**`, registry, Dockerfile, детектор, остальные
адаптеры, frozen probes, `tests/mutation_gate_scrapling.py`,
`tests/deployed_m12b.py`, deploy/**, scripts/**, docs, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m14a-fix.md`).

## Критерии приёмки

- **AC-851.** Unit и frozen probes зелёные:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-852.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-853.** Таймаут curl_cffi даёт err timeout:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_probe 2>&1 | tail -1 | grep -q OK && git diff 7e49529513444d7d140d69c61ed2adc1a0907fe6 HEAD -- tests/test_probe.py | grep -q "Timeout"'`
- **AC-854.** Live-тесты изменены только заменой имени провайдера:
  `bash -c 'for f in $(git diff --name-only 7e49529513444d7d140d69c61ed2adc1a0907fe6 HEAD -- "tests/live_*.py"); do diff <(git show 7e49529513444d7d140d69c61ed2adc1a0907fe6:$f) <(sed s/curl_cffi/curl/g $f) >/dev/null || exit 1; done && ! grep -nE "\[.curl.[],]" tests/live_m10_product.py tests/live_m11_api.py tests/live_m13a_bizprofile.py'`
- **AC-855.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 7e49529513444d7d140d69c61ed2adc1a0907fe6 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/live_*.py" ":(exclude)docs/specs/m14a-fix.md" && test "$(git diff 7e49529513444d7d140d69c61ed2adc1a0907fe6 HEAD -- bench/providers/docker/probe.py | grep -c "^[-+][^-+]")" -le 12'`
- **AC-856.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m14a-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 7e49529513444d7d140d69c61ed2adc1a0907fe6 --range 7e49529513444d7d140d69c61ed2adc1a0907fe6..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-851…AC-856,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"7e49529513444d7d140d69c61ed2adc1a0907fe6","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-851","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m14a-fix-20260917 --spec /home/user/exec-clones/abg-m14a-fix-20260917/docs/specs/m14a-fix.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: исправление требует правки
вне `CurlCffiAdapter`/общего классификатора ошибок probe; ломается mutation
gate M8 или frozen probe; live-тест требует правки логики, а не имени
провайдера. Спеку, AC, BASE и оснастку не менять, rc не выдумывать.
