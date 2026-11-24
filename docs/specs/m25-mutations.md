# M25 — независимые мутации тестов клика Turnstile

24.11.2026. Проверочная задача, не реализация. Код M25 писал Qwen,
мутации гоняет противоположный исполнитель (Codex).

Клон сделан `make_clone.sh --kind mut` от ветки `m25-turnstile-click`,
SOURCE_SHA `61f844edc4d8ba1ca1b12afa5e27feb47828ba94` (проверь
`git rev-parse HEAD`). Push запрещён. Выход — каталог `mut-out/` в корне
клона (не коммитить).

## Что мутировать

Продукт — `bench/providers/docker/probe.py`, только то, что изменила веха
(`git diff 1d19d80 61f844e -- bench/providers/docker/probe.py`): условие
включения клика в `PlaywrightAdapter` (только patchright, вердикт,
`header_cf_mitigated` И (`body_just_a_moment` ИЛИ `body_cf_chl_opt`)),
флаг `turnstile_attempted` и пропуск `_await_reload`; константы
`TURNSTILE_*`; `_turnstile_cap_ms` (10 с, половина остатка, TimeoutError
→ 0); `_turnstile_pw_timeout`; `_turnstile_gone`;
`_turnstile_has_clearance` (имя, домен хоста, суффикс с точкой);
`_turnstile_find_container` (глубина предков, границы
`width > 40`, `20 < height < 120`, точка x+25 / середина);
`_turnstile_token_filled`; цикл `_try_turnstile_click` (подтверждение
ухода 0,25 с, без клика после ухода, пауза 4 с после клика, 0,5 с после
промаха, пауза опроса ≤ остатка, выход при исключении паузы). Прочитать
целиком дифф вехи и `docs/specs/m25-patchright-turnstile-click.md`.

Авторский набор — ТОЛЬКО `tests.test_probe` и чекер
`docs/specs/checks/m25_turnstile_click.py` (печатает `ok`). Команды
(сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_probe`

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m25_turnstile_click.py`

Мутант убит, если падает хотя бы одна из двух команд (запиши, какая).
20–28 смысловых мутантов, по одному изменению, каждый в отдельной копии
дерева под `mut-out/`. Обязательные: сдвиг 25→26; пауза 4→1 с; снят
пропуск при заполненном токене; снято условие `cf_clearance`; потолок
10→14 с; снята «половина остатка»; включение для playwright; снята каждая
граница размера по отдельности и строгое неравенство → нестрогое; снято
требование `header_cf_mitigated`; клик после ухода заглушки; домен cookie
без границы метки; `turnstile_attempted` не выставляется; пауза опроса без
ограничения остатком; исключение паузы → `pass`.

Для каждого: id, ось, diff, доказательство, что изменённая строка
исполняется, команда, rc, упавший тест и строка assertion. Syntax/import
error — invalid. Нет вызова — survivor «непокрыто». Equivalent — только с
доказательством. Тест на отказ должен падать по причине мутации.

## Выход и границы

`mut-out/result.md` (таблица kill/survivor/invalid/equivalent, survivors с
пояснением), `mut-out/mutations.json`, `mut-out/logs/`. В конце —
восстановленный green, `git status` клона чист, кроме `mut-out/`,
HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`). Не править
продукт, тесты, спеки, TASKS/CHANGELOG. Без push, ревьюеров, других
моделей, новых панелей, sudo, установок на хост. Код исполняется только в
Docker 1002:1002. `report.json` не требуется. При ошибке квоты — сохранить
улики и остановиться.
