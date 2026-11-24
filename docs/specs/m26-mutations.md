# M26 — независимые мутации тестов прокси

24.11.2026. Проверочная задача, не реализация. Код M26 писал Codex,
мутации гоняет противоположный исполнитель (Qwen).

Клон сделан `make_clone.sh --kind mut` от ветки `m26-proxy-ladder`,
SOURCE_SHA `196879f` (полный — `git rev-parse HEAD`). Push запрещён.
Выход — каталог `mut-out/` в корне клона (не коммитить).

## Что мутировать

Только код вехи: `git diff 26c0f97 HEAD -- gateway/ bench/providers/docker/probe.py`.
Прочитать дифф и `docs/specs/m26-proxy-ladder.md` целиком. Оси:
- `gateway/oneshot.py`: `_explicit_proxy` (флаг важнее env; userinfo во
  флаге → `proxy_credentials_in_argv`; SOCKS5 с паролем при браузерах →
  `proxy_unsupported`, при `--no-browser` разрешён; управляющие символы;
  `socks5`→`socks5h`), `_proxy_parts` (схема, хост, порт), `session_store`
  (подкаталог по хэшу без пароля, отказ при неприватном корне),
  отключение `ABG_EGRESS_PROXY` при явном прокси, фильтр окружения потомка;
- `gateway/product.py`: `route_profile` в плане и валидации;
- `gateway/fetch.py`: сессии только на основном маршруте;
- `probe.py`: `playwright_proxy` (`socks5h`→`socks5`), `redact` (порядок:
  пароль до регулярки, `unquote`), `_chromium_proxy` (снятие учётных данных
  только для http/https), `_proxy_auth_handler` (учётные данные только на
  вызов от `Proxy`, один раз на запрос, иначе `CancelAuth`), флаг WebRTC
  и `block_webrtc`.

Авторский набор — `tests.test_proxy_ladder`, `tests.test_probe`,
`tests.test_gateway_product` и чекер `docs/specs/checks/m26_proxy_ladder.py`
(печатает `ok`). Команды (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_proxy_ladder tests.test_probe tests.test_gateway_product`

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m26_proxy_ladder.py`

Мутант убит, если падает хотя бы одна команда (запиши какая). 20–28
смысловых мутантов, по одному изменению, каждый в отдельной копии дерева
под `mut-out/`. Для каждого: id, ось, diff, доказательство исполнения
строки, rc, упавший тест и assertion. Syntax/import error — invalid; нет
вызова — survivor «непокрыто»; equivalent — только с доказательством.

## Выход и границы

`mut-out/result.md` (таблица kill/survivor/invalid/equivalent),
`mut-out/mutations.json` (поля id, axis, diff, status), `mut-out/logs/`.
В конце — восстановленный green, `git status` чист кроме `mut-out/`,
HEAD == SOURCE_SHA. Ничего не коммитить, не ходить в сеть, не править
продукт/тесты/спеки, без push, ревьюеров, новых панелей, sudo, установок.
Код — только в Docker 1002:1002. `report.json` не нужен. При ошибке квоты —
сохранить улики и остановиться.
