# M26 — вся лестница one-shot через один прокси

## Шапка и где работать

Репозиторий ai-browser-gateway, 24.11.2026. **Запускать только после
приёмки M25** (клик Turnstile в patchright,
`docs/specs/m25-patchright-turnstile-click.md`) и её слияния в `main`:
обе вехи правят `bench/providers/docker/probe.py`. Базовый коммит — вершина
`main` в момент создания клона; в нём уже есть код M25, эта спека и три
файла стенда `docs/specs/checks/m26_*`. Критерий границ считает дифф от
`git merge-base HEAD origin/main`, поэтому клон делается только
`make_clone.sh`. Исполнитель — `auto`; мутации по новым тестам потом гоняет
противоположный исполнитель отдельной вехой.

Новая ветка: `m26-proxy-ladder`. Живое дерево постановщика не трогать.
git pull в клоне не делать; push в origin запрещён, работу заберёт
постановщик через `git fetch` из клона. Образы стенда постановщик стянул
заранее: one-shot 0.1.6 и `gogost/gost:3.3.3` (дайджесты — в
`docs/specs/checks/m26_stand.sh`).

## Задача и почему

Владелец: «добавить поддержку прокси в скил», полный вариант — прокси на
КАЖДОЙ ступени, включая браузеры. Сейчас one-shot (`gateway/oneshot.py`)
знает только `ABG_EGRESS_PROXY`: это одна запасная ступень curl_cffi в
самом конце лестницы, браузеры идут с адреса хоста всегда. Нужен второй
режим — явный прокси, через который идёт вся лестница: curl_cffi,
patchright, scrapling.

Решения прошлых вех, на которые веха опирается и которые не меняет:

- Прокси уходит в процесс пробы только через окружение по имени
  `ABG_PROXY`, никогда через argv; direct-ступень прокси не наследует;
  разные вызовы не делят секреты (`docs/specs/m10-product-contract.md`,
  `docs/specs/m5-proxy.md`).
- Креды Playwright-семейства — отдельными полями `username`/`password`,
  Chromium userinfo из `server` игнорирует (`docs/specs/m5-proxy-fix.md`,
  функция `playwright_proxy`); `redact` вырезает userinfo из текста ошибки.
- Cookies решённого вызова привязаны к адресу, который его решил: сессии
  делят только ступени одного маршрута (`gateway/sessions.py`,
  `gateway/fetch.py`, `ProductFetcher`).
- Порядок лестницы: HTTP → patchright → scrapling → egress
  (`docs/research/06-two-egress.md`, `gateway/product.py`).

## Что проверено вживую, а что предположение

Проверено постановщиком 24.11.2026, образ one-shot 0.1.6 (curl_cffi
0.17.0, patchright 1.62.3, playwright 1.62.0, scrapling 0.4.15, Chrome
156.0.8078.47), Docker под 1002:1002, прокси gost 3.3.3 в изолированной
сети (`--internal`, цель доступна только через прокси):

- Проба (`probe.py`) уже применяет `ABG_PROXY` у всех трёх адаптеров
  (`CurlCffiAdapter`: `proxy=`; `PlaywrightAdapter.start` и
  `ScraplingAdapter.start`: `playwright_proxy(...)`). Не хватает только
  проводки в one-shot: `bench/runner/fetch.py::_fetch` кладёт `ABG_PROXY`
  в окружение пробы лишь у ступени с egress-профилем, а
  `plan_product` все ступени, кроме запасной, ставит на `direct`.
- 0.1.6 с `ABG_PROXY` в окружении контейнера его молча игнорирует:
  попытка `curl_cffi direct`, `provider_error` (DNS), 1 ступень.
- **Схемы по провайдерам** (каждая клетка — живой прогон пробы):

  | Прокси | curl_cffi | patchright | scrapling |
  |---|---|---|---|
  | `http://` без кредов | 200 | 200 | 200 |
  | `http://u:p@` | 200 | 200 | 200 |
  | `socks5://` без кредов | DNS-ошибка: имя цели резолвится на хосте | 200, имя резолвит прокси | 200, имя резолвит прокси |
  | `socks5://u:p@` | DNS-ошибка (то же) | `Browser does not support socks5 proxy authentication` | то же (`launch_persistent_context`) |
  | `socks5h://` без кредов / с кредами | 200 / 200 | `net::ERR_NO_SUPPORTED_PROXIES` | `net::ERR_NO_SUPPORTED_PROXIES` |
  | `https://u:p@` (TLS до прокси) | схема принята, TLS до прокси начат (`curl: (60)` на самоподписанном) | схема принята (`ERR_PROXY_CERTIFICATE_INVALID`) | не мерил, тот же Chromium |

  Следствия, заложенные в веху: браузерам `socks5h` отдаётся как `socks5`
  (Chromium и так резолвит имя у SOCKS5-прокси), curl_cffi `socks5`
  получает как `socks5h` (иначе имя цели резолвится с хоста — утечка DNS и
  расхождение с браузерами); SOCKS5 с паролем при включённых браузерах
  невозможен — отказ до запуска проб.
- В тексте ошибок выше пароля нет; Chrome запускается с
  `--proxy-server=http://<прокси>:8080` без кредов (видно в `docker top`).
- Стенд `docs/specs/checks/m26_stand.sh` и чекер
  `docs/specs/checks/m26_proxy_ladder.py` прогнаны на эталонной реализации
  постановщика (черновая копия, не в репозитории): чекер `ok`, все шесть
  сценариев стенда `ok` трижды подряд (5–20 с на сценарий); полный сьют и
  замороженные пробы на эталоне зелёные (789 и 125 тестов). На BASE чекер
  падает по делу (37 расхождений), стенд: `http`, `deny`, `compat` — FAIL,
  причём первая половина `compat` (только `ABG_EGRESS_PROXY`) на BASE
  проходит — это и есть эталон обратной совместимости.

Предположения (живьём не проверены): `https://`-прокси с доверенным
сертификатом проходит у всех трёх провайдеров (в стенде нет доверенного
TLS — проверены только приём схемы и начало рукопожатия); кэш сессий через
прокси живьём не гонялся — `ProductFetcher` работает с сессиями только для
`https://`-URL, а у стенда цель на `http://`; покрыто чекером без сети.

## Что сделать

Разрешённые файлы: `gateway/oneshot.py`, `gateway/product.py`,
`gateway/fetch.py`, `bench/providers/docker/probe.py` и тесты
`tests/test_oneshot.py`, `tests/test_probe.py`, `tests/test_gateway_product.py`,
`tests/test_gateway_fetch.py`, новый `tests/test_proxy_ladder.py`.

1. **Вход one-shot.** Новая опция `--proxy URL` и переменная `ABG_PROXY`.
   Опция сильнее переменной. `ABG_PROXY` пустая или из пробелов — прокси
   нет (как сейчас у `ABG_EGRESS_PROXY`). Проверка URL — как у
   `egress_profiles`: схема из `{http, https, socks5, socks5h}`, есть хост,
   порт разбирается, плюс нет пробельных и управляющих символов; иначе
   прежний отказ `{"error": "invalid_request"}`, rc 2. `--proxy ""` —
   тоже `invalid_request`.
2. **Креды не в argv.** `--proxy` с userinfo (логин, пароль или оба) —
   отказ rc 2, stderr ровно `{"error": "proxy_credentials_in_argv"}`
   (`json.dumps`), stdout пуст, ни одной пробы. Прокси с паролем передаётся
   только через `ABG_PROXY`.
3. **Неподдерживаемое сочетание.** Схема `socks5`/`socks5h` с userinfo и
   браузеры не выключены (`--no-browser` нет) — отказ rc 2, stderr ровно
   `{"error": "proxy_unsupported"}`, ни одной пробы. С `--no-browser` то же
   прокси разрешено (curl_cffi его умеет). Тихо пускать браузер напрямую
   ЗАПРЕЩЕНО: явный прокси значит «ни одна ступень не ходит с адреса хоста».
4. **Маршрут.** `ProductRequest` получает поле `route_profile: str =
   'direct'` (последним, чтобы позиционные вызовы не сдвинулись);
   валидация: непустая строка и не совпадает ни с одним из
   `egress_profiles`, иначе `ValueError`. `plan_product` ставит
   `route_profile` на ступени `entrance`, `http` и `browser`; ступени
   `egress` — как сейчас. С дефолтом план байт в байт прежний
   (замороженные пробы M10–M13 это проверяют). `gateway/api_http.py` и
   сервис не трогать: их белый список ключей поле не пропускает.
5. **Профили в one-shot.** С явным прокси: профиль `explicit` → URL прокси,
   `route_profile='explicit'`. Если задан и `ABG_EGRESS_PROXY`: значение
   ДРУГОЕ — запасная ступень `curl_cffi`/`proxy` остаётся последней, как
   сейчас; значение то же (сравнение строк после `strip`) — запасная
   ступень не добавляется (тот же адрес второй раз не пробуем). Без явного
   прокси поведение и вывод прежние, включая `egress_profile` в
   `attempts` (`direct`/`proxy`).
6. **Сессии.** `ProductFetcher(..., route='direct')`: сессии читаются и
   пишутся только у ступеней с `step.egress_profile == self.route` (сейчас —
   `egress is None`); запасная egress-ступень сессий не видит и не
   оставляет, как и прежде. `session_store` в one-shot с явным прокси
   кладёт сессии в подкаталог `ABG_SESSION_DIR/<scope>`, где
   `scope = 'proxy-' + sha256(identity).hexdigest()[:16]`,
   `identity = '|'.join((scheme, hostname, str(port or дефолт), unquote(username or '')))`,
   дефолт порта: http 80, https 443, socks5/socks5h 1080; `scheme` и
   `hostname` — как их отдаёт `urlsplit`. Пароль в `identity` не входит:
   смена пароля не меняет адрес выхода, а хэш от пароля в имени каталога —
   утечка. Без прокси каталог прежний (корень `ABG_SESSION_DIR`), старые
   файлы сессий остаются годными. `FileSessionStore` не менять: подкаталог
   он создаёт сам (`mkdir(mode=0o700, parents=True)`).
7. **Проба.** В `playwright_proxy` схема `socks5h` → `socks5` в `server`
   (без учёта регистра). В `CurlCffiAdapter.navigate` прокси со схемой
   `socks5://` (без учёта регистра) отдаётся curl_cffi как `socks5h://`;
   `CurlAdapter`, `PrimpAdapter`, входы и pydoll не трогать. `redact`
   дополнительно заменяет на `***` пароль текущего `ABG_PROXY` — и в сыром
   (`p%40ss`), и в раскодированном (`p@ss`) виде, если пароль непустой;
   битый URL в `ABG_PROXY` не должен ронять `redact`.
8. **Модульный docstring** `gateway/oneshot.py` описывает оба режима и
   отказы.
9. **Тесты** (unittest, без сети и браузера, через подмену `Popen`, как в
   `tests/test_oneshot.py`), каждый отказ — с проверкой ПРИЧИНЫ (точный
   stderr) и парным входом без нарушения, который проходит:
   все три ступени с `ABG_PROXY` и `egress_profile == 'explicit'`;
   `--proxy` сильнее `ABG_PROXY`; запасная ступень при другом и при том же
   `ABG_EGRESS_PROXY`; только `ABG_EGRESS_PROXY` — прежняя лестница; оба
   отказа и `invalid_request` — без единой пробы; пароль не появляется в
   stdout, stderr и argv проб; scope сессий (тот же прокси переигрывает,
   direct не берёт сессию прокси, другой логин/порт — другой каталог,
   другой пароль — тот же); `plan_product` с `route_profile` и его
   валидация; проба: `socks5h`→`socks5` в `playwright_proxy`,
   `socks5`→`socks5h` в curl_cffi, `redact` с паролем.

Мутанты, которые новые тесты обязаны убивать: `--proxy` слабее
`ABG_PROXY`; снят отказ по userinfo в `--proxy` (и вариант «только
пароль», пропускающий логин без пароля); снят отказ socks5-с-паролем или
он не учитывает `--no-browser`; `socks5h` выпал из проверки отказа;
браузерная ступень на `direct` при явном прокси; запасная ступень
удалена при другом `ABG_EGRESS_PROXY` или оставлена при том же; пароль
вошёл в `identity`; логин или порт выпал из `identity`; сессия у
запасной ступени; снят маппинг `socks5h`→`socks5` или `socks5`→`socks5h`;
`redact` без раскодированного пароля.

## Не трогать

- Спеку `docs/specs/m26-proxy-ladder.md`, файлы стенда
  `docs/specs/checks/m26_proxy_ladder.py`, `docs/specs/checks/m26_stand.sh`,
  `docs/specs/checks/m26_target.py`, чекеры M24/M25 и `tests/fixtures/*` —
  критерии сверяют sha256.
- 🚨 Зону M25: `PatchrightAdapter` и всё, что M25 добавила для клика
  Turnstile (`_try_turnstile_click` и связанные константы/хелперы),
  `PlaywrightAdapter.navigate`, `_document_and_body`, `_await_reload`,
  `detect_challenge`, `ScraplingAdapter.navigate`. В `probe.py` правятся
  только `playwright_proxy`, `redact` и ветка прокси в
  `CurlCffiAdapter.navigate`.
- `bench/runner/`, `bench/providers/registry.py`, `gateway/sessions.py`,
  `gateway/api_http.py`, `gateway/service.py`, `gateway/httpapi.py`,
  `gateway/mcp_stdio.py`, `deploy/`, `scripts/`, `README.md`, `docs/`,
  `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`, `tests/probe_*.py`, старые
  `tests/mutation_gate*.py`. Существующие тесты не ослаблять и не удалять.
- Версии curl_cffi/patchright/playwright/scrapling/Chrome — без апгрейдов.
- Скил `abg-fetch` (fetch.sh, SKILL.md) — НЕ часть вехи, его правит
  постановщик после выпуска образа (см. «Стыки»).
- 🚨 Репозиторий публичный: ни одного настоящего прокси, логина, пароля,
  домена, IP или пути `/home/...`; в тестах — `.invalid`/`.example` и
  заглушки вида `user1:s3cr%40t`.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Файлы стенда и чекеры M24/M25 не изменены, все три чекера печатают ok:
  `bash -c 'printf "%s\n" "81b5f6c17e49ff762ac5520bb870a7fa2b44df8c08901750639fccac356f969f  docs/specs/checks/m26_proxy_ladder.py" "137304672fc4c18010af6ba3c47aaca984c6d541c6a60203dd293040a34ff000  docs/specs/checks/m26_stand.sh" "79cfb736d9eb73c0a107670c29b1e8e0de9b1ed983d525c47743970fec7f6074  docs/specs/checks/m26_target.py" "a92dd6e7ffa446540acc4d26ed073853d64fcede4b855ccd2f2fcc2016e23533  docs/specs/checks/m24_cf_detector.py" "087f0534692c114e7358c72ddaa974639d5c8398c250ef13592e1f2cafe76b2d  docs/specs/checks/m25_turnstile_click.py" | sha256sum -c --quiet && for c in m24_cf_detector m25_turnstile_click m26_proxy_ladder; do test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-003.** Стенд: без прокси цель недостижима, с HTTP-прокси с паролем curl_cffi берёт её через прокси:
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh http)" = ok'`
- **AC-004.** Стенд: браузерная ступень patchright идёт через прокси (страница с текстом только из JS):
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh browser)" = ok'`
- **AC-005.** Стенд: все три ступени (curl_cffi, patchright, scrapling) доходят до цели через прокси, пароль не виден в процессах:
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh deny)" = ok'`
- **AC-006.** Стенд: socks5h и socks5 без кредов, все три ступени через прокси:
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh socks)" = ok'`
- **AC-007.** Стенд: обратная совместимость ABG_EGRESS_PROXY и его стык с явным прокси:
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh compat)" = ok'`
- **AC-008.** Стенд: отказы с причиной без единого запроса через прокси, `--no-browser` с SOCKS5-паролем, `--proxy` сильнее `ABG_PROXY`:
  `bash -c 'test "$(bash docs/specs/checks/m26_stand.sh refuse)" = ok'`
- **AC-009.** Изменения только в разрешённых путях, есть новые тесты, дерево чистое:
  `bash -c 'b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)gateway/oneshot.py" ":(exclude)gateway/product.py" ":(exclude)gateway/fetch.py" ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_oneshot.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/test_gateway_product.py" ":(exclude)tests/test_gateway_fetch.py" ":(exclude)tests/test_proxy_ladder.py" && test -n "$(git diff --name-only "$b" HEAD -- gateway/oneshot.py)" && test -n "$(git diff --name-only "$b" HEAD -- "tests/test_*.py")" && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

Что проверяет каждый сценарий стенда — в самом `m26_stand.sh` (сети
`--internal`, цель только за прокси, `attempts` сверяются целиком:
провайдер, `egress_profile`, статус, `error_type`; пароль ищется в stdout,
stderr и `docker top` во время прогона). Стенд в интернет не ходит. Сбой
Docker (нет образа, не создаётся сеть) — `blocked` с дословной ошибкой в
`note`, а не правка стенда или кода.

## Порядок работы

Сначала пункты 4–6 и чекер (AC-002), затем стенд по сценариям в порядке
`http → browser → deny → socks → compat → refuse`. На падении сценария
смотреть `attempts` и лог прокси, а не подбирать ожидания: ожидания стенда
посчитаны на эталоне и на BASE.

## Авторевью

Перекрёстное ревью этой вехи проводит постановщик при приёмке (свой разбор
диффа, два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека `docs/specs/m26-proxy-ladder.md` и файлы стенда уже закоммичены в
`main` до создания клона. Если они всё же приехали в клон untracked (клон
сделан раньше), закоммитить их вместе с работой без правок содержимого —
критерий сверяет sha256, а критерий границ требует чистого дерева.

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
`report-blocked.md` (вывод сценария стенда, `attempts`, хвост лога
прокси), если: какой-то провайдер в образе не ходит через прокси схемой,
которую таблица выше называет рабочей; для зелёного стенда нужна правка
вне разрешённых файлов или в зоне M25; чекер или стенд требуют поведения,
противоречащего спеке; M25 ещё не в `main` (в BASE нет
`docs/specs/checks/m25_turnstile_click.py`). Спеку, стенд, чекеры,
критерии и BASE не менять, rc не выдумывать, наружу ничего не публиковать.

## Стыки с соседними вехами

Опирается на M25 (в `main`): её код в `probe.py` не трогается, её чекер
обязан остаться `ok` (AC-002). Обещает следующим: one-shot принимает
`ABG_PROXY`/`--proxy`, все ступени идут через него, отказы
`proxy_credentials_in_argv`/`proxy_unsupported` стабильны (на них
опирается обёртка скила).

**После приёмки — шаг постановщика, не исполнителя:** выпуск образа
(0.1.7: тег+дайджест), README, CHANGELOG, затем скил `abg-fetch` в
источнике правды (репо ансибля, `roles/ai-tools/files/claude/skills/abg-fetch/`)
и в live-копии:

- `fetch.sh`: `ABG_PROXY` из окружения вызывающего уходит в контейнер по
  ИМЕНИ (`-e ABG_PROXY`, рядом с `-e ABG_EGRESS_PROXY`), без умолчания из
  `HTTPS_PROXY` (явный прокси — только явно). Флаг `fetch.sh --proxy URL
  <url> [mode]` принимается только без userinfo (argv самого fetch.sh
  виден в `ps` хоста) и тоже передаётся в контейнер через `ABG_PROXY` по
  имени, а не флагом one-shot; URL с кредами во флаге — exit 2 с
  подсказкой «креды — через ABG_PROXY». rc 2 one-shot с
  `proxy_unsupported` пробрасывается как есть. Пин образа — новый
  тег+дайджест.
- `SKILL.md`: раздел «Прокси»: `ABG_PROXY` (вся лестница) против
  `ABG_EGRESS_PROXY` (запасная попытка, прежнее умолчание), таблица схем
  из этой спеки, SOCKS5 с паролем только с `--no-browser`, сессии через
  прокси хранятся отдельно от прямых.
