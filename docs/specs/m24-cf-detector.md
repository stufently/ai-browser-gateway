# M24 — пройденная Cloudflare-страница не отвергается детектором

## Шапка и где работать

Репозиторий ai-browser-gateway, 24.11.2026. Базовый коммит — вершина `main`
в момент создания клона; в нём уже лежат эта спека, чекер
`docs/specs/checks/m24_cf_detector.py` и четыре новые фикстуры. Критерий
границ считает дифф от `git merge-base HEAD origin/main`, поэтому клон
делается только `make_clone.sh` (обычный `git clone`, ветка `origin/main`
в клоне есть). Исполнитель — `auto`; мутации по новым тестам потом гоняет
противоположный исполнитель отдельной вехой.

Новая ветка: `m24-cf-detector`. Живое дерево постановщика не трогать.
git pull в клоне не делать; push в origin запрещён, работу заберёт постановщик через `git fetch` из клона.

## Задача и почему

Диагноз — `docs/research/13-cloudflare-turnstile.md` (прочитать целиком до
начала). Коротко: scrapling с нашего адреса ПРОХОДИТ управляемый вызов
Cloudflare (200, настоящий контент, cookie `cf_clearance`), а шлюз отвергает
результат по двум ложным срабатываниям. Веха чинит оба и третье, найденное
постановщиком при подготовке:

1. **Устаревший `cf-mitigated` у scrapling.** `StealthySession.fetch` в
   scrapling 0.4.15 берёт статус у последнего документа, а заголовки — у
   ПЕРВОГО ответа (`ResponseFactory.from_playwright_response`:
   `"status": final_response.status`, `"headers": first_response.all_headers()`).
   Первый ответ — 403 вызова с `cf-mitigated: challenge`. Нынешнее вето по
   словам (`_SCRAPLING_CHALLENGE_STRINGS`, коммит 36ca2c6) снимает заголовок
   только на теле без слов `turnstile`/`recaptcha`/…, а страницы входа и
   демо Turnstile их содержат всегда.
2. **Пассивные скрипты Cloudflare считаются решающими правилами.**
   `/cdn-cgi/challenge-platform/scripts/jsd/` (JSD) и загрузчик встроенного
   виджета `challenges.cloudflare.com/turnstile/v0/api.js` вместе дают два
   решающих правила тела → `suspected` на обычной странице 200.
3. **Patchright читает iframe виджета Turnstile как тело страницы.**
   `_playwright_body` склеивает содержимое всех фреймов; iframe с
   `challenges.cloudflare.com` несёт `cf_chl_opt` и имя хоста — снова два
   решающих правила на настоящей странице.

Что сломается и чинится в этой же вехе: тесты, которые использовали
JSD-путь как «независимый признак CF» для вердикта `captcha`, и тесты вета
по словам (список — в разделе «Что сделать», п. 4).

## Что проверено вживую, а что предположение

Проверено постановщиком 24.11.2026 (образ one-shot 0.1.6, scrapling 0.4.15,
patchright 1.62.3, Chrome 156; Docker под пользователем 1002):

- Код BASE: `detect_challenge` в `bench/providers/docker/probe.py` —
  решающие правила `_BODY_RULES` (5 штук), `body_enough` = заголовок «just a
  moment» или ≥2 решающих; `captcha_confirmed = bool(decisive_body or status
  in (403, 429))`; заголовок `cf-mitigated` решает вердикт раньше тела.
  `ScraplingAdapter.navigate` снимает заголовок только при пустом пересечении
  с `_SCRAPLING_CHALLENGE_STRINGS`. `_playwright_body(page, sentinel)` читает
  `frame.content()` у каждого `page.frames`. `run_probe` зовёт
  `detect_challenge(status, headers, body)` по результату адаптера.
- scrapling 0.4.15 `StealthySession.fetch` принимает `page_setup` («runs
  before navigation… register event listeners») и вызывает его ДО
  `page.goto`; `response.cookies` — кортеж словарей с ключом `name`.
- Живой прогон scrapling с `page_setup`, записывающим ответы-документы
  главного фрейма: scrapingcourse и gitlab — цепочка `307 → 403 (cf-mitigated)
  → 200 (без cf-mitigated)`, у `response.headers` всё ещё `cf-mitigated:
  challenge`, в `response.cookies` есть `cf_clearance`.
- На текущем коде (BASE) по фикстурам: gitlab `200`/без заголовков → `none`,
  с `cf-mitigated` → `suspected`; scrapingcourse `200` → `none` (одно правило
  `body_cf_challenges_host`); nowsecure `200` → `suspected`
  (`body_cf_challenges_host`, `body_cf_challenge_platform`,
  `body_captcha_interactive`); обе заглушки → `suspected`, шесть правил.
- Эталонная реализация постановщика (черновая копия, в репо не попала):
  все проверки чекера `m24_cf_detector.py` — `ok`; на BASE чекер падает по
  делу (12 расхождений). Полный сьют на эталоне: из прежних тестов падают
  ровно те, что перечислены в п. 4 ниже, после замены JSD-литерала в
  `tests/test_detect.py` — только три теста lowendtalk и семь тестов
  scrapling. Замороженные пробы (125) зелёные.
- Живой прогон шлюза на эталоне (образ 0.1.6 с примонтированными `bench/`,
  `gateway/`, `probe.py`, бюджет 90 с): gitlab — `ok`, scrapling 200 `none`
  за 16,0 с; scrapingcourse — `ok`, scrapling 200 `none` за 25,5 с;
  nowsecure — `ok`, curl_cffi 200 `none`; steamdb с `--no-browser` — `ok:
  false`, первая попытка `challenge: suspected` (заглушка по-прежнему
  ловится). Patchright на nowsecure без п. 3 — `suspected` (iframe виджета),
  с п. 3 — `none` (дважды).

Предположение: формулировки JSD-пути и загрузчика виджета стабильны у
Cloudflare (видны на всех замеренных страницах 18.09 и 24.11.2026).

## Что сделать

### 1. Детектор: пассивные скрипты не решают (`detect_challenge`)

- `body_cf_challenge_platform` срабатывает, только если в теле есть
  вхождение `/cdn-cgi/challenge-platform`, НЕ продолжающееся
  `/scripts/jsd/` (сравнение без учёта регистра, как сейчас).
- `body_cf_challenges_host` срабатывает, только если в теле есть вхождение
  `challenges.cloudflare.com`, НЕ продолжающееся `/turnstile/v0/api.js`.
- Всё остальное в детекторе не меняется: состав и порядок имён правил,
  `body_enough`, `captcha_confirmed`, приоритет заголовка, Qrator, PX, Akamai.
- Следствие, которое проверяет чекер: виджет на странице 200 без
  заглушки — `none` (`body_captcha_interactive` в именах остаётся), тот же
  виджет на 403 — `captcha`; JSD + загрузчик на 200 — `none` без правил.
- В `RULE_PROVENANCE` у двух правил допустимо дописать провенанс исключений
  (`fixture:cf_jsd_turnstile_widget_200.html`) — по желанию.

### 2. Scrapling: заголовки последнего документа (`ScraplingAdapter.navigate`)

- В `session.fetch` передавать `page_setup` — функцию, которая вешает
  `page.on("response", …)` и записывает ответы, у которых
  `request.resource_type == "document"` и `frame == page.main_frame`.
  Исключения внутри обработчика глушить (обработчик не должен ронять fetch).
- Если записанный ПОСЛЕДНИМ такой ответ есть и его `status` равен статусу
  ответа scrapling — заголовки результата берутся у него
  (`_normalize_headers(response.headers)`), а не у ответа scrapling.
- Иначе (обработчик не сработал, статус не совпал) — запасное правило:
  `cf-mitigated` снимается, только если статус 2xx,
  `detect_challenge(status, None, body)[0] == "none"` И в
  `response.cookies` есть cookie с именем `cf_clearance`. Отсутствующий или
  `None` `cookies` — значит cookie нет.
- Вето по словам удалить целиком: `_SCRAPLING_CHALLENGE_STRINGS`,
  `_SCRAPLING_STALE_CF_HEADER_RULES`, `_scrapling_only_jsd_platform_paths`,
  `_scrapling_has_challenge_strings`.
- Прочие поля результата (`final_url`, `redirects`, `session`) не меняются;
  словарь заголовков ответа scrapling на месте не мутировать.

### 3. Patchright/playwright: iframe виджета — не тело (`_playwright_body`)

Не читать фрейм, если он не главный (`frame is not page.main_frame`) и
хост его `url` — `challenges.cloudflare.com`. Главный фрейм читается всегда.
Поддельные страницы старых тестов не имеют `main_frame` или `url` у фрейма —
отсутствие атрибута значит «фрейм читать» (старые тесты обязаны остаться
зелёными без правок).

### 4. Тесты

Существующие, которые ломаются по замыслу (проверено на эталоне), — правятся
так, чтобы сохранить их смысл:

- `tests/test_detect.py`: во всех тестах, где JSD-скрипт
  `/cdn-cgi/challenge-platform/scripts/jsd/main.js` служил независимым
  признаком CF, заменить его на `/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1`.
  Ожидания lowendtalk: на 200 — `("none", ("body_captcha",))`; на 403 —
  `("access_denied", ("body_captcha", "status_403"))`; тест «со вторым
  признаком» дополнить скриптом orchestrate — тогда `suspected` с
  `body_cf_chl_opt`, `body_cf_challenge_platform`, `body_captcha`.
- `tests/test_probe.py`, `ScraplingAdapterTests`: тесты
  `test_scrapling_drops_stale_cf_header_on_clean_2xx`,
  `…_with_platform_and_noindex`, `…_with_ad_referrer_token`,
  `…_with_only_jsd_paths`, `…_with_mixed_case_jsd_paths`,
  `…_with_jsd_and_ordinary_words`,
  `test_scrapling_keeps_missing_and_empty_headers_distinct` — дать ответу
  `cookies` с `cf_clearance` (запасное правило). Тест
  `test_scrapling_preserves_cf_header_with_jsd_and_challenge_strings`
  описывает удаляемое вето: переписать в пару «с `cf_clearance` заголовок
  снят, без него — остался».

Новые тесты (в `tests/test_detect.py` и `tests/test_probe.py`, `unittest`,
без сети), каждый отказ — с проверкой ПРИЧИНЫ:

- все четыре новые фикстуры и `cf_interstitial_200body_403.html`: точные
  вердикты на 200 и 403 (как в чекере);
- JSD отдельно, загрузчик отдельно, оба вместе — не решают; путь
  `challenge-platform` не-JSD и голый `challenges.cloudflare.com` — решают;
- scrapling, основной путь: поддельный `fetch` вызывает `page_setup` и
  эмитит `307 → 403 cf-mitigated → 200`, плюс ответ подфрейма и
  ответ-скрипт ПОСЛЕ 200 — в результате заголовки именно главного 200;
- scrapling, отказ основного пути по статусу: последний записанный документ
  с другим статусом не используется;
- scrapling, запасное правило: снимается на gitlab, scrapingcourse,
  nowsecure при `cf_clearance`; остаётся без `cf_clearance` (тело чистое —
  причина в cookie); остаётся на теле заглушки при `cf_clearance` (причина в
  теле); остаётся вне 2xx;
- patchright-тело: iframe `challenges.cloudflare.com` пропущен, обычный
  iframe прочитан, главный фрейм на этом хосте прочитан.

Мутанты, которые новые тесты обязаны убивать (их потом прогонит отдельная
веха): снять исключение JSD; снять исключение загрузчика; снять условие
`cf_clearance`; снять сравнение статуса; снять проверку `frame ==
main_frame` в записи ответов; читать iframe `challenges.cloudflare.com`;
не читать главный фрейм на хосте `challenges.cloudflare.com`.

### 5. Коммит

Всё — в ветке `m24-cf-detector`, сообщения короткие, повелительное
наклонение, без подписей.

## Не трогать

- Спеку `docs/specs/m24-cf-detector.md`, чекер
  `docs/specs/checks/m24_cf_detector.py`, фикстуры `tests/fixtures/*` и их
  README — постановщик положил их в BASE; критерии сверяют sha256.
- `gateway/`, `deploy/`, `scripts/`, `bench/` кроме `probe.py`, `README.md`,
  `docs/`, `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`.
- Версии пакетов и образов — без апгрейдов (решение владельца).
- `PlaywrightAdapter.navigate` и ожидание JS-вызова (`_await_reload`) —
  клик по Turnstile делает следующая веха.
- Старые обвязки `tests/mutation_gate*.py` не править: они относятся к
  прошлым вехам и в сьют не входят.
- Существующие тесты не ослаблять и не удалять, кроме правок из п. 4.
- 🚨 Репозиторий публичный: новых доменов, IP и путей `/home/...` в новых
  тестах не писать; для адресов — зоны `.invalid`/`.example`. Тела страниц
  брать только из фикстур.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Чекер вехи и фикстуры не изменены, чекер печатает ok:
  `bash -c 'printf "%s\n" "4cb49aa56948038c8534939be7f8b8ad0bf5a03ad86bbc0415ead43a1dd64950  docs/specs/checks/m24_cf_detector.py" "6588ce1e6d1289fd7d6e45234e80e8965a04e235f1056561dca3b6badb662ff8  tests/fixtures/cf_interstitial_200body_403.html" "1bba04ac5f99e5f80119c1e404dd7d857f8e2d03ebfb9ebf13cbef1e0d07c2ac  tests/fixtures/cf_jsd_turnstile_widget_200.html" "e12d7a8e234fb35ca3c163c7bbcc0a9817b65ea9269251d1cfadcd42d6c4e033  tests/fixtures/cf_managed_interstitial_403.html" "98304a0909fbe5a70e23991a5140983e7eeb7127ba3153e5c2d1f8342f124b3f  tests/fixtures/cf_passed_gitlab_signin_200.html" "a30e63e8e2b2e94ef2b3d2ee880fae8461a1b9ab428e76ac3520550bfe910823  tests/fixtures/cf_passed_scrapingcourse_200.html" | sha256sum -c --quiet && test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m24_cf_detector.py)" = ok'`
- **AC-003.** Тесты вехи используют все четыре новые фикстуры:
  `bash -c 'for f in cf_passed_gitlab_signin_200 cf_passed_scrapingcourse_200 cf_jsd_turnstile_widget_200 cf_managed_interstitial_403; do grep -q "$f.html" tests/test_detect.py tests/test_probe.py || exit 1; done'`
- **AC-004.** Вето по словам удалено из адаптера:
  `bash -c '! grep -nE "_SCRAPLING_CHALLENGE_STRINGS|_scrapling_has_challenge_strings|_SCRAPLING_STALE_CF_HEADER_RULES|_scrapling_only_jsd_platform_paths" bench/providers/docker/probe.py tests/test_probe.py'`
- **AC-005.** Живой прогон, страница входа за управляемым вызовом принята:
  `bash -c 'd=$(mktemp -d) && docker run --rm --init --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://gitlab.com/users/sign_in --budget-ms 90000 > "$d/out.json" && jq -e ".ok and .attempts[-1].status == 200 and .attempts[-1].challenge == \"none\"" "$d/out.json"'`
- **AC-006.** Живой прогон, страница после вызова с встроенным Turnstile принята:
  `bash -c 'd=$(mktemp -d) && docker run --rm --init --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://www.scrapingcourse.com/cloudflare-challenge --budget-ms 90000 > "$d/out.json" && jq -e ".ok and .attempts[-1].status == 200 and .attempts[-1].challenge == \"none\"" "$d/out.json"'`
- **AC-007.** Живой прогон, обычная страница 200 с JSD и виджетом принята первой ступенью:
  `bash -c 'd=$(mktemp -d) && docker run --rm --init --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://nowsecure.nl/ --budget-ms 90000 > "$d/out.json" && jq -e ".ok and .provider == \"curl_cffi\" and (.attempts | length) == 1" "$d/out.json"'`
- **AC-008.** Живой прогон, настоящая заглушка по-прежнему ловится:
  `bash -c 'd=$(mktemp -d); docker run --rm --init --user 1002:1002 -v "$PWD/bench":/opt/abg-src/bench:ro -v "$PWD/gateway":/opt/abg-src/gateway:ro -v "$PWD/bench/providers/docker/probe.py":/opt/abg/probe.py:ro ghcr.io/stufently/ai-browser-gateway-oneshot@sha256:bb1d5f0817d2db585def9389be12044ab19c9a7f578de735f5b5cba6aece195e https://steamdb.info/ --budget-ms 90000 --no-browser > "$d/out.json"; test $? -eq 1 && jq -e "(.ok | not) and .attempts[0].status == 403 and .attempts[0].challenge == \"suspected\"" "$d/out.json"'`
- **AC-009.** Изменения только в разрешённых путях, дерево чистое:
  `bash -c 'b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/test_probe.py" && test -n "$(git diff --name-only "$b" HEAD -- bench/providers/docker/probe.py)" && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

Живые критерии (AC-005…AC-008) ходят в сеть с адреса хоста. Сбой сети или
DNS — `blocked` с дословной ошибкой в `note`, а не правка кода.

## Авторевью

Перекрёстное ревью этой вехи проводит постановщик при приёмке (свой разбор
диффа, два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека `docs/specs/m24-cf-detector.md` уже закоммичена в `main` до создания клона. Если она всё же
приехала в клон untracked (клон сделан раньше), закоммитить её вместе с
работой без правок содержимого — критерий сверяет sha256 чекеров, а
критерий границ требует чистого дерева.

## Контракт отчёта

`report.json` в корне клона, untracked, ровно 9 записей AC-001…AC-009,
`command` посимвольно из спеки:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда из спеки>", "rc": 0, "note": "<улика>"}]}
```

`blocked` — `"rc": null` и дословная ошибка в `note`. Обходить
несовместимость запрещено (`--no-deps`, `|| true`, `set +e` в команде и т. п.).

## Контракт на невыполнимое

Остановиться и записать один список blocker с уликами в
`report-blocked.md`, если: чекер требует поведения, противоречащего этой
спеке; существующий тест вне перечисленных в п. 4 падает из-за требования
спеки; нужна правка вне разрешённых файлов; `page_setup` не вызывается
настоящим scrapling 0.4.15 в образе (живые AC-005/AC-006 падают при
зелёном чекере); живой прогон показывает, что заглушка проходит как
`none`. Спеку, чекер, фикстуры, критерии и BASE не менять, rc не выдумывать,
версии пакетов не поднимать, наружу ничего не публиковать.

## Стыки с соседними вехами

Следующая веха (клик по Turnstile в ступени patchright) опирается на то,
что эта веха гарантирует: заглушка Cloudflare по телу главного фрейма даёт
`suspected` с правилами `body_just_a_moment` и `body_cf_chl_opt`, а
пройденная страница с виджетом или JSD — `none`; iframe виджета в тело не
попадает. Выпуск образа и запись в CHANGELOG делает постановщик после
приёмки.
