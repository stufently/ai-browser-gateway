# M27 — независимые мутации тестов ретранслятора прокси

24.11.2026. Проверочная задача, не реализация. Код M27 писал Qwen,
мутации гоняет противоположный исполнитель (Codex).

Клон сделан `make_clone.sh --kind mut` от ветки `m27-proxy-relay`,
SOURCE_SHA `52ea300` (полный — `git rev-parse HEAD`). Push запрещён.
Выход — каталог `mut-out/` в корне клона (не коммитить).

## Что мутировать

Только код вехи: `git diff 64d847c HEAD -- gateway/ bench/providers/docker/probe.py`.
Прочитать дифф и `docs/specs/m27-proxy-relay.md` целиком. Оси:
- `_ProxyRelay`: bind только `127.0.0.1`; `Proxy-Authorization: Basic` в
  CONNECT и plain HTTP (кодировка `user:password`, `unquote`); снятие
  `Proxy-Authorization`/`Proxy-Connection`/`Connection` клиента;
  `Connection: close` наверх; никакого `Authorization` сайту;
  SOCKS5: метод 0x02, RFC 1929, ATYP=0x03, разбор ответа (0x01/0x03/0x04),
  предел 255 байт; 407 → `UPSTREAM_REJECTED_HTTP` и 502 (в т.ч. после 1xx);
  отказ цели (не 407) fatal не трогает; молчание/сброс → 502 и
  `UPSTREAM_UNREACHABLE`; https-прокси: проверка сертификата не ослаблена,
  сокет регистрируется до рукопожатия; байты после заголовка CONNECT и
  прелюдия прокси уходят в туннель первыми; тело POST; пределы заголовков;
  `close()` (halt, join, дедлайн), старт потока до занесения в список;
- `_browser_proxy`: релей только при userinfo, иначе `playwright_proxy`;
- `_cancel_auth_handler`: только `CancelAuth`, `handleAuthRequests: True`,
  подключение к новым страницам; включается только при релее (patchright и
  scrapling);
- `run_probe`: `fatal` релея после успешной навигации → `ok: false`, `err`
  с причиной через `redact`;
- адаптеры: релей закрывается в `finally` при исключении в close браузера;
- `gateway/oneshot.py`: `proxy_credentials_in_argv` сохранён, отказ
  `proxy_unsupported` снят.

Авторский набор — `tests.test_proxy_relay`, `tests.test_proxy_ladder`,
`tests.test_probe` и чекер `docs/specs/checks/m27_proxy_relay.py` (печатает
`ok`). Команды (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_proxy_relay tests.test_proxy_ladder tests.test_probe`

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m27_proxy_relay.py`

Мутант убит, если падает хотя бы одна команда (запиши какая). 24–30
смысловых мутантов, по одному изменению, каждый в отдельной копии дерева
под `mut-out/`. Для каждого: id, ось, diff, доказательство исполнения
строки, rc, упавший тест и assertion. Syntax/import error — invalid; нет
вызова — survivor «непокрыто»; equivalent — только с доказательством.
Зависание дольше 300 с на мутанте — kill по таймауту, отметить отдельно.

## Выход и границы

`mut-out/result.md` (таблица kill/survivor/invalid/equivalent/timeout),
`mut-out/mutations.json` (поля id, axis, diff, status), `mut-out/logs/`.
В конце — восстановленный green, `git status` чист кроме `mut-out/`,
HEAD == SOURCE_SHA. Ничего не коммитить, не ходить в сеть, не править
продукт/тесты/спеки, без push, ревьюеров, новых панелей, sudo, установок.
Код — только в Docker 1002:1002. `report.json` не нужен. При ошибке квоты —
сохранить улики и остановиться.
