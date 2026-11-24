# M28 — образы провайдеров в healthcheck и --check-deploy; bizprofile с любым провайдером

## Шапка и где работать

Репозиторий ai-browser-gateway, 24.11.2026. BASE_SHA: см. последнюю строку
раздела (коммит этой спеки и файлов стенда `docs/specs/checks/m28_*`).
Критерий границ считает дифф от `git merge-base HEAD origin/main`, поэтому
клон делается только `make_clone.sh` от вершины `main`. Исполнитель — `auto`;
мутации по новым тестам потом гоняет противоположный исполнитель отдельной
вехой. Параллельно идёт M27 (прокси-ретранслятор в контейнере: `probe.py`,
one-shot, образы провайдеров); веха M28 с ней файлов не делит.

Новая ветка: `m28-provider-images-health`. Живое дерево постановщика не
трогать. git pull в клоне не делать; push в origin запрещён, работу заберёт
постановщик через `git fetch` из клона. Постановщик до запуска проверяет, что
на хосте есть рантайм-образ стенда (ID в `docs/specs/checks/m28_stand.sh`),
публичный образ Python из критериев и пять образов маршрута (ниже).

## Задача и почему

10.11.2026 разовая чистка `docker image prune -a` удалила образы провайдеров
боевого маршрута: их контейнеры живут секунды, и prune считает образы
неиспользуемыми. Две недели API оставался `healthy`, `--check-deploy`
проходил, а каждый вызов падал с `environment_error` за ~0,5 с. Healthcheck
(`/health`) и `--check-deploy` наличие образов не проверяют вообще.

Решения владельца (не пересматривать):

1. `/health` сервиса и `--check-deploy` проверяют, что ВСЕ образы провайдеров
   боевого маршрута есть локально. Нет хотя бы одного — healthcheck не
   проходит (контейнер `unhealthy`, монитор шлёт `/fail`), `--check-deploy`
   даёт `ok:false` с перечнем недостающих тегов.
2. `--check-bizprofile` принимает любой успешный провайдер (ok, маркер найден)
   и пишет в результат, какой провайдер отдал каждую страницу. Сейчас он
   требует scrapling, а страницы с 24.11 отдаёт curl_cffi 0.17.0 первой
   ступенью — проверка формально падает на исправном сервисе.

## Что проверено вживую, а что предположение

Проверено постановщиком 24.11.2026 (Docker 29.9.2 на хосте, CLI 29.8.0 в
рантайм-образе, всё под 1002:1002, боевой сервис только читался):

- Образы маршрута — это провайдеры из `plan_product` (`gateway/product.py`)
  при `max_age_hours > 0` и `allow_browser=True`, образ каждого — из
  `bench/providers/registry.py` (`by_name(...).image`; `bench/runner/fetch.py`
  берёт образ так же). Вычислено вживую: `abg-curl_cffi:m2`,
  `abg-patchright:m2`, `abg-rss:m4`, `abg-scrapling:m8`, `abg-wayback:m4`.
  Запасная ступень egress — тоже curl_cffi, новых образов не добавляет.
- Healthcheck в `deploy/compose.yaml` (так же в `docker inspect` боевого
  контейнера api): `python3 -c` с `urllib.request.urlopen(.../health,
  timeout=4)`, требует `ok is True`; interval 30 s, timeout 5 s, retries 3.
  Ответ 503 даёт `HTTPError` → код 1 → `unhealthy` (проверено стендом на
  эталоне, сценарий absent). Сам прогон healthcheck занимает ~0,3 с.
  `deploy/compose.yaml` менять не нужно.
- Монитор (`gateway/health_monitor.py::check_once`) считает здоровым только
  статус 200 с `ok is True`, иначе пингует `/fail`.
- Контейнер api: пользователь 1002:1002, `group_add` = gid сокета,
  `/var/run/docker.sock` смонтирован RW, docker CLI в образе
  (`deploy/Dockerfile`). Изнутри боевого контейнера (только чтение)
  `docker image ls --format '{{.Repository}}:{{.Tag}}' --filter reference=<образ>`
  × 5 отработал за 40–42 мс, rc 0, вывел все пять тегов. Несколько
  `--filter reference=` объединяются по ИЛИ; отсутствующий тег просто не
  выводится, rc остаётся 0 (а `docker image inspect` с отсутствующим тегом
  даёт rc 1 и не говорит, какие нашлись, поэтому выбран `image ls`).
- `/health` сейчас (`gateway/api_http.py::dispatch`) всегда отвечает
  `200 {"ok": true}`, без авторизации; сервер — `ThreadingHTTPServer`, поток
  на запрос. `make_server` (`gateway/httpapi.py`) вызывают замороженные пробы
  M12 без новых аргументов и ждут прежний `/health` — поведение по умолчанию
  обязано остаться. `make_service` в тестах собирается без Docker — значит,
  при сборке docker не вызывается.
- `tests/deployed_m12b.py`: при ошибке `main()` печатает в stderr и пишет в
  `<mode>-result.json` ровно `{"ok": false, "internal_error": "<код>"}`, при
  успехе печатает `{"ok": true, "mode": "<mode>"}`, файл `{"ok": true}`.
  `check_deploy` сначала `verify_release`, потом читает `compose.env`.
  Файл работает и одиночным монтированием в контейнер (`worker`), поэтому
  импортировать `gateway` на уровне модуля нельзя. `check_bizprofile`
  требует `provider == 'scrapling'` у ответа и у последней попытки.
- Фейк `run_docker` в `tests/test_deployed_m12b.py` (`MonitorLogTests`)
  падает на любой незнакомой команде docker: новую команду проверки образов
  надо добавить в фейк, иначе упадут шесть существующих тестов (проверено на
  эталоне).
- Чекер `docs/specs/checks/m28_provider_images.py` и стенд
  `docs/specs/checks/m28_stand.sh` прогнаны на эталонной реализации
  постановщика (черновая копия, не в репозитории): чекер `ok`; стенд
  `present` и `absent` — `ok` по три раза; полный сьют (838) и замороженные
  пробы зелёные; команда AC-005 на эталоне дала счёт красных `[4, 3]`.
  На BASE чекер падает по делу (19 расхождений), стенд `absent` — FAIL
  (200 вместо 503), `present` проходит (BASE всегда отвечает 200).

Предположения: на хостах с другим хранилищем образов (не проверялось
ничего, кроме Docker 29.9.2 этого хоста) формат `{{.Repository}}:{{.Tag}}`
тот же; кэш 15 с и таймаут 3 с выбраны расчётом (ниже), а не замером под
нагрузкой.

## Что сделать

Разрешённые файлы: новый `gateway/provider_images.py`, `gateway/api_http.py`,
`gateway/httpapi.py`, `gateway/service.py`, `tests/deployed_m12b.py`,
`tests/test_deployed_m12b.py`, новый `tests/test_provider_images.py`.

1. **`gateway/provider_images.py`.**
   - `route_images()` → кортеж образов маршрута, отсортированный, без
     повторов: провайдеры из `plan_product(ProductRequest('https://example.com/',
     max_age_hours=1.0))`, образ — через `bench.providers.registry.by_name`
     в момент вызова (не список-константа, не кэш на импорте).
   - `class ImageCheck(images=None, *, run=None, clock=None, ttl=15.0,
     timeout=3.0)`. `images=None` → `route_images()`; явный список
     сортируется. `run=None` → `subprocess.run`, найденный в момент проверки
     через модуль `subprocess` (не `from subprocess import run`, не
     значение по умолчанию на этапе определения); `clock=None` →
     `time.monotonic` так же. Конструктор docker не вызывает.
   - Одна проверка — ОДИН вызов
     `run(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}',
     '--filter', 'reference=<образ1>', ...], capture_output=True, text=True,
     timeout=3.0, stdin=subprocess.DEVNULL)`, фильтры в порядке
     отсортированного списка. Найденные — строки stdout после `strip()`;
     прочие строки (`<none>:<none>`) игнорируются.
   - `status()` никогда не бросает и возвращает новый dict:
     `{"ok": true}`; или `{"ok": false, "error": "provider_images_missing",
     "missing": [<отсутствующие, по порядку списка>]}`; или
     `{"ok": false, "error": "provider_images_unknown"}` при rc ≠ 0 и любом
     исключении `run` (таймаут, нет docker, что угодно).
   - Кэш: результат (любой из трёх) переиспользуется, пока
     `clock() - отметка < ttl`; при `>= ttl` — новая проверка. Под замком:
     одновременные `status()` во время проверки ждут её и не запускают
     свою (один вызов docker). Изменение возвращённого dict вызывающим не
     портит кэш.
   - Обоснование чисел — в docstring модуля: healthcheck раз в 30 с и монитор
     раз в 60 с видят данные не старше 15 с; поток неавторизованных `/health`
     даёт не больше одного вызова docker за 15 с; после пересборки образов
     здоровье возвращается за ≤ 15 с; таймаут 3 с укладывается в
     `timeout=4` healthcheck и 5 с монитора.
2. **`/health`.** `make_server(..., health_check=None)`: не None и не
   callable → `ValueError('invalid configuration')`, как прочие аргументы;
   хранится в `server.health_check`. В `Handler`: `health_check is None` →
   прежний `200 {"ok": true}`. Иначе ответ — результат вызова: статус 200,
   если в нём `ok is True`, иначе 503 с телом как есть. Исключение или не
   dict из `health_check` → `503 {"ok": false, "error":
   "provider_images_unknown"}`. Авторизация `/health` и `/v1/fetch` не
   меняются.
3. **Сервис.** `make_service(environ=None, *, fetcher_factory=None,
   health_check=None)`; `None` → `ImageCheck().status` (образы маршрута,
   docker через сокет). Передаётся в `make_server`. `main()` не менять.
4. **`--check-deploy`.** В `tests/deployed_m12b.py` константа
   `PROVIDER_IMAGES` — те же пять тегов, отсортированные (файл одиночный,
   `gateway` не импортирует; паритет с `route_images()` проверяет тест).
   В `check_deploy` сразу после `verify_release` и ДО чтения `compose.env`:
   один вызов через существующий хелпер `docker('image', 'ls', '--format',
   '{{.Repository}}:{{.Tag}}', '--filter', 'reference=<образ>', ...,
   timeout=30)` в порядке `PROVIDER_IMAGES` (не прежние 200 с по умолчанию:
   зависший Docker не должен держать `runner.lock`). Есть отсутствующие — провал: rc 1, stdout пуст,
   stderr и `check_deploy-result.json` ровно
   `{"ok": false, "internal_error": "provider_images_missing",
   "missing_images": [<по порядку PROVIDER_IMAGES>]}`; дальше проверка не
   идёт. Все на месте — проверка идёт дальше как прежде.
5. **`--check-bizprofile`.** Страница проходит, если `ok is True`,
   `provider` — непустая строка, у последней попытки тот же `provider`,
   `success is True`, `challenge == 'none'`, `error_type == 'none'` и маркер
   найден. У каждой строки `pages` в `bizprofile.json` (и архиве) — ключ
   `provider` (значение из ответа API; `null`, если страница упала
   исключением). Успех: rc 0, stdout ровно `{"ok": true, "mode":
   "check_bizprofile", "providers": {"home": ..., "card": ...}}`, файл
   `check_bizprofile-result.json` — `{"ok": true, "providers": {...}}`.
   Провал: rc 1, stderr и файл — `{"ok": false, "internal_error":
   "bizprofile_not_passed", "providers": {...}}`. Добавочные поля проходят
   через `redact`. Остальные режимы выводят ровно то же, что раньше.
6. **Тесты** (unittest, без сети и без Docker, подменой `subprocess.run` /
   `docker` / `worker_call`): в новом `tests/test_provider_images.py` —
   `route_images`, `ImageCheck` (все исходы, argv, кэш на границе 15 с,
   кэш отказа, одиночный вызов при одновременных `status()`, копия),
   `/health` через `make_server` (200/503/исключение/не callable/без
   проверки) и проводка `make_service`; в `tests/test_deployed_m12b.py` —
   паритет `PROVIDER_IMAGES`, провал и проход `check_deploy` по образам
   (с проверкой, что `verify_release` вызван до docker и `compose.env` не
   читается при провале), bizprofile
   через curl_cffi и смешанные провайдеры, `providers` в выводе и файлах,
   провал с `null`. Фейк `run_docker` в `MonitorLogTests` дополнить ответом
   на новую команду (все пять образов); существующие тесты не ослаблять.

Мутанты, которые новые тесты обязаны убивать: `>= ttl` → `> ttl`; кэш не
хранит отказ; снят замок; `status()` отдаёт сам кэш; пропущен один образ в
`route_images` или в `PROVIDER_IMAGES`; rc ≠ 0 считается «всё есть»;
исключение из `run` уходит наружу; `/health` отвечает 200 при `ok: false`;
`make_service` не передаёт проверку; проверка образов в `check_deploy` после
`compose.env` или без `missing_images`; bizprofile снова требует scrapling;
пропущено сравнение провайдера ответа и последней попытки; `providers` нет в
выводе успеха или провала.

## Не трогать

- Спеку `docs/specs/m28-provider-images-health.md` и файлы стенда
  `docs/specs/checks/m28_provider_images.py`,
  `docs/specs/checks/m28_stand.py`, `docs/specs/checks/m28_stand.sh` —
  критерии сверяют sha256.
- 🚨 Зону M27 и всё про прокси и Turnstile: `bench/` целиком (в том числе
  `bench/providers/docker/probe.py`, `bench/providers/registry.py`,
  Dockerfile провайдеров, `bench/runner/`), `gateway/oneshot.py`,
  `gateway/fetch.py`, `gateway/product.py`, `gateway/sessions.py`.
- `gateway/health_monitor.py`, `gateway/mcp_stdio.py`, `gateway/client.py`,
  `deploy/` (compose и Dockerfile), `scripts/`, `README.md`, `docs/`,
  `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`, `tests/probe_*.py`,
  `tests/fixtures/`, `tests/mutation_gate*.py`, прочие тесты. Существующие
  тесты не ослаблять и не удалять.
- Боевой сервис, его контейнеры и образы хоста: никаких `docker rm`, `rmi`,
  `tag`, `build`, `prune`, `compose`. Стенд из docker только читает список
  образов.
- 🚨 Репозиторий публичный: ни доменов, ни IP, ни имён хостов, ни путей
  `/home/...`; в тестах — `.invalid`/`.example`.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Файлы стенда не изменены, чекер M28 печатает ok:
  `bash -c 'printf "%s\n" "414ef8205b9f612d559801bea9222d4130c1d4d392f3313d1cbd8b4b78631b84  docs/specs/checks/m28_provider_images.py" "c55f372aa1d799a368310a43628a0bd6972fb19f22711043c200ef39f474c0e0  docs/specs/checks/m28_stand.py" "1fdf8d9fae00c14dc291f61280823ffae87d24f89bfcdae44e5f6157ac8a78c0  docs/specs/checks/m28_stand.sh" | sha256sum -c --quiet && test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m28_provider_images.py)" = ok'`
- **AC-003.** Стенд: все образы маршрута на хосте, сервис из клона в рантайм-образе отвечает 200 и healthcheck compose проходит:
  `bash -c 'test "$(bash docs/specs/checks/m28_stand.sh present)" = ok'`
- **AC-004.** Стенд: один образ маршрута отсутствует, /health отвечает 503 с этим тегом и healthcheck compose падает:
  `bash -c 'test "$(bash docs/specs/checks/m28_stand.sh absent)" = ok'`
- **AC-005.** Новые тесты красные без правки: не меньше трёх падений в каждом из двух модулей на коде BASE:
  `bash -c 'b=$(git merge-base HEAD origin/main) && t=$(mktemp -d) && git archive HEAD | tar -x -C "$t" && for f in gateway/api_http.py gateway/httpapi.py gateway/service.py tests/deployed_m12b.py; do git show "$b:$f" > "$t/$f" || exit 1; done && docker run --rm --network none --user 1002:1002 -v "$t":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -c "import io, sys, unittest; red = lambda name: (lambda r: len(r.failures) + len(r.errors))(unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromName(name))); counts = [red(n) for n in (\"tests.test_provider_images\", \"tests.test_deployed_m12b\")]; print(counts); sys.exit(0 if min(counts) >= 3 else 1)"'`
- **AC-006.** Изменения только в разрешённых путях, новые файлы есть, дерево чистое:
  `bash -c 'b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)docs/specs/m28-provider-images-health.md" ":(exclude)docs/specs/checks/m28_provider_images.py" ":(exclude)docs/specs/checks/m28_stand.py" ":(exclude)docs/specs/checks/m28_stand.sh" ":(exclude)gateway/provider_images.py" ":(exclude)gateway/api_http.py" ":(exclude)gateway/httpapi.py" ":(exclude)gateway/service.py" ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)tests/test_provider_images.py" && for f in gateway/provider_images.py tests/test_provider_images.py gateway/api_http.py tests/deployed_m12b.py; do test -n "$(git diff --name-only "$b" HEAD -- "$f")" || exit 1; done && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

AC-005 подменяет на копии дерева четыре боевых файла версиями BASE (новый
модуль `gateway/provider_images.py` остаётся) и требует, чтобы новые тесты
это заметили: падения проводки `/health` и `make_service` в
`tests.test_provider_images`, падения `check_deploy` и bizprofile в
`tests.test_deployed_m12b`. Стенд: рантайм-образ по ID, сеть `none`, клон
только на чтение, сокет docker; сервис собирается `make_service` без
`main()` (никакой зачистки чужих контейнеров), команда healthcheck берётся
дословно из `deploy/compose.yaml`. Нет образа стенда или образов маршрута на
хосте — `blocked` с дословным выводом в `note`, а не правка стенда или кода.

## Порядок работы

Пункт 1, его тесты, затем 2–3 и стенд (AC-003, AC-004), затем 4–5 и чекер
(AC-002), в конце AC-005, AC-001, AC-006. На падении чекера читать
расхождение, а не подбирать ожидания: ожидания посчитаны на эталоне и на BASE.

## Авторевью

Перекрёстное ревью этой вехи проводит постановщик при приёмке (свой разбор
диффа, два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека и файлы стенда уже закоммичены в `main` до создания клона. Если они
всё же приехали в клон untracked, закоммитить спеку
`docs/specs/m28-provider-images-health.md` и файлы стенда вместе с работой без правок
содержимого — AC-002 сверяет sha256 файлов стенда, AC-006 эти четыре пути
исключает из проверки границ и требует чистого дерева.

## Контракт отчёта

`report.json` в корне клона, untracked, ровно 6 записей AC-001…AC-006,
`command` посимвольно из спеки:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда из спеки>", "rc": 0, "note": "<улика>"}]}
```

`blocked` — `"rc": null` и дословная ошибка в `note`. Обходить
несовместимость запрещено (`--no-deps`, `|| true`, `set +e` в команде и т. п.).

## Контракт на невыполнимое

Остановиться и записать один список blocker с уликами в `report-blocked.md`,
если: стенд или чекер требуют поведения, противоречащего спеке; для зелёных
критериев нужна правка вне разрешённых файлов (в том числе в зоне M27 или в
`deploy/`); замороженная проба M12 падает от новой проводки `/health`;
на хосте нет рантайм-образа стенда или образов маршрута (стенд печатает
`blocked`). Спеку, стенд, чекер, критерии и BASE не менять, rc не выдумывать,
наружу ничего не публиковать, образы и контейнеры хоста не трогать.

## Стыки с соседними вехами

С M27 не пересекается по файлам. Если M27 поменяет набор провайдеров
маршрута или теги образов, `route_images()` подхватит это из `plan_product`
и реестра сам, а `PROVIDER_IMAGES` в `tests/deployed_m12b.py` поймает тест
паритета — менять его придётся в той же вехе.

**После приёмки — шаг постановщика:** README (абзац «healthcheck и
`--check-deploy` не видят отсутствия образов» и требование Scrapling в
bizprofile), CHANGELOG, выкладка сервиса с живой проверкой `--check-deploy`
и `--check-bizprofile`.

BASE_SHA: (ставится отдельным коммитом сразу после коммита этой спеки)
