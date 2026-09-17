# M14b — выкладка лестницы с curl_cffi на stand-host

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `b31a36b10f57a21e4d2703e9de770e731d06950e` — main после слияния принятой M14a (`curl_cffi` вместо
`curl` на HTTP- и egress-ступенях).
Клон /home/user/exec-clones/abg-m14b-deploy-20260917, ветка m14b-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026:
«доделывай все до конца кодексом»). Образец — `docs/specs/m13c-deploy.md` и
раздел README «M12b deployed service» (прочитать оба целиком).

Обновление production-сервиса на ЭТОМ хосте в каталоге
`/home/user/services/ai-browser-gateway/`. Сейчас там работает release
`4409f8a5197f7a9f464263e15b362c00548399e2` (образ `abg-runtime:4409f8a5197f`),
Compose-проект `ai-browser-gateway`, API на `127.0.0.1:8765`. Разрешено
менять только: `releases/b31a36b10f57a21e4d2703e9de770e731d06950e/` и `manifests/b31a36b10f57a21e4d2703e9de770e731d06950e.sha256` (создаёт
`abg-release prepare`), ключи `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` в
`compose.env` (и его копию `compose.env.pre-m14b`), свой образ
`abg-runtime:<первые 12 символов b31a36b10f57a21e4d2703e9de770e731d06950e>`, свой Compose-проект и файлы клона.
`releases/4409f8a…`, `releases/929bded…`, их manifests, образы
`abg-runtime:4409f8a5197f`, `abg-runtime:929bded313e3`, `compose.env.pre-m13c`
НЕ удалять и не менять. Каталог `secrets/` не читать и не менять. Провайдерские
образы (`abg-curl_cffi:m2` и др.) не пересобирать и не удалять. Чужие сервисы,
compose-проекты, контейнеры, сети и `.env` не трогать и не читать. Push/merge
запрещены.

## Задача

1. **Выкладка.** Процедура README и пункта 4 `docs/specs/m13c-deploy.md`
   дословно, с заменой: новый release `b31a36b10f57a21e4d2703e9de770e731d06950e`, копия
   `compose.env.pre-m14b` (0600, не перезаписывать), откат на
   `4409f8a5197f7a9f464263e15b362c00548399e2` (вернуть `compose.env` из
   `compose.env.pre-m14b` байт-в-байт, `-f` на `releases/4409f8a…`). ДО `up`:
   проект `ai-browser-gateway` запущен из `releases/4409f8a…`, иначе blocker.
   Сбой `up` или AC-874 после `up` — откат и `report-blocked.md`.
2. **Живые проверки** runner'ом `tests/deployed_m12b.py` с `--release b31a36b10f57a21e4d2703e9de770e731d06950e
   --evidence /home/user/.cache/abg-coord-20260917/m14b` (код runner НЕ
   менять), строго в этом порядке и без других клиентов API:
   `--check-deploy`, `--check-profiles`, `--check-api-egress`,
   `--check-bizprofile`, `--run-targets`. Egress теперь идёт через
   `curl_cffi`, поэтому ротация профилей обязана подтвердиться заново;
   в `api-egress.json` все не-direct попытки — `provider "curl_cffi"`.
   Дополнительно из улик: в `targets.json` у каждой цели, где лестница дошла
   до HTTP-ступени, первая не-entrance попытка — `provider "curl_cffi"`,
   `egress_profile "direct"`; ни одной попытки `provider "curl"` в
   `targets.json` и в новом архиве `bizprofile-<UTC>.json`.
3. **Документы.** `docs/research/04-phase1-verdict.md` — в раздел
   «Пересмотр 17.09.2026» добавить подраздел «После выкладки M14b»: release,
   image ID, таблица шести целей и двух страниц bizprofile (провайдер успеха,
   лестница попыток provider/status/challenge/elapsed) из улик, имя файла
   архива bizprofile; сравнение с матрицей M13c
   (`/home/user/.cache/abg-coord-20260917/m13c/targets.json`): где
   `curl_cffi` взял цель раньше браузера и где нет (и почему — детектор).
   README: актуальный release `b31a36b10f57a21e4d2703e9de770e731d06950e`, откат на `4409f8a…`, путь улик m14b.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: сервис на `4409f8a…`, healthy; отпечатки
отката — sha256 manifest `4409f8a….sha256`
`c263d4c65c95e4e0aefb433d58d7eb9207dfc700823f46c6ee91454ab0c983e4`, образ
`abg-runtime:4409f8a5197f` = `sha256:c7a84ef4061f3d2d6ae7f763718ea96c070f99092751f44dbe96f2a58acd032b`;
провайдерский образ `abg-curl_cffi:m2` =
`sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc`.
Прямой запуск `abg-curl_cffi:m2` с текущим probe: example.com 200/none;
lowendtalk 200, но детектор `captcha` → эскалация в браузер ожидаема;
bizprofile 403. Предположение: control-hqd, control-static и
cf-spa-chatgpt-share возьмёт `curl_cffi`; bizprofile по-прежнему пройдёт
scrapling.

## Разрешения

Всё из «Задачи». Реальные внешние запросы только через runner (AC-875…AC-878),
≥30 с между запросами к одному hostname (runner соблюдает). Docker
build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, tests/** (включая runner), контракт,
другие specs, TASKS.md, CHANGELOG.md; `secrets/**`; чужие сервисы и их файлы;
`~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не менять
policy/budget, не ретраить цель ради зелёного исхода. Сначала закоммитить эту
спеку byte-identical (`docs/specs/m14b-deploy.md`).

## Критерии приёмки

- **AC-871.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-872.** Выкачиваемый код — это BASE:
  `bash -c 'git diff --exit-code b31a36b10f57a21e4d2703e9de770e731d06950e HEAD -- gateway bench scripts deploy tests && test -d /home/user/services/ai-browser-gateway/releases/b31a36b10f57a21e4d2703e9de770e731d06950e'`
- **AC-873.** Откат цел (оба прежних release сверены, образы те же, копии конфига на месте):
  `bash -c 'printf "%s  %s\n" c263d4c65c95e4e0aefb433d58d7eb9207dfc700823f46c6ee91454ab0c983e4 /home/user/services/ai-browser-gateway/manifests/4409f8a5197f7a9f464263e15b362c00548399e2.sha256 f76ec85184f67bd27c4feb8b907e0c75ff995bb89b1a4971482300a3866055bd /home/user/services/ai-browser-gateway/manifests/929bded313e371808b0747fd9a400696a36638aa.sha256 | sha256sum -c --quiet - && python3 -c "import sys; sys.path.insert(0, \"tests\"); import deployed_m12b as d; from pathlib import Path; r=\"/home/user/services/ai-browser-gateway\"; [d.verify_release(Path(r, \"releases\", s), Path(r, \"manifests\", s + \".sha256\")) for s in (\"4409f8a5197f7a9f464263e15b362c00548399e2\", \"929bded313e371808b0747fd9a400696a36638aa\")]" && test "$(docker image inspect abg-runtime:4409f8a5197f --format "{{.Id}}")" = sha256:c7a84ef4061f3d2d6ae7f763718ea96c070f99092751f44dbe96f2a58acd032b && test "$(docker image inspect abg-curl_cffi:m2 --format "{{.Id}}")" = sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m14b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m13c'`
- **AC-874.** Сервис развёрнут на новом release:
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy --release b31a36b10f57a21e4d2703e9de770e731d06950e --evidence /home/user/.cache/abg-coord-20260917/m14b'`
- **AC-875.** Профили egress измерены заново:
  `bash -c 'python3 tests/deployed_m12b.py --check-profiles --release b31a36b10f57a21e4d2703e9de770e731d06950e --evidence /home/user/.cache/abg-coord-20260917/m14b'`
- **AC-876.** Ротация egress через API на curl_cffi:
  `bash -c 'python3 tests/deployed_m12b.py --check-api-egress --release b31a36b10f57a21e4d2703e9de770e731d06950e --evidence /home/user/.cache/abg-coord-20260917/m14b && python3 -c "import json; r=json.load(open(\"/home/user/.cache/abg-coord-20260917/m14b/api-egress.json\")); a=[x for q in r[\"requests\"] for x in q[\"attempts\"] if x[\"egress_profile\"]!=\"direct\"]; assert r.get(\"rotation_proven\") is True and a and all(x[\"provider\"]==\"curl_cffi\" for x in a), a"'`
- **AC-877.** Bizprofile без expected_text через deployed API:
  `bash -c 'python3 tests/deployed_m12b.py --check-bizprofile --release b31a36b10f57a21e4d2703e9de770e731d06950e --evidence /home/user/.cache/abg-coord-20260917/m14b'`
- **AC-878.** Шесть целей и CLI; лестница начинается с curl_cffi и не содержит curl:
  `bash -c 'python3 tests/deployed_m12b.py --run-targets --release b31a36b10f57a21e4d2703e9de770e731d06950e --evidence /home/user/.cache/abg-coord-20260917/m14b && python3 -c "import json,glob; e=\"/home/user/.cache/abg-coord-20260917/m14b/\"; t=json.load(open(e+\"targets.json\"))[\"targets\"]; a=[x for r in t for x in r[\"attempts\"]]; b=json.load(open(sorted(glob.glob(e+\"bizprofile-*.json\"))[-1]))[\"pages\"]; a+= [x for p in b for x in p[\"api_evidence\"][\"attempts\"]]; assert not [x for x in a if x[\"provider\"]==\"curl\"]; h=[[x for x in r[\"attempts\"] if x[\"provider\"] not in (\"rss\",\"wayback\")] for r in t]; assert all(s and s[0][\"provider\"]==\"curl_cffi\" and s[0][\"egress_profile\"]==\"direct\" for s in h), h"'`
- **AC-879.** Документы:
  `bash -c 'grep -q "После выкладки M14b" docs/research/04-phase1-verdict.md && grep -q b31a36b10f57a21e4d2703e9de770e731d06950e README.md && grep -q abg-coord-20260917/m14b README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-880.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code b31a36b10f57a21e4d2703e9de770e731d06950e HEAD -- . ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)README.md" ":(exclude)docs/specs/m14b-deploy.md" && git ls-files --error-unmatch docs/specs/m14b-deploy.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Healthchecks `ai-browser-gateway-health`: success-пинги ≈60 с после перезапуска.

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base b31a36b10f57a21e4d2703e9de770e731d06950e --range b31a36b10f57a21e4d2703e9de770e731d06950e..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 10 записей AC-871…AC-880,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"b31a36b10f57a21e4d2703e9de770e731d06950e","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-871","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m14b-deploy-20260917 --spec /home/user/exec-clones/abg-m14b-deploy-20260917/docs/specs/m14b-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным на новом release (или на `4409f8a…`
после отката).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
проект/порт заняты не нашим `4409f8a…`; нужна правка кода/тестов/deploy/secrets;
`docker build` падает (сервис не тронут); `up` или AC-874 падают после `up`
(сначала откат). Если AC-875…878 дают честный внешний отказ цели — улики
записать, AC fail с разбором attempts, сервис НЕ откатывать, код НЕ править.
Если лестница содержит `curl` или не начинается с `curl_cffi` — это дефект
M14a: AC-876/878 fail, откатить на `4409f8a…`, остановиться. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, чужое не трогать.
