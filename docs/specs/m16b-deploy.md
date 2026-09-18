# M16b — выкладка фикса детектора captcha на stand-host

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `ae72bfe1bae927a0297edfa273632df14ac89689` — main после слияния всей цепочки M16a (fix…fix5) (`captcha`
объявляется только при достаточной улике в теле: title «just a moment» либо
≥2 решающих меток; заголовок `cf-mitigated` и статусы 403/429 остаются
подтверждением сами по себе).
Клон /home/user/exec-clones/abg-m16b-20260918, ветка m16b-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца: «доделывай все
через кодекс»). Образец — `docs/specs/m15b-deploy.md`,
`docs/specs/m14b-deploy.md` и раздел README «M12b deployed service»
(прочитать все три целиком).

Обновление production-сервиса на ЭТОМ хосте в каталоге
`/home/user/services/ai-browser-gateway/`. Сейчас там работает release
`58d3b738a808af71ebed84df261e87754747ee0a` (образ `abg-runtime:58d3b738a808`),
Compose-проект `ai-browser-gateway`, API на `127.0.0.1:8765`. Разрешено
менять только: `releases/ae72bfe1bae927a0297edfa273632df14ac89689/` и `manifests/ae72bfe1bae927a0297edfa273632df14ac89689.sha256`
(создаёт `abg-release prepare`), ключи `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` в
`compose.env` (и его копию `compose.env.pre-m16b`), свой образ
`abg-runtime:ae72bfe1bae9`, свой Compose-проект и файлы клона.
`releases/58d3b73…`, `releases/b31a36b…`, `releases/4409f8a…`,
`releases/929bded…`, их manifests, образы `abg-runtime:58d3b738a808`,
`abg-runtime:b31a36b10f57`, `abg-runtime:4409f8a5197f`,
`abg-runtime:929bded313e3`, `compose.env.pre-m13c`, `compose.env.pre-m14b`,
`compose.env.pre-m15b` НЕ удалять и не менять. Каталог `secrets/` не читать и
не менять. Провайдерские образы (`abg-curl_cffi:m2` и др.) не пересобирать и
не удалять. Чужие сервисы, compose-проекты, контейнеры, сети и `.env` не
трогать и не читать. Push/merge запрещены.

Почему выкладка вообще меняет поведение: детектор живёт в
`bench/providers/docker/probe.py` и бинд-маунтится в провайдерский контейнер
из каталога релиза (`bench/runner/fetch.py`, `PROBE_FILE`). Пересборка
`abg-curl_cffi:m2` не нужна и запрещена.

Вместе с детектором едет правка продуктового форматтера M16a-fix4
(`gateway/format_html.py`): до неё страница с гигантской числовой ссылкой
роняла разбор, и форматы `markdown`/`links`/`meta` отвечали HTTP 500. Она
живёт в рантайм-образе, поэтому подхватывается обычной пересборкой
`abg-runtime:ae72bfe1bae9`; отдельных действий не требует. Живой проверки на
боевой цели для неё не предусмотрено: враждебной страницы с такой ссылкой в
интернете под рукой нет, а подкладывать её в прод запрещено — проверка
сделана координатором на стенде до выкладки (три формата 500 → 200).

## Задача

1. **Выкладка.** Процедура README и пункта 4 `docs/specs/m13c-deploy.md`
   дословно, с заменой: новый release `ae72bfe1bae927a0297edfa273632df14ac89689`, копия
   `compose.env.pre-m16b` (0600, не перезаписывать), откат на
   `58d3b738a808af71ebed84df261e87754747ee0a` (вернуть `compose.env` из
   `compose.env.pre-m16b` байт-в-байт, `-f` на `releases/58d3b73…`). ДО `up`:
   проект `ai-browser-gateway` запущен из `releases/58d3b73…`, иначе blocker.
   Сбой `up` или AC-942 после `up` — откат и `report-blocked.md`.
2. **Живые проверки** runner'ом `tests/deployed_m12b.py` с
   `--release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b`
   (код runner НЕ менять), строго в этом порядке:
   `--check-deploy`, `--check-profiles`, `--check-api-egress`,
   `--check-bizprofile`, `--run-targets` (`--check-api-egress` читает
   `profiles.json`, который пишет `--check-profiles`).
3. **Живая проверка самого фикса.** Ровно ОДИН запрос к
   `https://lowendtalk.com/` через развёрнутый API (`127.0.0.1:8765`, токен
   читать программно из `secrets/token` сервиса или `~/.config/abg/client-token`,
   НЕ печатать), без `expected_text`, ответ целиком положить в
   `/home/user/.cache/abg-coord-20260918/m16b/lowendtalk.json`. Замер ДО фикса
   (координатор, 18.09.2026, release `58d3b73…`): `ok=false`,
   `error_type=interactive_challenge`, `step=human`, единственная попытка
   `curl_cffi / interactive_challenge / captcha / 275 мс / next_step=human` —
   лестница отказывалась сразу и браузер не пробовала. Ожидание после фикса:
   первая попытка `curl_cffi` больше НЕ отдаёт `challenge=captcha` с
   `next_step=human`. Честный внешний отказ цели (403/429/сетевой) — это не
   провал вехи, см. «Контракт на невыполнимое».
4. **Документы.** `docs/research/04-phase1-verdict.md` — в раздел
   «Ложная captcha на 200 (M16a)» добавить подраздел «После выкладки M16b»
   (упомянуть, что в этот же релиз входит правка форматтера M16a-fix4):
   release, image ID, таблица шести целей и двух страниц bizprofile (провайдер
   успеха, лестница попыток provider/status/challenge/elapsed/next_step) из
   улик, имя файла архива bizprofile; исход lowendtalk до и после с обеими
   лестницами; сравнение матрицы целей с M15b
   (`/home/user/.cache/abg-coord-20260917/m15b/targets.json`) — изменились ли
   исходы и время. README: актуальный release `ae72bfe1bae927a0297edfa273632df14ac89689`, откат на
   `58d3b73…`, путь улик m16b.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026: сервис на `58d3b73…` (`docker compose ls`);
отпечатки отката — sha256 manifest `58d3b73….sha256`
`0af6e2a5162d9b058a567086e85ad01182a08043ff6531137ce8ee21bdb1df45`, manifest
`b31a36b….sha256`
`f0d44ed737b2bf82e46e69f27534bc9e8e9164965c321230b10ec6b47ce2d558`; образ
`abg-runtime:58d3b738a808` =
`sha256:1acaf7967acbd0a436b5a01dd0a25ab4edee9e27dbcaba4a41361e48a8e53dd0`;
провайдерский образ `abg-curl_cffi:m2` =
`sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc`.
Замер lowendtalk до фикса — выше, пункт 3, сделан через тот же API.
Предположение: шесть целей и bizprofile после фикса дают те же исходы, что в
M15b; ни одна из них не опиралась на ложную `captcha`.

## Разрешения

Всё из «Задачи». Реальные внешние запросы только через runner (AC-943…AC-945)
и ровно один запрос lowendtalk из пункта 3; ≥30 с между запросами к одному
hostname. Docker build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, tests/** (включая runner), контракт,
другие specs, TASKS.md, CHANGELOG.md; `secrets/**`; чужие сервисы и их файлы;
`~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не менять
policy/budget, не ретраить цель ради зелёного исхода. Сначала закоммитить эту
спеку byte-identical (`docs/specs/m16b-deploy.md`).

## Критерии приёмки

- **AC-940.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-941.** Выкачиваемый код — это BASE:
  `bash -c 'git diff --exit-code ae72bfe1bae927a0297edfa273632df14ac89689 HEAD -- gateway bench scripts deploy tests && test -d /home/user/services/ai-browser-gateway/releases/ae72bfe1bae927a0297edfa273632df14ac89689'`
- **AC-942.** Сервис развёрнут на новом release:
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy --release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b'`
- **AC-943.** Откат цел (прежние release сверены, образы те же, копии конфига на месте):
  `bash -c 'printf "%s  %s\n" 0af6e2a5162d9b058a567086e85ad01182a08043ff6531137ce8ee21bdb1df45 /home/user/services/ai-browser-gateway/manifests/58d3b738a808af71ebed84df261e87754747ee0a.sha256 f0d44ed737b2bf82e46e69f27534bc9e8e9164965c321230b10ec6b47ce2d558 /home/user/services/ai-browser-gateway/manifests/b31a36b10f57a21e4d2703e9de770e731d06950e.sha256 | sha256sum -c --quiet - && python3 -c "import sys; sys.path.insert(0, \"tests\"); import deployed_m12b as d; from pathlib import Path; r=\"/home/user/services/ai-browser-gateway\"; [d.verify_release(Path(r, \"releases\", s), Path(r, \"manifests\", s + \".sha256\")) for s in (\"58d3b738a808af71ebed84df261e87754747ee0a\", \"b31a36b10f57a21e4d2703e9de770e731d06950e\")]" && test "$(docker image inspect abg-runtime:58d3b738a808 --format "{{.Id}}")" = sha256:1acaf7967acbd0a436b5a01dd0a25ab4edee9e27dbcaba4a41361e48a8e53dd0 && test "$(docker image inspect abg-curl_cffi:m2 --format "{{.Id}}")" = sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m16b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m15b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m14b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m13c'`
- **AC-944.** Профили заново и ротация egress через API:
  `bash -c 'python3 tests/deployed_m12b.py --check-profiles --release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b && python3 tests/deployed_m12b.py --check-api-egress --release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b'`
- **AC-945.** Bizprofile и шесть целей; лестница по-прежнему начинается с curl_cffi direct:
  `bash -c 'python3 tests/deployed_m12b.py --check-bizprofile --release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b && python3 tests/deployed_m12b.py --run-targets --release ae72bfe1bae927a0297edfa273632df14ac89689 --evidence /home/user/.cache/abg-coord-20260918/m16b && python3 -c "import json; e=\"/home/user/.cache/abg-coord-20260918/m16b/\"; t=json.load(open(e+\"targets.json\"))[\"targets\"]; h=[[x for x in r[\"attempts\"] if x[\"provider\"] not in (\"rss\",\"wayback\")] for r in t]; assert all(s and s[0][\"provider\"]==\"curl_cffi\" and s[0][\"egress_profile\"]==\"direct\" for s in h), h"'`
- **AC-946.** Ложная captcha на lowendtalk ушла (улика из пункта 3):
  `bash -c 'python3 -c "import json; d=json.load(open(\"/home/user/.cache/abg-coord-20260918/m16b/lowendtalk.json\")); a=d[\"attempts\"]; assert a, d; bad=[x for x in a if x.get(\"challenge\")==\"captcha\" and x.get(\"next_step\")==\"human\"]; assert not bad, bad"'`
- **AC-947.** Документы:
  `bash -c 'grep -q "После выкладки M16b" docs/research/04-phase1-verdict.md && grep -q lowendtalk docs/research/04-phase1-verdict.md && grep -q ae72bfe1bae927a0297edfa273632df14ac89689 README.md && grep -q abg-coord-20260918/m16b README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-948.** Вне разрешённых путей ничего не изменено, дерево чистое, секретов в уликах нет:
  `bash -c 'git diff --exit-code ae72bfe1bae927a0297edfa273632df14ac89689 HEAD -- . ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)README.md" ":(exclude)docs/specs/m16b-deploy.md" && git ls-files --error-unmatch docs/specs/m16b-deploy.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")" && ! grep -rqE "Bearer [A-Za-z0-9._-]{8,}" /home/user/.cache/abg-coord-20260918/m16b'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Healthchecks `ai-browser-gateway-health`: success-пинги ≈60 с после перезапуска.

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base ae72bfe1bae927a0297edfa273632df14ac89689 --range ae72bfe1bae927a0297edfa273632df14ac89689..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 9 записей AC-940…AC-948,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"ae72bfe1bae927a0297edfa273632df14ac89689","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-940","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16b-20260918 --spec /home/user/exec-clones/abg-m16b-20260918/docs/specs/m16b-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным на новом release (или на `58d3b73…`
после отката).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
проект/порт заняты не нашим `58d3b73…`; нужна правка кода/тестов/deploy/secrets;
`docker build` падает (сервис не тронут); `up` или AC-942 падают после `up`
(сначала откат). Если AC-944…AC-946 дают честный внешний отказ цели (403, 429,
сетевая ошибка, реальный интерактивный челлендж с `cf-mitigated` в заголовках) —
улики записать, AC fail с разбором attempts, сервис НЕ откатывать, код НЕ
править. Если lowendtalk снова даёт `captcha` + `next_step=human` на HTTP 200
без `cf-mitigated` — это дефект M16a: AC-946 fail, откатить на `58d3b73…`,
остановиться. Спеку, AC, BASE и оснастку не менять, rc не выдумывать, чужое не
трогать.
