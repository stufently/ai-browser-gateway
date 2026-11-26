# M29 — пароль прокси вне окружения процессов браузера

## Шапка и где работать

Репозиторий ai-browser-gateway, 26.11.2026.

BASE_SHA: (вписывается следующим коммитом после коммита спеки и стенда)

Клон делается от вершины `main` не раньше BASE_SHA; в базе есть выпуск
0.1.8 (M27 — локальный релей прокси, M28 — проверка образов провайдеров),
эта спека и стенд `docs/specs/checks/m29_stand.sh`. Критерий границ
считает дифф от `git merge-base HEAD origin/main`, поэтому клон делается
только `make_clone.sh`. Исполнитель — `cx`; мутации по новым тестам потом
гоняет противоположный исполнитель отдельной вехой.

Новая ветка: `m29-proxy-env`. Живое дерево постановщика не трогать.
git pull в клоне не делать; push в origin запрещён, работу заберёт
постановщик через `git fetch` из клона. Образы стенда постановщик стянул
заранее: one-shot 0.1.8, `gogost/gost:3.3.3`, `python:3.14.7-slim-bookworm`
(дайджесты — в стендах).

## Задача и почему

Креды прокси приходят пробе (`bench/providers/docker/probe.py`) через
переменную окружения `ABG_PROXY`: one-shot и сервис передают её по имени
(`docker run -e ABG_PROXY`, `LocalLauncher` в `gateway/oneshot.py`,
`bench/runner/fetch.py`). Проба читает её из `os.environ` в момент
использования (`_proxy_url`, `urlopen`, `redact`) и само окружение не
трогает. Поэтому всё, что проба запускает, наследует пароль: драйвер
Playwright/Patchright (`node … cli.js run-driver`), главный процесс Chrome
и его `chrome_crashpad_handler`, а у адаптера `curl` — ещё и `ALL_PROXY`
с кредами в окружении `curl`. С M27 браузер ходит к прокси через релей на
127.0.0.1 и кредов не получает ни в флагах, ни через CDP, но пароль всё
ещё лежит в `/proc/<pid>/environ` процессов браузера, которые исполняют
недоверенный веб-контент.

Цель вехи: ни один дочерний процесс пробы не получает `ABG_PROXY` (и
кредов прокси в любой другой переменной); поведение пробы снаружи не
меняется.

## Что проверено вживую, а что предположение

Проверено постановщиком 26.11.2026 на образе one-shot 0.1.8 (patchright
1.62.3, scrapling 0.4.15, Chrome 156) стендом `m29_stand.sh`:

- На BASE стенд падает у обоих провайдеров: `LEAK` у главного процесса
  `/opt/google/chrome/chrome`, у обоих `chrome_crashpad_handler` и у
  драйвера `…/patchright/driver/node … run-driver`. Дочерние процессы
  Chrome (renderer, gpu, utility, zygote) уже `clean` — Chrome чистит им
  окружение сам.
- Эталонная правка (черновая копия, не в репозитории): в начале `main()`
  забрать значение `os.environ.pop("ABG_PROXY", "")` в переменную модуля,
  а `_proxy_url`, `urlopen` и `redact` читать из неё — стенд `ok` у
  patchright и scrapling, страница через прокси с паролем читается.
- `xvfb-run`, `Xvfb`, `docker-init` и сам процесс `python3 probe.py`
  показывают `LEAK` и после правки: они получили переменную от docker или
  от родителя до старта пробы, а `unsetenv` не стирает исходный блок
  окружения процесса. Это вне скоупа вехи (см. «Решения постановщика»).

Предположение (живьём не проверено): адаптер `curl` (провайдер
бенчмарка, в лестнице one-shot его нет) принимает прокси из конфига на
stdin (`curl --config -`, строка `proxy = "<url>"`), как документирует curl.

## Решения постановщика

- **Скоуп — процессы, которые запускает проба:** драйвер, Chrome, `curl`.
  Как креды доходят до пробы (переменная `ABG_PROXY` от docker/one-shot/
  сервиса), не меняется: это интерфейс скила и сервиса. Процессы-родители
  пробы (`docker-init`, `xvfb-run`, `Xvfb`) и исходный блок окружения
  самой пробы остаются как есть.
- **Одно чтение.** Проба забирает `ABG_PROXY` из `os.environ` один раз,
  в самом начале `main()`, до разбора аргументов и до любого запуска
  дочернего процесса, и удаляет её оттуда (`pop`). Дальше все места,
  которым нужен прокси (`_proxy_url`, `urlopen`, `redact`, адаптеры,
  `_browser_proxy`), берут значение из одного источника в модуле.
  Пустое или отсутствующее значение — «прокси нет», как раньше.
- **Без `main()` (тесты и чекеры зовут `run_probe` и адаптеры напрямую с
  `os.environ["ABG_PROXY"]`)** поведение прежнее: пока `main()` не
  забрал переменную, источник — `os.environ`. Существующие тесты, которые
  ставят `ABG_PROXY` через `mock.patch.dict(os.environ, …)`, не должны
  меняться ради этой вехи; если тест всё же приходится править — только
  потому, что он проверял само наследование окружения, и с объяснением
  в `note` AC-001.
- **`curl`.** `CurlAdapter.navigate` больше не кладёт прокси в окружение
  (`ALL_PROXY`) и не ставит его в argv. Прокси передаётся конфигом curl
  на stdin: `--config -` в argv и `proxy = "<url>"` во входе процесса
  (`input=` у `subprocess.run`), с экранированием `\` и `"` по правилам
  конфига curl. Окружение потомка curl — копия окружения пробы, в которой
  нет `ABG_PROXY` (после `main()` её нет и так; без `main()` её убрать
  явно) и нет `ALL_PROXY`/`HTTPS_PROXY`/`HTTP_PROXY` в любом регистре.
  Без прокси — прежний вызов без `--config -` и без `input`.
- **Браузеры.** `PlaywrightAdapter` (playwright и patchright) и
  `ScraplingAdapter` не передают драйверу и браузеру окружение с
  `ABG_PROXY`: после `main()` переменной уже нет в `os.environ`; без
  `main()` адаптеры ничего дополнительно не делают (браузер в тестах не
  запускается). `env=` в вызовы launch не добавлять.
- `redact` по-прежнему снимает пароль текущего прокси из текста ошибки:
  источник пароля — тот же единый источник, порядок замен не менять.

## Что сделать

Разрешённые файлы: `bench/providers/docker/probe.py`, `tests/test_probe.py`
(кроме класса `TurnstileClickTests`), новый `tests/test_proxy_env.py`.

1. Единый источник значения прокси в `probe.py` и забор переменной в
   начале `main()` — по «Решениям постановщика».
2. `urlopen`, `_proxy_url`, `redact` читают из единого источника.
3. `CurlAdapter.navigate` — прокси конфигом на stdin, чистое окружение.
4. Тесты в `tests/test_proxy_env.py` (unittest, без сети и без браузера):
   - после `main()` (с подменённым `run_probe`, ловящим вызов) в
     `os.environ` нет `ABG_PROXY`, а `_proxy_url()` и `redact` видят
     прежнее значение (пароль из URL вида `http://user1:s3cr%40t@proxy.invalid:8080`
     снимается из текста, в том числе в `unquote`-виде);
   - забор происходит ДО первого запуска потомка: подменённый
     `subprocess.Popen`/`run`, вызванный из подменённого `run_probe`,
     получает окружение без `ABG_PROXY`;
   - пустое `ABG_PROXY` после `main()` — прокси нет (`_proxy_url() == ""`);
   - `CurlAdapter.navigate` с прокси: argv содержит `--config` и `-` и не
     содержит ни URL прокси, ни пароля; `input` — ровно строка конфига
     `proxy = "…"` с экранированием `"` и `\`; в `env` нет `ABG_PROXY` и
     ни одной `*_proxy`-переменной в любом регистре; без прокси — нет
     `--config`, `input` не передан;
   - `urlopen` с прокси использует `ProxyHandler` с тем же значением,
     после `main()` тоже.
   Тест, который при BASE проходит, не доказывает ничего: каждый новый
   тест обязан падать на BASE (проверь, откатив `probe.py`).

## Не трогать

- Спеки и стенды прошлых вех (`docs/specs/m2*`, `docs/specs/checks/m2*`),
  спеку `docs/specs/m29-proxy-env.md` и стенд `docs/specs/checks/m29_stand.sh` —
  критерий сверяет sha256.
- 🚨 Зону M25 и класс `TurnstileClickTests`; `_ProxyRelay`,
  `_browser_proxy`, `_cancel_auth_handler` (M27) — логику не менять, только
  источник значения прокси, если он там читается.
- `gateway/`, `bench/runner/`, `bench/providers/registry.py`, Dockerfile'ы
  провайдеров, `deploy/`, `scripts/`, `README.md`, `docs/`, `TASKS.md`,
  `CHANGELOG.md`, `pyproject.toml`, `tests/probe_*.py`, `tests/fixtures/*`.
- Версии пакетов и образов — без апгрейдов; сторонних пакетов не добавлять.
- 🚨 Репозиторий публичный: ни одного настоящего прокси, логина, пароля,
  домена, IP или пути `/home/...`; в тестах — `.invalid`/`.example`,
  `127.0.0.1` и заглушки вида `user1:s3cr%40t`.

## Разрешения

Можно: читать весь репозиторий; гонять Docker под `--user 1002:1002`
(сьют, чекеры, стенды — стенды сами создают и удаляют свои сети и
контейнеры с префиксами `m27-`/`m29-`); локальные коммиты в ветке
`m29-proxy-env`. Нельзя: push, сеть наружу, `docker pull` (образы уже
есть; нет образа — `blocked`), установки на хост, sudo, правка чужих
контейнеров/сетей.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Стенды и чекеры не изменены, чекеры M24, M25 и M27 печатают ok:
  `bash -c 'printf "%s\n" "e6a3df5e97a120a3cf08084e529e61e186ea45a6b694cdecac86216427274187  docs/specs/checks/m29_stand.sh" "86449844e45d1b2ea7e3bdadd6caeca0c2a349a2719f04a052d82238e55f6fcc  docs/specs/checks/m27_proxy_relay.py" "37e4962e57e89386213a319f7edfe5a74e491c6b3703ee5b42e85b22aeafa09c  docs/specs/checks/m27_stand.sh" "c657ac0d254fa65fcbeb837b039964f00ec5be45bd59c9a3741c667a462877a0  docs/specs/checks/m27_target.py" "934e6b16c590b021fa0fb51c5d07edaadc108e503d81dd9f86a1507ade9a287f  docs/specs/checks/m26_proxy_ladder.py" "4aa0bedf53ea6949408a87504a95f25c5e85a4a97c71214b49a3479112992e49  docs/specs/checks/m26_stand.sh" "79cfb736d9eb73c0a107670c29b1e8e0de9b1ed983d525c47743970fec7f6074  docs/specs/checks/m26_target.py" "a92dd6e7ffa446540acc4d26ed073853d64fcede4b855ccd2f2fcc2016e23533  docs/specs/checks/m24_cf_detector.py" "087f0534692c114e7358c72ddaa974639d5c8398c250ef13592e1f2cafe76b2d  docs/specs/checks/m25_turnstile_click.py" | sha256sum -c --quiet && for c in m24_cf_detector m25_turnstile_click m27_proxy_relay; do test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 timeout 300 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-003.** Стенд: у patchright драйвер и Chrome без пароля прокси в окружении, страница через прокси с паролем читается:
  `bash -c 'test "$(bash docs/specs/checks/m29_stand.sh patchright)" = ok'`
- **AC-004.** Стенд: у scrapling драйвер и Chrome без пароля прокси в окружении, страница через прокси с паролем читается:
  `bash -c 'test "$(bash docs/specs/checks/m29_stand.sh scrapling)" = ok'`
- **AC-005.** Стенд M27 без изменений: релей, SOCKS5 с паролем, 401 сайта и неверный пароль, https-прокси:
  `bash -c 'for s in relay socks auth tls; do test "$(bash docs/specs/checks/m27_stand.sh $s)" = ok || exit 1; done'`
- **AC-006.** Стенд M26 без изменений: curl_cffi через прокси с паролем, SOCKS без кредов, совместимость с ABG_EGRESS_PROXY:
  `bash -c 'for s in http socks compat; do test "$(bash docs/specs/checks/m26_stand.sh $s)" = ok || exit 1; done'`
- **AC-007.** Изменения только в разрешённых путях, есть новый тест, дерево чистое:
  `bash -c 'git merge-base --is-ancestor BASE_FULL HEAD && b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/test_proxy_env.py" && test -n "$(git diff --name-only "$b" HEAD -- bench/providers/docker/probe.py)" && test -n "$(git diff --name-only "$b" HEAD -- tests/test_proxy_env.py)" && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

Стенд `m29_stand.sh` (смотри сам файл): прокси gost с паролем в
изолированных сетях, проба напрямую (`xvfb-run python3 probe.py`) с кодом
ветки поверх образа 0.1.8; пока проба жива, сканер внутри контейнера
читает `/proc/*/environ` и cmdline. Судятся процессы Chrome
(`chrome`/`chromium`/`headless_shell` в cmdline) и драйвера (`node`);
обязателен хотя бы один процесс каждого вида и ни одного `LEAK`; пароль
в сыром, `%40`- и base64-виде ищется ещё и в stdout, stderr и выводе
сканера. Браузер живёт около секунды, поэтому стенд повторяет прогон до
трёх раз, пока сканер не застанет оба вида процессов. Сбой Docker (нет
образа, не создаётся сеть) — `blocked` с дословной ошибкой в `note`, а
не правка стенда или кода.

## Порядок работы

До первой правки — первая половина AC-007 на свежем клоне:
`git merge-base --is-ancestor BASE_FULL HEAD && b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD`
(rc 0 обязателен, иначе blocker) и AC-003 (на BASE обязан печатать
`FAIL: пароль прокси в окружении процессов браузера: …`; другой FAIL —
blocker с выводом). Затем пункты 1–3, тесты п. 4 (каждый новый — красный
на BASE), затем AC-003, AC-004, AC-005, AC-006, AC-002 и полный сьют.

## Авторевью

Перекрёстное ревью проводит постановщик при приёмке (свой разбор диффа,
два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека `docs/specs/m29-proxy-env.md` и стенд уже закоммичены в `main` до
создания клона. Если они всё же приехали в клон untracked, закоммитить их
вместе с работой без правок содержимого — критерий сверяет sha256 стенда,
а критерий границ требует чистого дерева.

## Контракт отчёта

`report.json` в корне клона, untracked, ровно 7 записей AC-001…AC-007,
`command` посимвольно из спеки:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда из спеки>", "rc": 0, "note": "<улика>"}]}
```

`blocked` — `"rc": null` и дословная ошибка в `note`. Обходить
несовместимость запрещено (`--no-deps`, `|| true`, `set +e` в команде и т. п.).

## Контракт на невыполнимое

Остановиться и записать один список blocker с уликами в
`report-blocked.md` (вывод стенда, хвост `probe.err`), если: первая
половина AC-007 на свежем клоне не rc 0; AC-003 на BASE падает не на
`LEAK`; для зелёного стенда нужна правка вне разрешённых файлов, в зоне
M25 или в логике релея M27, или сторонний пакет; curl в образе не
принимает прокси из `--config -`; стенд или чекер требуют поведения,
противоречащего спеке. Спеку, стенды, чекеры, критерии и BASE не менять,
rc не выдумывать, наружу ничего не публиковать.

## Стыки с соседними вехами

Опирается на M27 (релей, 0.1.8). Обещает: дочерние процессы пробы не
получают `ABG_PROXY` и кредов прокси в окружении.

**После приёмки — шаг постановщика:** CHANGELOG, выпуск образа 0.1.9
(только с подтверждения владельца), пересборка образов провайдеров
сервиса, пины в скиле `abg-fetch` (ансибль) и check-sites CI.
