# M24 — независимые мутации тестов детектора Cloudflare

24.11.2026. Проверочная задача, не реализация. Код M24 писал Qwen,
мутации гоняет противоположный исполнитель (Codex).

Клон сделан `make_clone.sh --kind mut` от ветки `m24-cf-detector`,
SOURCE_SHA `866bb5ada76aa07a5778594c580e80b3f93c7bcd` (проверь
`git rev-parse HEAD`). Push запрещён. Выход — каталог `mut-out/` в корне
клона (не коммитить).

## Что мутировать

Продукт — `bench/providers/docker/probe.py`, только то, что изменила веха
(`git diff 9fb660d 866bb5a -- bench/providers/docker/probe.py`):
`_needle_not_followed`; ветки `body_cf_challenge_platform` и
`body_cf_challenges_host` в `detect_challenge`; `_scrapling_has_clearance`;
в `ScraplingAdapter.fetch` — `page_setup`/`_on_response` (фильтр
`document` + main frame, `response.headers`), основной путь (последний
документ, совпадение статуса) и запасное правило (2xx, чистое тело,
`cf_clearance` по домену хоста, срабатывает и при несовпадении статуса);
в `_playwright_body` — пропуск iframe `challenges.cloudflare.com` кроме
main frame. Прочитать целиком дифф вехи и `docs/specs/m24-cf-detector.md`.

Авторский набор — ТОЛЬКО `tests.test_detect` и `tests.test_probe`. Команда
(сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_detect tests.test_probe`

18–26 смысловых мутантов, по одному изменению, каждый в отдельной копии
дерева под `mut-out/`. Обязательные оси:
- суффиксы `/scripts/jsd/` и `/turnstile/v0/api.js` (снять, сменить регистр-
  чувствительность, проверять только первое вхождение);
- `_scrapling_has_clearance`: точное совпадение хоста, `endswith("." + d)` →
  `endswith(d)`, пустой домен, имя cookie, не-dict cookie;
- фильтр документа: `resource_type`, `frame is main_frame`, `recorded_docs[0]`
  вместо `[-1]`, `all_headers()` вместо `headers`;
- основной путь: снять сравнение статуса; запасное правило: снять 2xx, снять
  проверку тела, снять cookie, вернуть `elif` только к пустому списку;
- `_playwright_body`: снять проверку `main_frame`, сменить хост.

Для каждого: id, ось, diff, доказательство, что изменённая строка
исполняется авторским набором, команда, rc, упавший тест и строка
assertion. Syntax/import error — invalid. Нет вызова — survivor
«непокрыто». Equivalent — только с доказательством. Тест на отказ должен
падать по причине мутации, а не попутно.

## Выход и границы

`mut-out/result.md` (таблица kill/survivor/invalid/equivalent, survivors с
пояснением), `mut-out/mutations.json`, `mut-out/logs/`. В конце —
восстановленный green, `git status` клона чист, кроме `mut-out/`,
HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`). Не править
продукт, тесты, спеки, TASKS/CHANGELOG. Без push, ревьюеров, других
моделей, новых панелей, sudo, установок на хост. Код исполняется только в
Docker 1002:1002; хостовый Python — только файлы, git, оркестрация.
`report.json` не требуется. При ошибке квоты — сохранить улики и
остановиться.
