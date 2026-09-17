# M13a — независимые мутации тестов Scrapling-заголовков (после M13a-fix)

17.09.2026. Проверочная задача cx, не реализация. Директива владельца 17.09:
«доделывай всё до конца». Правку и тесты писала другая cx-панель.

Клон /home/user/exec-clones/abg-m13a-mutations2-20260917, ветка
m13a-mutations2, origin push DISABLED. SOURCE_SHA
`c32da3c` (FINAL M13a-fix, полный SHA — `git rev-parse c32da3c` в клоне).
Выход: /home/user/.cache/abg-coord-20260917/m13a-mutations2/. Первый прогон
по `c0a6f17` остановлен координатором: код переделывался.

## Что мутировать

Продукт мутаций — условие удаления устаревшего `cf-mitigated` в
`ScraplingAdapter.navigate` (`bench/providers/docker/probe.py`) и его соседство:
`_normalize_headers`, передача `headers` в `_result`, путь `run_probe` →
`detect_challenge`. Прочитать целиком `docs/specs/m13a-scrapling-headers.md`, `docs/specs/m13a-fix.md`,
`docs/research/08-bizprofile-scrapling.md` и `git diff 7e1bf3a c32da3c`.
`detect_challenge` и его правила НЕ мутировать (заморожены отдельно).

Авторский набор — ТОЛЬКО `tests.test_probe.ScraplingAdapterTests`. Команда
(сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_probe.ScraplingAdapterTests`

12–20 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: границы статуса (`<= 300`,
`< 299`, `>= 201`, убрать проверку `None`); вердикт тела (убрать
`interactive`, убрать `suspected`, передавать `headers` вместо `None`,
`status` вместо тела); удаление (удалять все заголовки / очищать словарь,
удалять всегда при 2xx, превращать `{}` в `None`, мутировать исходный словарь
ответа вместо нормализованной копии); удалить весь блок (регресс исходного
дефекта); captcha-условие (убрать `"body_captcha" not in`, `== "none"` заменить на
`not in ("suspected", "interactive")`, проверять `body_captcha` в
`body_challenge[0]` вместо `[1]`). Отдельно: `tests/mutation_gate_scrapling.py`
запустить на SOURCE (он сам мутирует дерево — только в копии, RW-mount копии,
не клона) и подтвердить, что все его мутанты убиты и тест мутанта 3 существует.

Для каждого: id, ось, diff, SHA256 исходника/мутанта/восстановления,
доказательство активации изменённой строки авторским набором, команда/cwd/rc,
лог, упавший тест и строка assertion. Syntax/import error — invalid. Нет вызова
— survivor «непокрыто». Equivalent — только с доказательством. Тест на отказ
должен падать по причине мутации, а не по побочному эффекту.

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, survivors с пояснением),
`mutations.json`, `commands.json`, `logs/`, `SHA256SUMS`. В конце —
восстановленный green, `git status` клона пуст, HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`), live-тест не
запускать, не трогать `/home/user/services/**`, сервис, секреты, Docker-сокет в
контейнерах. Не править продукт, тесты, specs, TASKS/CHANGELOG. Без push,
reviewers, других моделей, новых панелей, sudo, host installs. Исполнение кода
только в Docker 1002:1002; host Python — файлы/git/оркестрация. report.json не
требуется. На quota error — сохранить доказательство и остановиться. После
пакета остановиться с путём к result.md.
