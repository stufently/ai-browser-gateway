# M27 — локальный релей прокси для браузерных ступеней

## Шапка и где работать

Репозиторий ai-browser-gateway, 24.11.2026.

BASE_SHA: (ставится отдельным коммитом сразу после коммита этой спеки)

Клон делается от вершины `main` не раньше BASE_SHA; в базе уже есть код
M26 (выпуск 0.1.7), усиление `TurnstileClickTests` (`1d5cd18`), эта спека и
три файла стенда `docs/specs/checks/m27_*`. Коммиты спеки M28
(`docs/specs/m28-*`, `docs/specs/checks/m28_*`) в базе — чужие, их не
трогать. Критерий границ считает дифф от `git merge-base HEAD origin/main`,
поэтому клон делается только `make_clone.sh`. Исполнитель — `auto`;
мутации по новым тестам потом гоняет противоположный исполнитель отдельной
вехой.

Новая ветка: `m27-proxy-relay`. Живое дерево постановщика не трогать.
git pull в клоне не делать; push в origin запрещён, работу заберёт
постановщик через `git fetch` из клона. Образы стенда постановщик стянул
заранее: one-shot 0.1.7, `gogost/gost:3.3.3`, `python:3.14.7-slim-bookworm`
(дайджесты — в `docs/specs/checks/m27_stand.sh`).

## Задача и почему

M26 пустила всю лестницу через явный прокси. Для http/https-прокси с
паролем проба снимает креды с прокси запуска Chromium и отвечает на 407
через CDP `Fetch.authRequired`, подключая обработчик к каждой странице
(`_chromium_proxy`, `_proxy_auth_handler` в `bench/providers/docker/probe.py`).
Дыры этого пути: первый 407 от cross-site iframe (OOPIF) или service
worker идёт в другую CDP-цель и остаётся без ответа; popup получает
обработчик только после своего первого запроса; SOCKS5 с паролем Chromium
не умеет вовсе, и one-shot отказывает `proxy_unsupported`.

**Решение владельца:** маленький релей без авторизации внутри процесса
пробы, на `127.0.0.1` и эфемерном порту. Chromium (patchright и scrapling)
запускается с `http://127.0.0.1:<порт>` БЕЗ кредов; релей пересылает
трафик внешнему прокси и сам добавляет авторизацию: `Proxy-Authorization:
Basic` для http/https, RFC 1929 (username/password) для socks5/socks5h.
curl_cffi, как и сейчас, ходит к внешнему прокси напрямую.

## Решения постановщика

- **Релей — только для браузерных ступеней patchright и scrapling и только
  когда в URL прокси есть userinfo** (`urlparse(url).username is not None`).
  Без кредов Chromium получает прежний `playwright_proxy(url)`. Почему не
  один путь для всех: без кредов все схемы у Chromium уже работают (таблица
  M26), прямой путь не добавляет хоп, поток на соединение и новую точку
  отказа, SOCKS5 без пароля сохраняет нативный удалённый DNS Chromium, а
  сценарии `socks`/`compat` стенда M26 остаются живым эталоном
  совместимости. `PlaywrightAdapter` пакета `playwright` (только бенч),
  camoufox и pydoll не меняются: у них креды прокси работают нативно.
- **Код релея — в `probe.py`, не в новом модуле.** Проба — один файл по
  контракту: бенч монтирует только `probe.py` в `/opt/abg/probe.py`
  (`bench/providers/registry.py::build_argv`, `bench/runner/fetch.py::PROBE_FILE`),
  `Dockerfile.patchright`/`Dockerfile.scrapling` и `deploy/Dockerfile.oneshot`
  копируют только его, стенды монтируют только его. Новый модуль потребовал
  бы правок вне вехи. Только stdlib (`socket`, `ssl`, `threading`, `base64`;
  `selectors` по желанию) — в образе Python 3.14.7, OpenSSL 3.0.20, всё
  импортируется (проверено).
- **CDP-обработчик сужается до `CancelAuth` (решение владельца
  24.11.2026).** Креды прокси через CDP больше не отдаются НИКОГДА
  (`ProvideCredentials` из кода исчезает): их знает только релей. Но
  обработчик остаётся, когда работает релей, и на ЛЮБОЙ
  `Fetch.authRequired` отвечает `CancelAuth`: на `source=Server` (401
  сайта) — чтобы страница с 401 читалась, как на BASE; на `source=Proxy` —
  при релее такого быть не должно, а если случится, Chromium всё равно
  нечего отдать. Подключение — как на BASE (страница запуска,
  `context.on("page", …)` для новых страниц у patchright, `page_setup` у
  scrapling, трюк `page.route`/`page.unroute`, чтобы Patchright отпустил
  свой перехватчик Fetch). Без релея (прокси без кредов или без прокси)
  обработчик не включается — прямой режим не меняется. Измерено: без
  `CancelAuth` главный документ с `401 Basic` даёт
  `net::ERR_INVALID_AUTH_CREDENTIALS`, а same-origin iframe с таким 401
  поднимает окно входа headful Chrome и подвешивает загрузку до таймаута;
  с обработчиком (BASE и эталон) страница читается со статусом 401. Защита
  WebRTC остаётся при ЛЮБОМ прокси: флаг
  `--webrtc-ip-handling-policy=disable_non_proxied_udp` у patchright и
  `block_webrtc=True` у scrapling.
- **Вне скоупа: `ABG_PROXY` в окружении процессов браузера** (драйвер и
  Chrome наследуют окружение пробы, пароль виден в `/proc/<pid>/environ`
  тому же uid). Так было и до M27; решение владельца — отдельная веха после
  выпуска 0.1.8. В этой вехе окружение запуска браузеров не трогать.
- **one-shot:** отказ `proxy_unsupported` убирается совсем (других причин
  у него нет). `proxy_credentials_in_argv` и `invalid_request` — без
  изменений. Кэш сессий не меняется: scope по-прежнему от identity прокси.

## Что проверено вживую, а что предположение

Проверено постановщиком 24.11.2026 на эталонной реализации (черновая
копия, не в репозитории) поверх образа one-shot 0.1.7 (patchright 1.62.3,
scrapling 0.4.15, Chrome 156), Docker под 1002:1002, gost 3.3.3 в
изолированных сетях:

- Все семь сценариев `m27_stand.sh` — `ok` три прогона подряд (2–17 с на
  сценарий). Чекер `m27_proxy_relay.py` — `ok` трижды; девять мутантов
  узкого обработчика и утечек (`ProvideCredentials`, в том числе вторым
  подписчиком и только в popup, `Authorization` сайту через SOCKS5, обработчик снят у patchright
  или scrapling, включён без релея, нет на новых страницах,
  `handleAuthRequests: False`) чекер убивает все. Сценарий `auth` на
  эталоне без обработчика падает (страница с 401 виснет), на BASE с
  отключённой проверкой релея — `ok`: поведение на 401 сайта как на BASE.
  Полный сьют на эталоне (база с усилением `TurnstileClickTests`) — 838 тестов, падают ровно три старых теста, которые веха обязана
  переписать (см. «Что сделать», п. 8); замороженные пробы M9–M13 (125)
  и чекеры M24/M25 зелёные.
- На эталоне стенд M26: `http`, `socks`, `compat` — `ok`; `browser` и
  `deny` — FAIL по делу (ищут `--proxy-server=http://<прокси>:8080`, а
  теперь там релей), `refuse` — FAIL по делу (SOCKS5 с паролем больше не
  отказ). Чекер M26 падает ровно четырьмя строками про SOCKS5 с паролем.
- На BASE стенд M27 падает во всех сценариях, кроме `refuse` (эталон
  неизменного отказа), чекер M27 — десятками расхождений.
- **Честно про дыры из «Задачи»:** на BASE с отключённой проверкой
  «Chrome запущен на релее» сценарии `frame` (cross-site iframe) и `sw`
  (service worker) ПРОХОДЯТ: Chromium кэширует креды прокси после 407
  главного документа, и последующие запросы других целей их уже несут.
  Дыра реальна только когда ПЕРВЫЙ запрос сессии идёт не от страницы;
  стенд такого не воспроизводит. Поэтому доказательство вехи — не эти
  сценарии, а то, что Chromium не видит ни адреса внешнего прокси, ни кредов
  (`docker top`), CDP-обработчик никогда не отдаёт креды (чекер), а iframe,
  воркер и SOCKS5 с паролем через релей работают (стенд).
- **Popup (`window.open`) на стенде невозможен:** у Chrome обоих
  провайдеров нет `--disable-popup-blocking` (видно в `docker top`), и
  `window.open` без жеста пользователя блокируется — окно не создаётся,
  цель его адреса не получает ни одного запроса (измерено). Замена: релей
  уровня запуска обслуживает любую будущую цель, включая popup, а чекер
  требует, чтобы новая страница контекста получила тот же обработчик
  `CancelAuth`.
- Service worker получает secure context через `http://localhost:8000`:
  вторая цель живёт в сетевом пространстве прокси, Playwright запускает
  Chrome с `--proxy-bypass-list=<-loopback>`, так что loopback тоже идёт
  через релей и внешний прокси.
- https-прокси (TLS до прокси): релей проверяет сертификат прокси
  `ssl.create_default_context()`; стенд выпускает свой CA и передаёт его
  через `SSL_CERT_FILE`. Python 3.14 по умолчанию включает
  `VERIFY_X509_STRICT`: CA без `keyUsage` и лист без `authorityKeyIdentifier`
  отвергаются (Chrome такие принимал). Ослаблять проверку ЗАПРЕЩЕНО.
- Неверный пароль: на one-shot лестница до браузеров не доходит (curl_cffi
  с http-прокси видит 407 → `content_mismatch`, с SOCKS5 →
  `provider_error`, как до M27), поэтому отказ браузеров стенд проверяет
  пробой напрямую: `err` — точный текст из п. 4 ниже.

Предположения (живьём не проверены): `ws://`/`wss://` идут через CONNECT
так же, как https (так устроен Chromium; в стенде нет WebSocket); доверие к
https-прокси с публичным сертификатом — через системные CA образа
(`/usr/lib/ssl`), а не через хранилище Chrome; scrapling на iframe/воркере
не гонялся (лестница останавливается на patchright), его путь тот же —
`_browser_proxy` и тот же релей.

## Что сделать

Разрешённые файлы: `bench/providers/docker/probe.py`, `gateway/oneshot.py`,
`tests/test_probe.py` (кроме класса `TurnstileClickTests`), `tests/test_proxy_ladder.py`,
`tests/test_oneshot.py`, новый `tests/test_proxy_relay.py`.

1. **Релей** — класс `_ProxyRelay(upstream_url)` в `probe.py`:
   `start()` слушает `("127.0.0.1", 0)` (только loopback) и возвращает
   `"http://127.0.0.1:<порт>"`; `close()` закрывает слушающий сокет и все
   живые соединения и дожидается своих потоков (join с таймаутом, потоки
   `daemon=True`); `fatal: str | None` — первый отказ уровня прокси (п. 4).
   Креды — `unquote` от userinfo; нет пароля в URL (`http://user1@…`) —
   пароль пустая строка, не ошибка; для SOCKS5 логин или пароль длиннее
   255 байт в UTF-8 — `ProxyRelayError` из конструктора, до запуска браузера.
2. **Протокол со стороны Chromium.** Заголовок запроса читается до
   `\r\n\r\n`, не больше 64 KiB.
   - `CONNECT host:port` (https, ws, wss): открыть туннель наверх; успех —
     клиенту `HTTP/1.1 200 Connection established\r\n\r\n`, затем байты в
     обе стороны до закрытия любой стороны. Байты, прочитанные вместе с
     заголовком CONNECT (после `\r\n\r\n`), уходят в туннель первыми.
   - Запрос с absolute-URI `http://…` (http-цели у HTTP-прокси): у
     http/https-прокси переслать наверх тот же request line; у SOCKS5 —
     туннель к `host:port` из URI и request line в origin-form
     (`GET /path?query HTTP/1.1`). В обоих случаях убрать заголовки
     клиента `Proxy-Authorization`, `Proxy-Connection`, `Connection`,
     добавить `Connection: close` (и `Proxy-Authorization` — только у
     http/https). Тело запроса (байты после `\r\n\r\n`, прочитанные вместе
     с заголовком, и всё, что клиент пришлёт дальше) пересылается наверх
     как есть до закрытия. Ответ сервера отдать клиенту как есть и закрыть
     соединение после него: на keep-alive следующий запрос ушёл бы без
     авторизации или не в тот туннель. Заголовки ответа не переписывать:
     запрос наверх уже несёт `Connection: close`, а запрос на соединении,
     которое закрыл релей, Chromium повторяет сам (стенд зелёный 3/3).
   - Иное (не http-схема в absolute-URI) — `400` и закрыть.
3. **Протокол наверх.**
   - http: `CONNECT host:port HTTP/1.1` с `Host` и
     `Proxy-Authorization: Basic base64(user:password)` (UTF-8).
   - https: то же поверх TLS к прокси, `ssl.create_default_context()`,
     `server_hostname` = хост прокси; без отключения проверок.
   - socks5 и socks5h — одинаково: приветствие с методом `0x02`, затем
     RFC 1929 (`0x01, ulen, user, plen, password`), затем CONNECT с
     `ATYP=0x03` и ИМЕНЕМ цели (имя резолвит прокси), разбор ответа с
     любым ATYP.
4. **Отказы.** Клиенту при любой неудаче наверху — `HTTP/1.1 502 Bad
   Gateway` (никогда не 407 и не текст ответа прокси). Отказы уровня
   прокси пишутся в `fatal`, ровно этими текстами:
   `upstream proxy rejected credentials (HTTP 407)` (407 на CONNECT или на
   plain HTTP), `upstream proxy rejected credentials (SOCKS5)` (метод
   `0x02` не выбран или RFC 1929 вернул не 0), `upstream proxy unreachable`
   (нет TCP до прокси), `upstream proxy TLS failed` (рукопожатие TLS с
   прокси). Отказ уровня цели (CONNECT наверху 4xx/5xx кроме 407, SOCKS
   reply ≠ 0) — только 502 клиенту, `fatal` НЕ трогает. `run_probe`: если у
   адаптера `fatal` задан — `err` равен `redact("ProxyRelayError: " + fatal)`,
   и при исключении навигации (в том числе таймауте), и после успешной
   навигации; во втором случае payload — как у исключения (`ok: false`,
   `status: null`, без `html`/`text` содержимого страницы), чтобы шлюз не
   принял страницу, часть которой не получила авторизацию. Без `fatal` —
   прежний `err`. Пароля в `fatal` нет по
   построению; `redact` не менять.
5. **Адаптеры.** `PatchrightAdapter` (через `PlaywrightAdapter.start` при
   `package == "patchright"`) и `ScraplingAdapter.start` получают прокси
   запуска из одной функции `_browser_proxy(url) -> (settings, relay|None)`:
   с userinfo — `{"server": relay.start()}` и ничего больше (ни
   `username`, ни `password`), без userinfo — `playwright_proxy(url)`.
   Релей стартует ДО запуска браузера и сохраняется в адаптере до вызова
   launch, чтобы `close()` закрыл его и при упавшем launch. `close()`
   закрывает релей в `finally` после браузера/сессии. `_chromium_proxy`
   удалить. `_proxy_auth_handler` заменить обработчиком без кредов
   (`_cancel_auth_handler()` → `attach(page)`), который включается ТОЛЬКО
   при релее: одна CDP-сессия на страницу (повторный `attach` той же
   страницы ничего не делает), трюк `page.route("**/*", …)` +
   `page.unroute`, `Fetch.enable` с `handleAuthRequests: True` и
   `patterns: [{"urlPattern": "*"}]`, `Fetch.requestPaused` →
   `Fetch.continueRequest`, `Fetch.authRequired` (любой `source`) →
   `Fetch.continueWithAuth` с `{"response": "CancelAuth"}` и ничем иным.
   Подключение: patchright — страница запуска и `context.on("page", attach)`;
   scrapling — из `page_setup`. Остальной код
   `PlaywrightAdapter.navigate` и `ScraplingAdapter.navigate` не трогать.
6. **Прерывание.** One-shot убивает группу процесса пробы `SIGKILL`
   (`LocalLauncher.kill_active`) — релей живёт в том же процессе и умирает
   с ним; порт освобождает ядро. Отдельных обработчиков сигналов в пробе
   не добавлять.
7. **one-shot.** Из `_explicit_proxy` убрать отказ `proxy_unsupported`;
   параметр `allow_browser` убрать, если больше не нужен. Docstring
   модуля: креды прокси для браузеров идут через локальный релей, SOCKS5
   с паролем работает при включённых браузерах.
8. **Тесты** (unittest, без сети наружу и без браузера; релей — настоящий,
   на 127.0.0.1, против поддельного upstream в том же тесте, как в чекере).
   Переписать три теста, которые описывают снятое поведение:
   `test_proxy_credentials_answer_only_proxy_auth_challenges` и
   `test_both_playwright_packages_get_proxy_server` в `tests/test_probe.py`,
   `test_socks_credentials_require_http_only` в `tests/test_proxy_ladder.py`.
   ⚠️ Если класс `ProxyWiringTests` после слияния усиления
   `TurnstileClickTests` изменился — переписывать те же три теста по
   смыслу, остальное в классе не трогать.
   Остальные существующие тесты не ослаблять и не удалять. Каждый отказ —
   с проверкой ПРИЧИНЫ (точный `err` или точный ответ клиенту) и парным
   входом без нарушения, который проходит. Новые тесты обязаны убивать
   мутантов: релей включается без userinfo; `username`/`password` остались
   в прокси запуска; слушает не `127.0.0.1`; нет `Proxy-Authorization` на
   CONNECT или на plain HTTP; `Proxy-Authorization` клиента проходит
   наверх; нет `Connection: close`; тело POST или байты после заголовка
   CONNECT потеряны; URL без пароля роняет релей; SOCKS5 шлёт `ATYP=0x01` (резолв у
   себя) или не раскодирует `%40` в пароле; 407 наверху отдан клиенту как
   407; отказ цели (SOCKS reply 5, CONNECT 503) записан в `fatal`;
   `run_probe` не подставляет `fatal` в `err` при таймауте или после
   успешной навигации, или после успешной навигации оставляет `ok: true`; `close()` не закрывает живые соединения или
   слушающий сокет (порт принимает после `close`); релей не закрыт, если
   `browser.close()` бросил; релей не закрыт при упавшем launch; релей
   включён у пакета `playwright`; флаг WebRTC или `block_webrtc` пропал;
   обработчик CDP отвечает `ProvideCredentials` (или шлёт логин/пароль)
   хоть на какой-то `source`, в том числе вторым подписчиком
   `Fetch.authRequired` или только на новых страницах; релей добавляет
   сайту `Authorization` (через SOCKS5 или HTTP-прокси); обработчик не включён при релее (у
   patchright или у scrapling) или включён без релея; новая страница
   patchright без обработчика; `handleAuthRequests` выключен;
   one-shot всё ещё отказывает SOCKS5 с паролем; `--proxy` с userinfo
   перестал отказывать.

## Не трогать

- Спеку `docs/specs/m27-proxy-relay.md`, файлы стенда
  `docs/specs/checks/m27_proxy_relay.py`, `docs/specs/checks/m27_stand.sh`,
  `docs/specs/checks/m27_target.py`, все файлы M26 (`m26_*`), чекеры
  M24/M25 и `tests/fixtures/*` — критерии сверяют sha256.
- 🚨 Зону M25 и класс `TurnstileClickTests` в `tests/test_probe.py`:
  `_try_turnstile_click` и связанные константы/хелперы,
  `PlaywrightAdapter.navigate`, `_document_and_body`, `_await_reload`,
  `_playwright_body`, `detect_challenge`, `ScraplingAdapter.navigate` (кроме
  удаления вызова `_proxy_auth` в `page_setup`).
- `playwright_proxy`, `redact`, `urlopen`, адаптеры curl/curl_cffi/primp,
  camoufox, pydoll, входы; `gateway/` кроме `oneshot.py`; `bench/runner/`,
  `bench/providers/registry.py`, `deploy/`, `scripts/`, `README.md`,
  `docs/`, `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`, `tests/probe_*.py`,
  старые `tests/mutation_gate*.py`.
- Версии curl_cffi/patchright/playwright/scrapling/Chrome — без апгрейдов;
  сторонних пакетов не добавлять.
- Скил `abg-fetch` — НЕ часть вехи (см. «Стыки»).
- 🚨 Репозиторий публичный: ни одного настоящего прокси, логина, пароля,
  домена, IP или пути `/home/...`; в тестах — `.invalid`/`.example`,
  `127.0.0.1` и заглушки вида `user1:s3cr%40t`.

## Разрешения

Можно: читать весь репозиторий; гонять Docker под `--user 1002:1002`
(сьют, чекеры, стенд — стенд сам создаёт и удаляет свои сети и
контейнеры с префиксом `m27-`); локальные коммиты в ветке
`m27-proxy-relay`. Нельзя: push, сеть наружу, `docker pull` (образы уже
есть; нет образа — `blocked`), установки на хост, sudo, правка чужих
контейнеров/сетей.

## Критерии приёмки

- **AC-001.** Полный сьют и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-002.** Файлы стендов M26/M27 и чекеры M24/M25 не изменены, чекеры M24, M25 и M27 печатают ok:
  `bash -c 'printf "%s\n" "86449844e45d1b2ea7e3bdadd6caeca0c2a349a2719f04a052d82238e55f6fcc  docs/specs/checks/m27_proxy_relay.py" "37e4962e57e89386213a319f7edfe5a74e491c6b3703ee5b42e85b22aeafa09c  docs/specs/checks/m27_stand.sh" "c657ac0d254fa65fcbeb837b039964f00ec5be45bd59c9a3741c667a462877a0  docs/specs/checks/m27_target.py" "934e6b16c590b021fa0fb51c5d07edaadc108e503d81dd9f86a1507ade9a287f  docs/specs/checks/m26_proxy_ladder.py" "4aa0bedf53ea6949408a87504a95f25c5e85a4a97c71214b49a3479112992e49  docs/specs/checks/m26_stand.sh" "79cfb736d9eb73c0a107670c29b1e8e0de9b1ed983d525c47743970fec7f6074  docs/specs/checks/m26_target.py" "a92dd6e7ffa446540acc4d26ed073853d64fcede4b855ccd2f2fcc2016e23533  docs/specs/checks/m24_cf_detector.py" "087f0534692c114e7358c72ddaa974639d5c8398c250ef13592e1f2cafe76b2d  docs/specs/checks/m25_turnstile_click.py" | sha256sum -c --quiet && for c in m24_cf_detector m25_turnstile_click m27_proxy_relay; do test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 timeout 300 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-003.** Чекер M26 расходится ровно в двух снятых отказах SOCKS5 с паролем, остальное (лестница, сессии, проба) по-прежнему ok:
  `bash -c 'out=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m26_proxy_ladder.py); test "$(printf "%s\n" "$out" | wc -l)" = 4 && test "$(printf "%s\n" "$out" | sed "s/:.*//" | LC_ALL=C sort | uniq -c | tr -s " " | tr "\n" "|")" = " 2 socks5 с паролем и браузерами| 2 socks5h с паролем и браузерами|"'`
- **AC-004.** Стенд M26 без изменений: curl_cffi через прокси с паролем, SOCKS без кредов у всех ступеней, совместимость с ABG_EGRESS_PROXY:
  `bash -c 'for s in http socks compat; do test "$(bash docs/specs/checks/m26_stand.sh $s)" = ok || exit 1; done'`
- **AC-005.** Стенд: прокси с паролем, Chrome запущен только на релее 127.0.0.1, страница из JS и три ступени до цели:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh relay)" = ok'`
- **AC-006.** Стенд: cross-site iframe на втором хосте цели виден в content, сессия к хосту B в логе прокси:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh frame)" = ok'`
- **AC-007.** Стенд: service worker сам ходит в сеть через релей и прокси:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh sw)" = ok'`
- **AC-008.** Стенд: SOCKS5 и socks5h с паролем у patchright и scrapling, сессии u1 в логе прокси:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh socks)" = ok'`
- **AC-009.** Стенд: 401 Basic сайта через прокси с паролем читается (главный документ и iframe) без Authorization сайту, неверный пароль даёт точную причину в err пробы:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh auth)" = ok'`
- **AC-010.** Стенд: https-прокси с паролем через релей, CONNECT-туннель поверх TLS, без доверия к CA отказ по TLS:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh tls)" = ok'`
- **AC-011.** Стенд: креды в argv по-прежнему отказ без единого запроса через прокси:
  `bash -c 'test "$(bash docs/specs/checks/m27_stand.sh refuse)" = ok'`
- **AC-012.** Изменения только в разрешённых путях, есть новый тест релея, дерево чистое:
  `bash -c 'git merge-base --is-ancestor BASE_SHA_PLACEHOLDER HEAD && b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)gateway/oneshot.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/test_proxy_ladder.py" ":(exclude)tests/test_oneshot.py" ":(exclude)tests/test_proxy_relay.py" && test -n "$(git diff --name-only "$b" HEAD -- bench/providers/docker/probe.py)" && test -n "$(git diff --name-only "$b" HEAD -- tests/test_proxy_relay.py)" && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

Что проверяет каждый сценарий стенда — в самом `m27_stand.sh`: сети
`--internal`, цель только за прокси, `attempts` сверяются целиком
(провайдер, `egress_profile`, статус, `error_type`), пароль (верный и
неверный, в сыром, `%40`- и base64-виде `user:password`) ищется в stdout,
stderr и `docker top` во время каждого прогона; в сценарии `auth` ни один
запрос сайту (любой путь) не несёт `Authorization`; сценарий `tls` дополнительно
открывает настоящим `_ProxyRelay` сырой CONNECT-туннель поверх TLS до
прокси и гонит через него HTTP-запрос; Chrome обязан стоять на
`--proxy-server=http://127.0.0.1:<порт>` и ни разу на адресе прокси.
Стенд в интернет не ходит. Сбой Docker (нет образа, не создаётся сеть) —
`blocked` с дословной ошибкой в `note`, а не правка стенда или кода.

## Порядок работы

До первой правки — первая половина AC-012 на свежем клоне:
`git merge-base --is-ancestor <BASE_SHA> HEAD && b=$(git merge-base HEAD origin/main) && git diff --quiet "$b" HEAD`
(rc 0 обязателен: иначе база старше спеки или не та, это blocker; вторая
половина AC-012 до работы падает по построению — новых файлов ещё нет) и
чекер M25 (команда из AC-002 для `m25_turnstile_click`). Затем пункты 1–5
и тесты релея, затем п. 7, и только потом чекер M27 (его часть про
one-shot требует уже снятого `proxy_unsupported`) и AC-003, затем стенд в порядке `relay → frame → sw → socks → auth →
tls → refuse`, затем AC-004 и полный сьют. На падении сценария смотреть
`attempts`, `err` пробы и лог прокси, а не подбирать ожидания: ожидания
стенда посчитаны на эталоне и на BASE.

## Авторевью

Перекрёстное ревью проводит постановщик при приёмке (свой разбор диффа,
два внешних ревьюера, живой стенд и отдельный мутационный прогон
противоположным исполнителем). Исполнитель обёртку ревью не запускает и
квитанций не пишет; его часть — зелёные критерии и честный `report.json`.

Спека `docs/specs/m27-proxy-relay.md` и файлы стенда уже закоммичены в
`main` до создания клона. Если они всё же приехали в клон untracked,
закоммитить их вместе с работой без правок содержимого — критерий сверяет
sha256, а критерий границ требует чистого дерева.

## Контракт отчёта

`report.json` в корне клона, untracked, ровно 12 записей AC-001…AC-012,
`command` посимвольно из спеки:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда из спеки>", "rc": 0, "note": "<улика>"}]}
```

`blocked` — `"rc": null` и дословная ошибка в `note`. Обходить
несовместимость запрещено (`--no-deps`, `|| true`, `set +e` в команде и т. п.).

## Контракт на невыполнимое

Остановиться и записать один список blocker с уликами в
`report-blocked.md` (вывод сценария, `attempts`, `err` пробы, хвост лога
прокси), если: первая половина AC-012 на свежем клоне до правок не rc 0 (в базе нет
слияния `TurnstileClickTests` или лишние коммиты); чекер M25 на BASE не
`ok`; Chromium в образе не ходит через релей схемой, которую спека
называет рабочей; для зелёного стенда нужна правка вне разрешённых файлов,
в зоне M25, ослабление TLS-проверки или сторонний пакет; чекер или стенд
требуют поведения, противоречащего спеке. Спеку, стенд, чекеры, критерии
и BASE не менять, rc не выдумывать, наружу ничего не публиковать.

## Стыки с соседними вехами

Опирается на M26 (в `main`, 0.1.7) и на усиление `TurnstileClickTests`
(влить до запуска). Обещает следующим: SOCKS5 с паролем работает при
включённых браузерах, `proxy_unsupported` больше не выдаётся; Chromium
никогда не получает кредов прокси.

**После приёмки — шаг постановщика, не исполнителя:** выпуск образа
(0.1.8: тег+дайджест), README (таблица схем: SOCKS5 с паролем теперь у
всех ступеней), CHANGELOG, затем скил `abg-fetch` в источнике правды (репо
ансибля) и в live-копии: из `SKILL.md` убрать «SOCKS5 с паролем только с
`--no-browser`», ветку `proxy_unsupported` в `fetch.sh` оставить как
безвредный проброс rc 2; пин образа — новый тег+дайджест.
