# M15b — выкладка лимита HTTP-ступени на stand-host

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `58d3b738a808af71ebed84df261e87754747ee0a` — main после слияния принятой M15a (http/egress-ступень
ограничена 15 с, её `timeout` передаёт ход браузеру или следующему egress).
Клон /home/user/exec-clones/abg-m15b-deploy-20260917, ветка m15b-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026:
«доделывай все до конца кодексом»). Образец — `docs/specs/m14b-deploy.md`,
`docs/specs/m13c-deploy.md` и раздел README «M12b deployed service» (прочитать
все три целиком).

Обновление production-сервиса на ЭТОМ хосте в каталоге
`/home/user/services/ai-browser-gateway/`. Сейчас там работает release
`b31a36b10f57a21e4d2703e9de770e731d06950e` (образ `abg-runtime:b31a36b10f57`),
Compose-проект `ai-browser-gateway`, API на `127.0.0.1:8765`. Разрешено
менять только: `releases/58d3b738a808af71ebed84df261e87754747ee0a/` и
`manifests/58d3b738a808af71ebed84df261e87754747ee0a.sha256` (создаёт
`abg-release prepare`), ключи `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` в
`compose.env` (и его копию `compose.env.pre-m15b`), свой образ
`abg-runtime:58d3b738a808`, свой Compose-проект и файлы клона.
`releases/b31a36b…`, `releases/4409f8a…`, `releases/929bded…`, их manifests,
образы `abg-runtime:b31a36b10f57`, `abg-runtime:4409f8a5197f`,
`abg-runtime:929bded313e3`, `compose.env.pre-m13c`, `compose.env.pre-m14b` НЕ
удалять и не менять. Каталог `secrets/` не читать и не менять. Провайдерские
образы (`abg-curl_cffi:m2` и др.) не пересобирать и не удалять. Чужие сервисы,
compose-проекты, контейнеры, сети и `.env` не трогать и не читать. Push/merge
запрещены.

## Задача

1. **Выкладка.** Процедура README и пункта 4 `docs/specs/m13c-deploy.md`
   дословно, с заменой: новый release `58d3b738a808af71ebed84df261e87754747ee0a`, копия
   `compose.env.pre-m15b` (0600, не перезаписывать), откат на
   `b31a36b10f57a21e4d2703e9de770e731d06950e` (вернуть `compose.env` из
   `compose.env.pre-m15b` байт-в-байт, `-f` на `releases/b31a36b…`). ДО `up`:
   проект `ai-browser-gateway` запущен из `releases/b31a36b…`, иначе blocker.
   Сбой `up` или AC-934 после `up` — откат и `report-blocked.md`.
2. **Живые проверки** runner'ом `tests/deployed_m12b.py` с `--release 58d3b738a808af71ebed84df261e87754747ee0a
   --evidence /home/user/.cache/abg-coord-20260917/m15b` (код runner НЕ
   менять), строго в этом порядке и без других клиентов API:
   `--check-deploy`, `--check-api-egress`, `--check-bizprofile`,
   `--run-targets`. Из улик дополнительно: ни одна попытка `curl_cffi`
   (ступени http и egress) в `api-egress.json`, `targets.json` и новом архиве
   `bizprofile-<UTC>.json` не длится дольше 20000 мс (лимит 15 с плюс запас
   на запуск контейнера); лестница по-прежнему начинается с `curl_cffi`
   direct.
3. **Документы.** `docs/research/04-phase1-verdict.md` — в раздел
   «Лимит HTTP-ступени (M15a)» добавить подраздел «После выкладки M15b»:
   release, image ID, таблица шести целей и двух страниц bizprofile (провайдер
   успеха, лестница попыток provider/status/challenge/elapsed/next_step) из
   улик, имя файла архива bizprofile; сравнение с матрицей M14b
   (`/home/user/.cache/abg-coord-20260917/m14b/targets.json`): изменились ли
   исходы и время; была ли хоть одна попытка `curl_cffi` с `timeout` и что
   лестница сделала дальше (если не было — так и записать: живой прогон
   ветку таймаута не задел). README: актуальный release
   `58d3b738a808af71ebed84df261e87754747ee0a`, откат на `b31a36b…`, путь улик m15b.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: сервис на `b31a36b…` (compose ls и
`compose.env`); отпечатки отката — sha256 manifest `b31a36b….sha256`
`f0d44ed737b2bf82e46e69f27534bc9e8e9164965c321230b10ec6b47ce2d558`, manifest
`4409f8a….sha256`
`c263d4c65c95e4e0aefb433d58d7eb9207dfc700823f46c6ee91454ab0c983e4`; образ
`abg-runtime:b31a36b10f57` =
`sha256:c0ee2abf4c14dc906092056d832983106ead0518fe3f054dff75565e30669bd0`;
провайдерский образ `abg-curl_cffi:m2` =
`sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc`.
Транспорт (`bench/runner/fetch.py`) переводит истечение лимита запуска в
`FailureReason.timeout`, поэтому лимит 15 с срабатывает на проде той же веткой,
что в unit-тестах. Предположение: на M14b все HTTP-попытки укладывались в
~5 с, поэтому исходы шести целей и bizprofile не изменятся, а таймаут-ветка
вживую задета не будет.

## Разрешения

Всё из «Задачи». Реальные внешние запросы только через runner (AC-935…AC-937),
≥30 с между запросами к одному hostname (runner соблюдает). Docker
build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, tests/** (включая runner), контракт,
другие specs, TASKS.md, CHANGELOG.md; `secrets/**`; чужие сервисы и их файлы;
`~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не менять
policy/budget, не ретраить цель ради зелёного исхода. Сначала закоммитить эту
спеку byte-identical (`docs/specs/m15b-deploy.md`).

## Критерии приёмки

- **AC-931.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-932.** Выкачиваемый код — это BASE:
  `bash -c 'git diff --exit-code 58d3b738a808af71ebed84df261e87754747ee0a HEAD -- gateway bench scripts deploy tests && test -d /home/user/services/ai-browser-gateway/releases/58d3b738a808af71ebed84df261e87754747ee0a'`
- **AC-933.** Откат цел (прежние release сверены, образы те же, копии конфига на месте):
  `bash -c 'printf "%s  %s\n" f0d44ed737b2bf82e46e69f27534bc9e8e9164965c321230b10ec6b47ce2d558 /home/user/services/ai-browser-gateway/manifests/b31a36b10f57a21e4d2703e9de770e731d06950e.sha256 c263d4c65c95e4e0aefb433d58d7eb9207dfc700823f46c6ee91454ab0c983e4 /home/user/services/ai-browser-gateway/manifests/4409f8a5197f7a9f464263e15b362c00548399e2.sha256 | sha256sum -c --quiet - && python3 -c "import sys; sys.path.insert(0, \"tests\"); import deployed_m12b as d; from pathlib import Path; r=\"/home/user/services/ai-browser-gateway\"; [d.verify_release(Path(r, \"releases\", s), Path(r, \"manifests\", s + \".sha256\")) for s in (\"b31a36b10f57a21e4d2703e9de770e731d06950e\", \"4409f8a5197f7a9f464263e15b362c00548399e2\")]" && test "$(docker image inspect abg-runtime:b31a36b10f57 --format "{{.Id}}")" = sha256:c0ee2abf4c14dc906092056d832983106ead0518fe3f054dff75565e30669bd0 && test "$(docker image inspect abg-curl_cffi:m2 --format "{{.Id}}")" = sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m15b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m14b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m13c'`
- **AC-934.** Сервис развёрнут на новом release:
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy --release 58d3b738a808af71ebed84df261e87754747ee0a --evidence /home/user/.cache/abg-coord-20260917/m15b'`
- **AC-935.** Ротация egress через API, egress-попытки в лимите:
  `bash -c 'python3 tests/deployed_m12b.py --check-api-egress --release 58d3b738a808af71ebed84df261e87754747ee0a --evidence /home/user/.cache/abg-coord-20260917/m15b && python3 -c "import json; r=json.load(open(\"/home/user/.cache/abg-coord-20260917/m15b/api-egress.json\")); a=[x for q in r[\"requests\"] for x in q[\"attempts\"] if x[\"egress_profile\"]!=\"direct\"]; assert r.get(\"rotation_proven\") is True and a and all(x[\"provider\"]==\"curl_cffi\" and x[\"elapsed_ms\"]<=20000 for x in a), a"'`
- **AC-936.** Bizprofile без expected_text через deployed API:
  `bash -c 'python3 tests/deployed_m12b.py --check-bizprofile --release 58d3b738a808af71ebed84df261e87754747ee0a --evidence /home/user/.cache/abg-coord-20260917/m15b'`
- **AC-937.** Шесть целей и CLI; лестница с curl_cffi, HTTP-попытки не дольше лимита:
  `bash -c 'python3 tests/deployed_m12b.py --run-targets --release 58d3b738a808af71ebed84df261e87754747ee0a --evidence /home/user/.cache/abg-coord-20260917/m15b && python3 -c "import json,glob; e=\"/home/user/.cache/abg-coord-20260917/m15b/\"; t=json.load(open(e+\"targets.json\"))[\"targets\"]; a=[x for r in t for x in r[\"attempts\"]]; b=json.load(open(sorted(glob.glob(e+\"bizprofile-*.json\"))[-1]))[\"pages\"]; a+= [x for p in b for x in p[\"api_evidence\"][\"attempts\"]]; assert not [x for x in a if x[\"provider\"]==\"curl\"]; s=[x for x in a if x[\"provider\"]==\"curl_cffi\" and x[\"elapsed_ms\"]>20000]; assert not s, s; h=[[x for x in r[\"attempts\"] if x[\"provider\"] not in (\"rss\",\"wayback\")] for r in t]; assert all(s and s[0][\"provider\"]==\"curl_cffi\" and s[0][\"egress_profile\"]==\"direct\" for s in h), h"'`
- **AC-938.** Документы:
  `bash -c 'grep -q "После выкладки M15b" docs/research/04-phase1-verdict.md && grep -q 58d3b738a808af71ebed84df261e87754747ee0a README.md && grep -q abg-coord-20260917/m15b README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-939.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 58d3b738a808af71ebed84df261e87754747ee0a HEAD -- . ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)README.md" ":(exclude)docs/specs/m15b-deploy.md" && git ls-files --error-unmatch docs/specs/m15b-deploy.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Healthchecks `ai-browser-gateway-health`: success-пинги ≈60 с после перезапуска.

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 58d3b738a808af71ebed84df261e87754747ee0a --range 58d3b738a808af71ebed84df261e87754747ee0a..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 9 записей AC-931…AC-939,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"58d3b738a808af71ebed84df261e87754747ee0a","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-931","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m15b-deploy-20260917 --spec /home/user/exec-clones/abg-m15b-deploy-20260917/docs/specs/m15b-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным на новом release (или на `b31a36b…`
после отката).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
проект/порт заняты не нашим `b31a36b…`; нужна правка кода/тестов/deploy/secrets;
`docker build` падает (сервис не тронут); `up` или AC-934 падают после `up`
(сначала откат). Если AC-935…937 дают честный внешний отказ цели — улики
записать, AC fail с разбором attempts, сервис НЕ откатывать, код НЕ править.
Если попытка `curl_cffi` дольше 20000 мс или лестница не начинается с
`curl_cffi` — это дефект M15a: AC-935/937 fail, откатить на `b31a36b…`,
остановиться. Спеку, AC, BASE и оснастку не менять, rc не выдумывать, чужое не
трогать.
