# M25 — ступень patchright кликает по чекбоксу Turnstile

## Шапка и где работать

Репозиторий ai-browser-gateway, 24.11.2026. **Запускать только после
приёмки M24** (детектор CF) и её слияния в `main`: базовый коммит — вершина
`main` в момент создания клона, в нём уже есть код M24, эта спека и чекер
`docs/specs/checks/m25_turnstile_click.py`. Критерий границ считает дифф
от `git merge-base HEAD origin/main`, поэтому клон делается только
`make_clone.sh`. Исполнитель — `auto`; мутации по новым тестам потом гоняет
противоположный исполнитель отдельной вехой.

Новая ветка: `m25-turnstile-click`. Живое дерево постановщика не трогать.
git pull в клоне не делать; push в origin запрещён, работу заберёт постановщик через `git fetch` из клона.

## Задача и почему

Диагноз — `docs/research/13-cloudflare-turnstile.md`, п. «Patchright» и
вариант 4. Сейчас ступень patchright на заглушке Cloudflare отдаёт 403 за
~1 с: она ждёт только JS-вызов (`javascript_required`), а на управляемом
вызове нужен клик по чекбоксу Turnstile. Ожидание без клика замерено и не
помогает. Scrapling кликает и проходит, но за 15–25 с; patchright с кликом
по образцу Byparr проходит за ~7 с (замер ниже), то есть лестница при
дефолтном бюджете 30 с кончается на второй ступени, не доходя до scrapling.

Веха добавляет в `PatchrightAdapter` (и только в него) ожидание заглушки с
кликом: найти контейнер `input[name="cf-turnstile-response"]`, кликнуть в
точку (x+25, середина по высоте), повторить через ~4 с, не кликать при уже
заполненном токене, считать успехом исчезновение заглушки плюс cookie
`cf_clearance`. Бюджеты не растут.

## Что проверено вживую, а что предположение

Проверено постановщиком 24.11.2026:

- **Byparr**, `src/challenge.py` на коммите
  `c81385f59ec978ef81909a273e514ca6d9ace2a9` (через GitHub API):
  `TURNSTILE_INPUT = 'input[name="cf-turnstile-response"]'`; контейнер —
  `page.locator(f"{TURNSTILE_INPUT} >> xpath=ancestor::div[{depth}]")` для
  `depth` 1…4, первый с `bounding_box` `width > 40` и `20 < height < 120`;
  клик `page.mouse.move(x + 25, y + height / 2)`, `mouse.down()`,
  `mouse.up()`; токен — `input_value()` первого такого input, непустой =
  «уже отвечено, не кликать»; пауза после клика `CLICK_COOLDOWN = 4`, после
  промаха `PROBE_INTERVAL = 0.5`, опрос `POLL_INTERVAL = 0.25`; «заглушка
  ушла» проверяется дважды с паузой 0,25 с. Комментарий у измерения
  контейнера: «running page scripts resets the challenge» — во время
  заглушки только локаторы, без `page.evaluate`. Признак заглушки у Byparr
  (`playwright-captcha`) — `script[src*="/cdn-cgi/challenge-platform/"]`;
  он ловит и пассивный JSD, поэтому здесь берётся путь `/h/` и заголовок.
- **Замер клика** (образ one-shot 0.1.6, patchright 1.62.3, Chrome 156,
  headful под xvfb, отдельный скрипт по образцу Byparr): scrapingcourse,
  steamdb, gitlab sign-in — 12 из 12 проходов за 6,3–7,3 с от начала
  `goto`, каждый раз ровно два клика (первый через ~1,5 с ложится до
  готовности виджета, второй через 4 с проходит), цепочка документов
  `307 → 403 → 200`, `cf_clearance` есть. Контроль без клика (25 с):
  scrapingcourse и steamdb остаются на «Just a moment...», cookie нет.
  Контейнер на заглушке — 896×69 и 580×70 px (проходит границы Byparr).
- **Эталонная реализация постановщика** (черновая копия поверх эталона
  M24): чекер `m25_turnstile_click.py` — `ok` за ~26 с; на коде M24 без
  клика — падает по делу (11 расхождений). Полный сьют зелёный. Живой
  прогон шлюза с дефолтным бюджетом 30 с: steamdb и scrapingcourse — по три
  прогона, все `ok` через patchright, 200 `none`, ступень 6,9–8,2 с, итог
  8,4–9,7 с; gitlab — `ok` через patchright, 7,4 с; nowsecure — `ok` через
  curl_cffi (ступень не задействована).
- Код BASE (после M24): `PlaywrightAdapter.navigate` регистрирует
  `record` на `page.on("response")` до `goto`, читает DOM через
  `_document_and_body`, при `latest is not response` или
  `javascript_required` ждёт `_await_reload` (он зовёт
  `page.evaluate("document.readyState")`); `PatchrightAdapter` — подкласс с
  `package = "patchright"`; `_bound_timeout_ms(default)` режет по общему
  дедлайну `_DEADLINE`, `remaining_s()` бросает `TimeoutError` при
  исчерпании; сессия экспортируется `_browser_session` (cookies контекста +
  `navigator.userAgent`). Шлюз даёт ступени browser весь остаток бюджета
  (`gateway/product.py`, `run_product`).

Предположения: Cloudflare не сменит разметку контейнера до выпуска; клик
из контейнера в кадре 1280×720 без прокрутки (на всех замеренных заглушках
виджет в первом экране).

## Что сделать

Только `bench/providers/docker/probe.py` и тесты.

1. **Когда включается.** В `PlaywrightAdapter.navigate`, после первого
   чтения DOM и ДО существующей ветки ожидания JS, только если
   `self.package == "patchright"`: вердикт `detect_challenge(status,
   headers, body)` — `suspected` или `interactive`, среди правил есть
   `header_cf_mitigated` (заголовок ставит край Cloudflare, телом страницы
   его не подделать) И `body_just_a_moment` или `body_cf_chl_opt`. Тело
   заглушки без заголовка — без клика и без ожидания. Иначе поведение прежнее
   (playwright, страницы без заглушки, 403 Akamai — без ожидания вообще).
2. **Потолок ожидания.** Сначала `limit = _bound_timeout_ms(10_000)`
   (сама функция режет только по ВСЕМУ остатку, пополам не делит), затем,
   если общий дедлайн задан, `limit = min(limit, int(_DEADLINE.remaining_s()
   * 1000 / 2))`; при `TimeoutError` — не ждать.
   Константа 10 000 мс в модуле с комментарием-происхождением (замер:
   проход за ≤7,3 с; половина остатка оставляет scrapling время, если клик
   не прошёл).
3. **Цикл** (опрос каждые 250 мс через `page.wait_for_timeout`):
   - заглушка считается ушедшей, если заголовок страницы не содержит
     «just a moment» (без учёта регистра) И
     `page.locator('script[src*="/cdn-cgi/challenge-platform/h/"]').count()
     == 0`; проверка дважды с паузой 250 мс; успех — ушла И в
     `page.context.cookies()` есть `cf_clearance`. Ушла без cookie — не
     успех, ждать дальше до потолка;
   - клик — когда наступило время следующей попытки: если токен
     `input[name="cf-turnstile-response"]` непустой — не кликать; иначе
     искать контейнер по Byparr (предки `div` 1…4, границы размера
     `width > 40`, `20 < height < 120`), клик в `(x + 25, y + height / 2)`
     через `page.mouse.move/down/up`; после клика следующая попытка через
     4 с, после промаха — через 0,5 с;
   - во время заглушки никаких `page.evaluate`/`frame.evaluate`: только
     `title()`, локаторы, `bounding_box`, `input_value`, `mouse`,
     `context.cookies()`; любое исключение Playwright в шаге цикла — шаг
     не удался, цикл продолжается;
   - у каждого вызова Playwright с параметром `timeout` (`bounding_box`,
     `input_value` и любых других, что понадобятся) — явный `timeout` не
     больше 1000 мс и не больше остатка потолка: штатные 30 с ожидания
     локатора не должны съесть бюджет;
   - клик только в точку внутри найденного контейнера токена, никаких
     кликов по другим элементам и «на всякий случай».
4. **После цикла.** Успех — перечитать DOM `_document_and_body` от
   последнего записанного документа и пройти существующую ветку ожидания
   (`latest is not response` → `_await_reload`), статус и заголовки — у
   последнего документа. Неуспех — вернуть прежний результат (403 с
   заглушкой, без `err`), чтобы лестница перешла к scrapling.
5. **Тесты** — новый класс в `tests/test_probe.py` на поддельной странице
   (без браузера, как в чекере), каждый отказ с проверкой ПРИЧИНЫ:
   проход со вторым кликом и точкой (x+25, середина); пауза между кликами
   3,5–5 с; без клика при заполненном токене; заглушка ушла без
   `cf_clearance` → прежний 403 (а с cookie тот же сценарий → 200);
   никогда не проходит → прежний 403 и потолок 10 с; потолок «половина
   остатка» при малом бюджете; контейнер, нарушающий ровно одну границу
   (ширина 40, высота 20, высота 120 — граничные значения), → нет клика;
   тело заглушки без `cf-mitigated` → нет клика и ожидания;
   `PlaywrightAdapter` → нет клика и ожидания; 403 Akamai → нет ожидания;
   ни одного `evaluate` пока заглушка на месте; сессия после прохода несёт
   `cf_clearance`. Таймеры в тестах сокращать патчем констант, где это не
   ломает смысл (паузу 4 с проверяет и чекер).

Мутанты, которые новые тесты обязаны убивать: сдвиг 25→26; пауза 4→1 с;
снят пропуск при заполненном токене; снято условие `cf_clearance`;
потолок 10→14 с; снята «половина остатка»; включение для playwright;
снята любая одна граница размера контейнера или строгое неравенство
заменено нестрогим; снято требование заголовка `cf-mitigated`;
`evaluate` в цикле.

## Не трогать

- Спеку `docs/specs/m25-patchright-turnstile-click.md` и чекеры
  `docs/specs/checks/m24_cf_detector.py`, `docs/specs/checks/m25_turnstile_click.py`,
  фикстуры `tests/fixtures/*` — критерии сверяют sha256.
- Детектор `detect_challenge`, `ScraplingAdapter`, `_playwright_body`
  (сделано в M24), `gateway/` (бюджеты и лестница), `deploy/`, `scripts/`,
  `README.md`, `docs/`, `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`.
- Версии patchright/playwright/Chrome/scrapling — без апгрейдов.
- Никаких кликов на уровне ОС, подмен отпечатков, сторонних решателей
  капчи и обращения к сервисам решения — только клик мышью Playwright.
- Старые `tests/mutation_gate*.py` не править; существующие тесты не
  ослаблять и не удалять.
- 🚨 Репозиторий публичный: новых доменов, IP и путей `/home/...` в тестах
  не писать; адреса — `.invalid`/`.example`.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Чекеры обеих вех не изменены и печатают ok:
  `bash -c 'printf "%s\n" "a92dd6e7ffa446540acc4d26ed073853d64fcede4b855ccd2f2fcc2016e23533  docs/specs/checks/m24_cf_detector.py" "087f0534692c114e7358c72ddaa974639d5c8398c250ef13592e1f2cafe76b2d  docs/specs/checks/m25_turnstile_click.py" | sha256sum -c --quiet && for c in m24_cf_detector m25_turnstile_click; do test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-003.** Живой прогон, steamdb трижды проходит ступенью patchright в дефолтном бюджете:
  `bash -c 'd=$(mktemp -d) && for i in 1 2 3; do docker run --rm --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://steamdb.info/ > "$d/$i.json" && jq -e ".ok and .provider == \"patchright\" and .attempts[-1].status == 200 and .attempts[-1].challenge == \"none\" and .elapsed_ms < 20000" "$d/$i.json" || exit 1; done'`
- **AC-004.** Живой прогон, scrapingcourse трижды проходит ступенью patchright в дефолтном бюджете:
  `bash -c 'd=$(mktemp -d) && for i in 1 2 3; do docker run --rm --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://www.scrapingcourse.com/cloudflare-challenge > "$d/$i.json" && jq -e ".ok and .provider == \"patchright\" and .attempts[-1].status == 200 and .attempts[-1].challenge == \"none\" and .elapsed_ms < 20000" "$d/$i.json" || exit 1; done'`
- **AC-005.** Живой прогон, страница без заглушки берётся первой ступенью, браузер не запускается:
  `bash -c 'd=$(mktemp -d) && docker run --rm --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://nowsecure.nl/ > "$d/out.json" && jq -e ".ok and .provider == \"curl_cffi\" and (.attempts | length) == 1" "$d/out.json"'`
- **AC-006.** Изменения только в разрешённых путях, дерево чистое:
  `bash -c 'b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" && test -n "$(git diff --name-only "$b" HEAD -- bench/providers/docker/probe.py)" && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

Живые критерии (AC-003…AC-005) ходят в сеть с адреса хоста. Сбой сети или
DNS — `blocked` с дословной ошибкой в `note`, а не правка кода. Если в
AC-003/AC-004 первая ступень curl_cffi сама получила 200 (сайт перестал
отдавать заглушку этому адресу), ступень patchright не проверена: статус
`blocked` с выводом `attempts` в `note`, а не `fail` и не правка кода.

## Порядок работы: сначала замер

До кода тестов прогнать AC-003 и AC-004 на своей реализации и записать в
`note` время ступени patchright по каждому прогону. Если клик не проходит
(заглушка остаётся, `cf_clearance` нет) — это не повод подбирать задержки
наугад: см. контракт ниже.

## Авторевью

Перекрёстное ревью этой вехи проводит постановщик при приёмке (свой разбор
диффа, два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека `docs/specs/m25-patchright-turnstile-click.md` уже закоммичена в `main` до создания клона. Если она всё же
приехала в клон untracked (клон сделан раньше), закоммитить её вместе с
работой без правок содержимого — критерий сверяет sha256 чекеров, а
критерий границ требует чистого дерева.

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

Остановиться и записать один список blocker с уликами в
`report-blocked.md` (по каждому живому прогону: время, число кликов,
заголовок страницы в конце, есть ли `cf_clearance`), если: клик по образцу
Byparr не проходит заглушку на steamdb или scrapingcourse хотя бы в одном
из трёх прогонов; проход не укладывается в потолок 10 с; для прохода нужно
что-то из запрещённого в «Не трогать» (клик ОС, апгрейд, другой браузер,
решатель); чекер требует поведения, противоречащего спеке; нужна правка
вне разрешённых файлов. Спеку, чекеры, критерии и BASE не менять, rc не
выдумывать, наружу ничего не публиковать.

## Стыки с соседними вехами

Опирается на M24: заглушка по телу главного фрейма даёт `suspected` с
`body_just_a_moment`/`body_cf_chl_opt`, iframe виджета в тело не попадает.
Обещает следующим: успешный проход patchright экспортирует сессию с
`cf_clearance` (кэш сессий шлюза), при неудаче — прежний 403 и не меньше
половины остатка бюджета для scrapling. Выпуск образа, CHANGELOG и замер
серии на других целях делает постановщик после приёмки.
