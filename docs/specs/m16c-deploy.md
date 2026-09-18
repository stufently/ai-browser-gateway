# M16c — выкладка браузерной нормализации детектора на stand-host

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `db4fc359171c304470d7edae3d60cb13394e7881` — main после слияния хвоста цепочки M16a (fix6, fix7,
fix8). Клон /home/user/exec-clones/abg-m16c-20260918, ветка m16c-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца: «доделывай все
через кодекс»). Образец — `docs/specs/m16b-deploy.md`,
`docs/specs/m15b-deploy.md` и раздел README «M12b deployed service»
(прочитать все три целиком).

Обновление production-сервиса на ЭТОМ хосте в каталоге
`/home/user/services/ai-browser-gateway/`. Сейчас там работает release
`ae72bfe1bae927a0297edfa273632df14ac89689` (образ `abg-runtime:ae72bfe1bae9`),
Compose-проект `ai-browser-gateway`, API на `127.0.0.1:8765`. Разрешено
менять только: `releases/db4fc359171c304470d7edae3d60cb13394e7881/` и `manifests/db4fc359171c304470d7edae3d60cb13394e7881.sha256`
(создаёт `abg-release prepare`), ключи `ABG_RELEASE` и `ABG_RUNTIME_IMAGE` в
`compose.env` (и его копию `compose.env.pre-m16c`), свой образ
`abg-runtime:db4fc359171c`, свой Compose-проект и файлы клона.
`releases/ae72bfe1bae927a0297edfa273632df14ac89689`, `releases/58d3b738a808af71ebed84df261e87754747ee0a`,
`releases/b31a36b10f57a21e4d2703e9de770e731d06950e`, их manifests, образы
`abg-runtime:ae72bfe1bae9`, `abg-runtime:58d3b738a808`,
`abg-runtime:b31a36b10f57`, `compose.env.pre-m13c`, `compose.env.pre-m14b`,
`compose.env.pre-m15b`, `compose.env.pre-m16b` НЕ удалять и не менять. Каталог
`secrets/` не читать и не менять. Провайдерские образы (`abg-curl_cffi:m2` и
др.) не пересобирать и не удалять. Чужие сервисы, compose-проекты, контейнеры,
сети и `.env` не трогать и не читать. Push/merge запрещены.

Почему выкладка вообще меняет поведение: детектор живёт в
`bench/providers/docker/probe.py` и бинд-маунтится в провайдерский контейнер
из каталога релиза (`bench/runner/fetch.py`, `PROBE_FILE`). Пересборка
`abg-curl_cffi:m2` не нужна и запрещена.

## Что именно едет и почему у этого нет живой цели

Предыдущая выкладка (M16b, release `ae72bfe1bae927a0297edfa273632df14ac89689`) починила главный случай:
lowendtalk на HTTP 200 больше не объявляется `captcha`. Эта выкладка везёт
остаток цепочки — приведение разбора разметки к тому, что делает настоящий
браузер:

- буквальный NUL в значении атрибута HTML-парсер браузера заменяет на U+FFFD,
  а не выбрасывает: `src="…render=explicit\x00"` — это НЕ `render=explicit`, то
  есть НЕ интерактивный виджет;
- `classList` режет `class` только по ASCII-пробельным символам, поэтому
  `class="g-recaptcha<NBSP>foo"` — один токен и НЕ виджет;
- обратный слэш в относительном `src` браузер считает разделителем пути:
  `recaptcha\api.js` — это `/recaptcha/api.js`, то есть виджет ЕСТЬ;
- краевая обрезка `src` переписана с квадратичной регулярки на `str.strip`
  (16000 внутренних пробелов: 1,235 с → 0,000015 с, замер координатора в Docker
  18.09.2026), чтобы недоверенная страница не жгла CPU внутри бюджета запроса.

Первые два случая до этой выкладки дают ЛОЖНЫЙ `captcha` на честном HTTP 200,
третий — ложный `none` на настоящем виджете. Живой цели в интернете, которая
отдавала бы такую разметку, у нас нет и подкладывать её в прод запрещено,
поэтому ценность проверяется не на внешнем сайте, а прямо на ВЫЛОЖЕННОМ файле
детектора: AC-956 импортирует `probe.py` из каталога релиза и гоняет по нему
четыре фикстуры офлайн. Живые проверки этой вехи (AC-954, AC-955, AC-957)
отвечают на другой вопрос — не сломала ли выкладка то, что уже работало.

## Задача

1. **Выкладка.** Процедура README и пункта 4 `docs/specs/m13c-deploy.md`
   дословно, с заменой: новый release `db4fc359171c304470d7edae3d60cb13394e7881`, копия
   `compose.env.pre-m16c` (0600, не перезаписывать), откат на
   `ae72bfe1bae927a0297edfa273632df14ac89689` (вернуть `compose.env` из
   `compose.env.pre-m16c` байт-в-байт, `-f` на `releases/ae72bfe1bae927a0297edfa273632df14ac89689`). ДО `up`:
   проект `ai-browser-gateway` запущен из `releases/ae72bfe1bae927a0297edfa273632df14ac89689`, иначе blocker.
   Сбой `up` или AC-952 после `up` — откат и `report-blocked.md`.
2. **Живые проверки** runner'ом `tests/deployed_m12b.py` с
   `--release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c`
   (код runner НЕ менять), строго в этом порядке:
   `--check-deploy`, `--check-profiles`, `--check-api-egress`,
   `--check-bizprofile`, `--run-targets` (`--check-api-egress` читает
   `profiles.json`, который пишет `--check-profiles`).
3. **Проверка отсутствия регресса на lowendtalk.** Ровно ОДИН запрос к
   `https://lowendtalk.com/` через развёрнутый API (`127.0.0.1:8765`, токен
   читать программно из `secrets/token` сервиса или `~/.config/abg/client-token`,
   НЕ печатать), без `expected_text`, ответ целиком положить в
   `/home/user/.cache/abg-coord-20260918/m16c/lowendtalk.json`. Замер на
   текущем релизе (координатор, 18.09.2026, release `ae72bfe1bae927a0297edfa273632df14ac89689`): `ok=true`,
   провайдер `curl_cffi`, `challenge=none`, 213 мс, `next_step=stop`. Ожидание
   после выкладки: то же самое — `ok=true` и ни одной попытки с
   `challenge=captcha` + `next_step=human`. Честный внешний отказ цели
   (403/429/сетевой) — это не провал вехи, см. «Контракт на невыполнимое».
4. **Документы.** `docs/research/04-phase1-verdict.md` — в раздел
   «Ложная captcha на 200 (M16a)» добавить подраздел «После выкладки M16c»:
   release, image ID, что именно приехало (четыре случая браузерного паритета
   из раздела «Что именно едет»), результат офлайн-проверки выложенного
   детектора (AC-956, четыре фикстуры и замер времени), таблица шести целей и
   двух страниц bizprofile (провайдер успеха, лестница попыток
   provider/status/challenge/elapsed/next_step) из улик, имя файла архива
   bizprofile; исход lowendtalk с лестницей; сравнение матрицы целей с M16b
   (`/home/user/.cache/abg-coord-20260918/m16b/targets.json`) — изменились ли
   исходы и время. README: актуальный release `db4fc359171c304470d7edae3d60cb13394e7881`, откат на
   `ae72bfe1bae927a0297edfa273632df14ac89689`, путь улик m16c.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026: сервис на `ae72bfe1bae927a0297edfa273632df14ac89689` (`docker compose ls`);
отпечатки отката — sha256 manifest `ae72bfe1bae927a0297edfa273632df14ac89689.sha256`
`096bc4ae96b7bdfeb2b2aa5960c1445910eaa898a9a899c4a42a43399720b6c9`, manifest
`58d3b738a808af71ebed84df261e87754747ee0a.sha256`
`0af6e2a5162d9b058a567086e85ad01182a08043ff6531137ce8ee21bdb1df45`; образ
`abg-runtime:ae72bfe1bae9` =
`sha256:ada25963a6592dab44996b00c8fa9d5495631a00d2c920d73252765a64190b43`;
провайдерский образ `abg-curl_cffi:m2` =
`sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc`.
Замер lowendtalk на текущем релизе — выше, пункт 3, сделан через тот же API.
Четыре случая браузерного паритета проверены координатором в живом Chrome
(`document.implementation.createHTMLDocument`, `classList`, `new URL`), а не в
`urllib.parse`: у Python другая политика пробелов, и авторитетом он тут не
является.
Предположение: шесть целей и bizprofile после выкладки дают те же исходы, что в
M16b; ни одна из них не опиралась на разобранный `class` с NBSP, на NUL в
атрибуте и на обратный слэш в `src`.

## Разрешения

Всё из «Задачи». Реальные внешние запросы только через runner (AC-954, AC-955)
и ровно один запрос lowendtalk из пункта 3; ≥30 с между запросами к одному
hostname. Docker build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, tests/** (включая runner), контракт,
другие specs, TASKS.md, CHANGELOG.md; `secrets/**`; чужие сервисы и их файлы;
`~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не менять
policy/budget, не ретраить цель ради зелёного исхода. Сначала закоммитить эту
спеку byte-identical (`docs/specs/m16c-deploy.md`).

## Критерии приёмки

- **AC-950.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-951.** Выкачиваемый код — это BASE, и выложенный детектор байт-в-байт равен BASE:
  `bash -c 'git diff --exit-code db4fc359171c304470d7edae3d60cb13394e7881 HEAD -- gateway bench scripts deploy tests && test -d /home/user/services/ai-browser-gateway/releases/db4fc359171c304470d7edae3d60cb13394e7881 && test "$(git show db4fc359171c304470d7edae3d60cb13394e7881:bench/providers/docker/probe.py | sha256sum | cut -d" " -f1)" = "$(sha256sum /home/user/services/ai-browser-gateway/releases/db4fc359171c304470d7edae3d60cb13394e7881/bench/providers/docker/probe.py | cut -d" " -f1)"'`
- **AC-952.** Сервис развёрнут на новом release:
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy --release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c'`
- **AC-953.** Откат цел (прежние release сверены, образы те же, копии конфига на месте):
  `bash -c 'printf "%s  %s\n" 096bc4ae96b7bdfeb2b2aa5960c1445910eaa898a9a899c4a42a43399720b6c9 /home/user/services/ai-browser-gateway/manifests/ae72bfe1bae927a0297edfa273632df14ac89689.sha256 0af6e2a5162d9b058a567086e85ad01182a08043ff6531137ce8ee21bdb1df45 /home/user/services/ai-browser-gateway/manifests/58d3b738a808af71ebed84df261e87754747ee0a.sha256 | sha256sum -c --quiet - && python3 -c "import sys; sys.path.insert(0, \"tests\"); import deployed_m12b as d; from pathlib import Path; r=\"/home/user/services/ai-browser-gateway\"; [d.verify_release(Path(r, \"releases\", s), Path(r, \"manifests\", s + \".sha256\")) for s in (\"ae72bfe1bae927a0297edfa273632df14ac89689\", \"58d3b738a808af71ebed84df261e87754747ee0a\")]" && test "$(docker image inspect abg-runtime:ae72bfe1bae9 --format "{{.Id}}")" = sha256:ada25963a6592dab44996b00c8fa9d5495631a00d2c920d73252765a64190b43 && test "$(docker image inspect abg-curl_cffi:m2 --format "{{.Id}}")" = sha256:a5dbc883dc6fb672cf36d80fc3c87c02afbc9085e0c14812328cf8d225bbd7dc && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m16c && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m16b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m15b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m14b && test -s /home/user/services/ai-browser-gateway/compose.env.pre-m13c'`
- **AC-954.** Профили заново и ротация egress через API:
  `bash -c 'python3 tests/deployed_m12b.py --check-profiles --release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c && python3 tests/deployed_m12b.py --check-api-egress --release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c'`
- **AC-955.** Bizprofile и шесть целей; лестница по-прежнему начинается с curl_cffi direct:
  `bash -c 'python3 tests/deployed_m12b.py --check-bizprofile --release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c && python3 tests/deployed_m12b.py --run-targets --release db4fc359171c304470d7edae3d60cb13394e7881 --evidence /home/user/.cache/abg-coord-20260918/m16c && python3 -c "import json; e=\"/home/user/.cache/abg-coord-20260918/m16c/\"; t=json.load(open(e+\"targets.json\"))[\"targets\"]; h=[[x for x in r[\"attempts\"] if x[\"provider\"] not in (\"rss\",\"wayback\")] for r in t]; assert all(s and s[0][\"provider\"]==\"curl_cffi\" and s[0][\"egress_profile\"]==\"direct\" for s in h), h"'`
- **AC-956.** ВЫЛОЖЕННЫЙ детектор разбирает разметку по-браузерному (офлайн, четыре фикстуры + бюджет времени):
  `bash -c 'python3 -c "import importlib.util as U, time; q=chr(34); p=\"/home/user/services/ai-browser-gateway/releases/db4fc359171c304470d7edae3d60cb13394e7881/bench/providers/docker/probe.py\"; s=U.spec_from_file_location(\"probe\", p); m=U.module_from_spec(s); s.loader.exec_module(m); W=lambda i: \"<html><body>cf_chl_opt\" + i + \"</body></html>\"; S=lambda v: \"<script src=\" + q + v + q + \"></script>\"; D=lambda c: \"<div class=\" + q + c + q + \"></div>\"; cases=[(S(\"recaptcha/api.js?render=explicit\x00\"), \"none\"), (D(\"g-recaptcha foo\"), \"none\"), (D(\"g-recaptcha\tfoo\"), \"captcha\"), (S(\"recaptcha\\\\api.js?render=explicit\"), \"captcha\")]; bad=[(i, m.detect_challenge(200, {}, W(i))) for i, e in cases if m.detect_challenge(200, {}, W(i))[0] != e]; assert not bad, bad; t=time.monotonic(); m.detect_challenge(200, {}, W(S(\"recaptcha/api.js?render=\" + chr(32) * 32000 + \"explicit\"))); d=time.monotonic() - t; assert d < 2, d"'`
- **AC-957.** Регресса на lowendtalk нет (улика из пункта 3):
  `bash -c 'python3 -c "import json; d=json.load(open(\"/home/user/.cache/abg-coord-20260918/m16c/lowendtalk.json\")); a=d[\"attempts\"]; assert a, d; assert d[\"ok\"] is True, d; bad=[x for x in a if x.get(\"challenge\")==\"captcha\" and x.get(\"next_step\")==\"human\"]; assert not bad, bad"'`
- **AC-958.** Документы:
  `bash -c 'grep -q "После выкладки M16c" docs/research/04-phase1-verdict.md && grep -q lowendtalk docs/research/04-phase1-verdict.md && grep -q db4fc359171c304470d7edae3d60cb13394e7881 README.md && grep -q abg-coord-20260918/m16c README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-959.** Вне разрешённых путей ничего не изменено, дерево чистое, секретов в уликах нет:
  `bash -c 'git diff --exit-code db4fc359171c304470d7edae3d60cb13394e7881 HEAD -- . ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)README.md" ":(exclude)docs/specs/m16c-deploy.md" && git ls-files --error-unmatch docs/specs/m16c-deploy.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")" && ! grep -rqE "Bearer [A-Za-z0-9._-]{8,}" /home/user/.cache/abg-coord-20260918/m16c'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Healthchecks `ai-browser-gateway-health`: success-пинги ≈60 с после перезапуска.

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base db4fc359171c304470d7edae3d60cb13394e7881 --range db4fc359171c304470d7edae3d60cb13394e7881..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 10 записей AC-950…AC-959,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"db4fc359171c304470d7edae3d60cb13394e7881","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-950","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16c-20260918 --spec /home/user/exec-clones/abg-m16c-20260918/docs/specs/m16c-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным на новом release (или на `ae72bfe1bae927a0297edfa273632df14ac89689`
после отката).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
проект/порт заняты не нашим `ae72bfe1bae927a0297edfa273632df14ac89689`; нужна правка кода/тестов/deploy/secrets;
`docker build` падает (сервис не тронут); `up` или AC-952 падают после `up`
(сначала откат). Если AC-954, AC-955, AC-957 дают честный внешний отказ цели
(403, 429, сетевая ошибка, реальный интерактивный челлендж с `cf-mitigated` в
заголовках) — улики записать, AC fail с разбором attempts, сервис НЕ откатывать,
код НЕ править. Если AC-956 падает — это дефект самой цепочки M16a, а не
внешнего мира: откатить на `ae72bfe1bae927a0297edfa273632df14ac89689` и остановиться. Если lowendtalk снова
даёт `captcha` + `next_step=human` на HTTP 200 без `cf-mitigated` — то же самое:
AC-957 fail, откат, стоп. Спеку, AC, BASE и оснастку не менять, rc не выдумывать,
чужое не трогать.
