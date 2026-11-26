# M29 — независимые мутации тестов окружения прокси

26.11.2026. Проверочная задача, не реализация. Код M29 писал Codex,
мутации гоняет противоположный исполнитель (Qwen).

Клон сделан `make_clone.sh --kind mut` от ветки `m29-proxy-env`,
SOURCE_SHA `43b12c7` (полный — `git rev-parse HEAD`). Push запрещён.
Выход — каталог `mut-out/` в корне клона (не коммитить).

## Что мутировать

Только код вехи: `git diff 3ab0356 HEAD -- bench/providers/docker/probe.py`.
Прочитать дифф и `docs/specs/m29-proxy-env.md` целиком. Оси:
- `main()`: забор `ABG_PROXY` (`pop` против `get`, до разбора аргументов,
  значение по умолчанию `""`, присваивание глобали);
- `_proxy_url`: ветка `None` (до `main()` читается `os.environ`), пустое
  захваченное значение не уступает `os.environ`;
- `urlopen` и `redact`: источник значения прокси;
- `_curl_env`: фильтр `*_proxy` без учёта регистра, применение в `start()`
  и в `navigate()`;
- `CurlAdapter.navigate`: экранирование `\` и `"` (и порядок замен), `\r`,
  `\n`; `--config -` только при прокси; `input` только при прокси; URL
  последним аргументом.

Авторский набор — `tests.test_proxy_env`, `tests.test_probe`. Команда
(сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_proxy_env tests.test_probe`

Мутант убит, если команда падает. 14–20 смысловых мутантов, по одному
изменению, каждый в отдельной копии дерева под `mut-out/`. Для каждого:
id, ось, diff, доказательство исполнения строки, rc, упавший тест и
assertion. Syntax/import error — invalid; нет вызова — survivor
«непокрыто»; equivalent — только с доказательством.

## Выход и границы

`mut-out/result.md` (таблица kill/survivor/invalid/equivalent),
`mut-out/mutations.json` (поля id, axis, diff, status), `mut-out/logs/`.
В конце — восстановленный green, `git status` чист кроме `mut-out/`,
HEAD == SOURCE_SHA. Ничего не коммитить, не ходить в сеть, не править
продукт/тесты/спеки, без push, ревьюеров, новых панелей, sudo, установок.
Код — только в Docker 1002:1002. `report.json` не нужен. При ошибке квоты —
сохранить улики и остановиться.
