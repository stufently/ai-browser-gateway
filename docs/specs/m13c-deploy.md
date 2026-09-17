# M13c — выкладка M13a/M13b на stand-host и живой bizprofile без expected_text

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `4409f8a5197f7a9f464263e15b362c00548399e2` — main после слияния принятых M13a-fix5 (Scrapling:
устаревший `cf-mitigated`) и M13b-fix5 (уборка позднего Docker-контейнера) плюс запись CHANGELOG.
Клон /home/user/exec-clones/abg-m13c-deploy-20260917, ветка m13c-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026:
«доделывай все до конца кодексом»). Образец предыдущей выкладки —
`docs/specs/m12b-deploy.md` и раздел README «M12b deployed service»
(прочитать оба целиком).

Это обновление production-сервиса на ЭТОМ хосте в каталоге
`/home/user/services/ai-browser-gateway/`. Сейчас там работает release
`929bded313e371808b0747fd9a400696a36638aa` (образ `abg-runtime:929bded313e3`),
Compose-проект `ai-browser-gateway`, API на `127.0.0.1:8765`. Разрешено
менять только: `releases/4409f8a5197f7a9f464263e15b362c00548399e2/` и `manifests/4409f8a5197f7a9f464263e15b362c00548399e2.sha256` (создаёт
`abg-release prepare`), ключи `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` в
`compose.env` (и его копию `compose.env.pre-m13c`, см. пункт 4), свой образ `abg-runtime:<первые 12 символов 4409f8a5197f7a9f464263e15b362c00548399e2>`, свой
Compose-проект и файлы клона. `releases/929bded…`, его manifest и образ
`abg-runtime:929bded313e3` НЕ удалять и не менять: это откат. Каталог
`secrets/` не читать, не менять, не пересоздавать. Чужие сервисы,
compose-проекты, контейнеры, сети и `.env` не трогать и не читать.
Push/merge в репозиторий запрещены: работу заберёт координатор.

## Задача

1. **Runner без зашитого релиза.** `tests/deployed_m12b.py` получает два
   необязательных аргумента: `--release <40 hex>` (по умолчанию
   `929bded313e371808b0747fd9a400696a36638aa`, чтобы команды спеки M12b
   остались валидными) и `--evidence <абсолютный путь>` (по умолчанию
   `/home/user/.cache/abg-coord-20260917/m12b`). От них выводятся все
   прежние константы: каталог release, manifest, `ABG_RELEASE` и
   `ABG_RUNTIME_IMAGE = abg-runtime:<sha[:12]>` в сверке `compose.env`,
   `WorkingDir` и монтирование release в контейнерах, `release_sha` в уликах,
   путь улик, `request-times.json` и `runner.lock`. Невалидный sha (не 40
   символов `[0-9a-f]`) или относительный путь улик — ошибка разбора
   аргументов через `parser.error` (rc 2, сообщение называет `--release` или
   `--evidence`) до любых Docker/HTTP действий и записей на диск. Зашитых
   `929bded` в логике проверок не остаётся (только значение по умолчанию).
2. **Новый режим `--check-bizprofile`.** Два запроса через deployed API,
   строго последовательно, между ними ≥30 с (существующий `wait_gap`):
   `https://bizprofile.net/` и
   `https://bizprofile.net/ny/albany/elevate-electric-llc`. Тело запроса:
   `allow_browser=true`, `budget_ms=120000`, `format=text`,
   `max_age_hours=0`, ключа `expected_text` НЕТ (не `null`, а отсутствует).
   Внутри одного запуска режима повторов нет; каждый запуск — отдельное
   измерение: runner пишет и `bizprofile.json` (последний запуск), и
   неперезаписываемую копию `bizprofile-<UTC YYYYMMDDTHHMMSSZ>.json`
   (`O_EXCL`), так что перезапуск AC приёмщиком не стирает прежние улики.
   Ответ проходит `parse_api`. Проверка пройдена, только если для каждой
   страницы: `ok` истинно, `provider == "scrapling"`, последний attempt —
   `provider "scrapling"`, `success true`, `challenge "none"`,
   `error_type "none"`; `content` содержит маркер страницы (главная —
   `Comprehensive Directory of Registered Businesses`, карточка —
   `Elevate Electric LLC`). Маркер проверяет runner у себя, в API он не
   уходит. Улики `bizprofile.json` в каталоге улик: по странице —
   `api_evidence`, `marker_found`, без content и URL. Любое несоответствие —
   rc≠0 с кодом `bizprofile_not_passed` ПОСЛЕ записи улик обеих страниц
   (вторую страницу запрашивать и при провале первой). Повторов нет.
   Существующие проверки не ослаблять.
3. **Unit-тесты** в `tests/test_deployed_m12b.py` (фейковые Docker/HTTP, без
   сети и секретов), закоммичены ДО production-действий:
   - разбор `--release`/`--evidence`: значения по умолчанию, свой sha
     меняет release/manifest/образ/ожидаемый `compose.env`, отказ на
     короткий/заглавный/не-hex sha и на относительный путь без побочных
     действий;
   - `check_bizprofile`: тело запроса без ключа `expected_text`; порядок URL
     и пауза между ними; зелёный случай; по отдельности провал на
     `ok false`, другом provider, `challenge` ≠ none в последнем attempt,
     `success false`, отсутствии маркера — и в каждом провале улики обеих
     страниц записаны; улики без content и URL.
4. **Выкладка.** Ровно процедура README (хостовый python3 для
   `abg-release prepare --repo <клон> --sha 4409f8a5197f7a9f464263e15b362c00548399e2 --root
   /home/user/services/ai-browser-gateway`, `docker build` из
   `releases/4409f8a5197f7a9f464263e15b362c00548399e2/deploy/Dockerfile`). Затем в `compose.env` поменять
   только `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` (остальные строки
   байт-в-байт), предварительно сохранив исходный файл копией
   `compose.env.pre-m13c` (0600, не перезаписывать, если уже есть), и
   `env -u ABG_RELEASE -u ABG_RUNTIME_IMAGE docker compose --env-file /home/user/services/ai-browser-gateway/compose.env -f /home/user/services/ai-browser-gateway/releases/4409f8a5197f7a9f464263e15b362c00548399e2/deploy/compose.yaml -p ai-browser-gateway up -d`.
   ДО `up`: убедиться, что проект `ai-browser-gateway` — это текущий
   `929bded…` (`docker compose ls -a`, label `com.docker.compose.project`);
   иначе blocker. Если `up` завершился ошибкой ИЛИ после `up` AC-893 падает
   по причине сервиса, откатить
   на `929bded…` той же командой README (вернуть `compose.env` из
   `compose.env.pre-m13c` байт-в-байт, `-f` на старый release), убедиться `--check-deploy --release 929bded…` зелёный и
   остановиться с `report-blocked.md`. Если и откат не поднимает сервис —
   остановиться немедленно, ничего больше не менять, в `report-blocked.md`
   вывод `docker compose ps -a` и безопасные коды ошибок.
5. **Документы.** `docs/research/08-bizprofile-scrapling.md` — раздел
   «После выкладки M13c»: release sha, image ID, таблица двух страниц
   (provider, попытки лестницы, challenge, elapsed) из улик, без секретов,
   с именем файла `bizprofile-<UTC>.json`, из которого взята таблица.
   README: раздел «M12b deployed service» обновить на актуальный release,
   откат на `929bded…` описан, в списке проверок — `--release`/`--evidence`
   и `--check-bizprofile`.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: сервис работает на `929bded…`,
`compose.env` содержит 9 ключей из `check_deploy`; API принимает запрос без
`expected_text` (`gateway/api_http.py`, `ProductRequest.expected_text=None`).
До M13a главная bizprofile без `expected_text` давала `ok:false` (scrapling
200 → suspected из-за `cf-mitigated`); на клонах M13a-fix…fix4 live-критерий
без `expected_text` проходил (≈75 с на обе страницы через фабрику продукта,
не через deployed API). Предположение: через deployed API с ротацией
профилей результат тот же, а Cloudflare не ужесточил проверку.

## Разрешения

Всё из «Задачи». Реальные внешние запросы: две страницы bizprofile через API
(AC-894), шесть целей и CLI `--run-targets` (AC-895); ≥30 с между запросами к
одному hostname. Docker build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, остальные tests и frozen probes,
контракт, другие specs, TASKS.md, CHANGELOG.md; `secrets/**`; чужие сервисы и
их файлы; `~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не
менять policy/budget, не ретраить цель ради зелёного исхода. Сначала
закоммитить эту спеку byte-identical (`docs/specs/m13c-deploy.md`).

## Критерии приёмки

- **AC-891.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-892.** Параметры разобраны runner, невалидный sha отвергнут до записи на диск:
  `bash -c 'test "$(grep -c 929bded313e371808b0747fd9a400696a36638aa tests/deployed_m12b.py)" = 1 && h="$(python3 tests/deployed_m12b.py --help)" && grep -q -- --release <<<"$h" && grep -q -- --evidence <<<"$h" && grep -q -- --check-bizprofile <<<"$h" && e="$(python3 tests/deployed_m12b.py --check-deploy --release ABC --evidence /home/user/.cache/abg-coord-20260917/m13c-argcheck 2>&1)"; test $? -eq 2 && ! grep -q unrecognized <<<"$e" && grep -q -- --release <<<"$e" && test ! -e /home/user/.cache/abg-coord-20260917/m13c-argcheck'`
- **AC-893.** Сервис развёрнут на новом release, откат цел (старый release сверен с manifest, manifest и образ те же):
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy --release 4409f8a5197f7a9f464263e15b362c00548399e2 --evidence /home/user/.cache/abg-coord-20260917/m13c && echo "f76ec85184f67bd27c4feb8b907e0c75ff995bb89b1a4971482300a3866055bd  /home/user/services/ai-browser-gateway/manifests/929bded313e371808b0747fd9a400696a36638aa.sha256" | sha256sum -c --quiet - && python3 -c "import sys; sys.path.insert(0, \"tests\"); import deployed_m12b as d; from pathlib import Path; r=\"/home/user/services/ai-browser-gateway\"; s=\"929bded313e371808b0747fd9a400696a36638aa\"; d.verify_release(Path(r, \"releases\", s), Path(r, \"manifests\", s + \".sha256\"))" && test "$(docker image inspect abg-runtime:929bded313e3 --format "{{.Id}}")" = sha256:b56b99cb0232452d3d1a6f315029fd7f1ae4131e379a8d48bbcf537350f08930 && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m13c'`
- **AC-894.** Bizprofile без expected_text проходит через deployed API:
  `bash -c 'python3 tests/deployed_m12b.py --check-bizprofile --release 4409f8a5197f7a9f464263e15b362c00548399e2 --evidence /home/user/.cache/abg-coord-20260917/m13c'`
- **AC-895.** Шесть целей и CLI на новом release, внешний отказ — записанный
  исход:
  `bash -c 'python3 tests/deployed_m12b.py --run-targets --release 4409f8a5197f7a9f464263e15b362c00548399e2 --evidence /home/user/.cache/abg-coord-20260917/m13c'`
- **AC-896.** Документы есть, без userinfo-URL:
  `bash -c 'grep -q "После выкладки M13c" docs/research/08-bizprofile-scrapling.md && grep -q 4409f8a5197f7a9f464263e15b362c00548399e2 README.md && grep -q -- --check-bizprofile README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-897.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 4409f8a5197f7a9f464263e15b362c00548399e2 HEAD -- . ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)README.md" ":(exclude)docs/specs/m13c-deploy.md"'`
- **AC-898.** Чистое дерево:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13c-deploy.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Через API healthchecks: у чека `ai-browser-gateway-health` success-пинги с
интервалом ≈60 с после перезапуска, без ручного ping. Мутации новых тестов
runner гоняет отдельная панель.

## Авторевью

Политика cross-review-v1, как в M12b: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 4409f8a5197f7a9f464263e15b362c00548399e2 --range 4409f8a5197f7a9f464263e15b362c00548399e2..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE,
затем verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 8 записей AC-891…AC-898,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"4409f8a5197f7a9f464263e15b362c00548399e2","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-891","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13c-deploy-20260917 --spec /home/user/exec-clones/abg-m13c-deploy-20260917/docs/specs/m13c-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным на новом release (или на `929bded…`
после отката по пункту 4).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
проект/порт заняты не нашим `929bded…`; для выкладки нужна правка
gateway/scripts/deploy/secrets; `docker build` падает (сервис не тронут);
`up` падает или AC-893 падает после `up` (сначала откат по пункту 4). Если AC-894 даёт честный отказ
Cloudflare (не ошибка оснастки) — это находка: улики записать, AC-894 fail с
разбором attempts, сервис НЕ откатывать, код gateway НЕ править. Спеку, AC,
BASE и оснастку не менять, rc не выдумывать, чужое не трогать.
