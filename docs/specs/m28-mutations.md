# M28 — независимые мутации тестов образов провайдеров

24.11.2026. Проверочная задача, не реализация. Код M28 писал Codex,
мутации гоняет противоположный исполнитель (Qwen).

Клон сделан `make_clone.sh --kind mut` от ветки `m28-provider-images-health`,
SOURCE_SHA `827ef99` (полный — `git rev-parse HEAD`). Push запрещён.
Выход — каталог `mut-out/` в корне клона (не коммитить).

## Что мутировать

Только код вехи: `git diff 15640fc HEAD -- gateway/ tests/deployed_m12b.py`.
Прочитать дифф и `docs/specs/m28-provider-images-health.md` целиком. Оси:
- `gateway/provider_images.py`: `route_images` (берётся из `plan_product`
  и registry, сортировка, дедупликация), `_probe` (фильтры `reference=`
  для каждого образа, ненулевой rc → `provider_images_unknown`, сравнение
  с выводом, список `missing` в исходном порядке, таймаут 3 с), `status`
  (кэш 15 с, `>=` против `>`, кэш и неудачи, исключение → unknown,
  `deepcopy`, блокировка);
- `gateway/api_http.py`: `/health` — 200 только при `ok is True`, иначе 503;
  `health_check is None` → `{'ok': True}`; исключение или не-dict →
  `provider_images_unknown`; `/health` без авторизации;
- `gateway/httpapi.py`: проверка `callable(health_check)`;
- `gateway/service.py`: `ImageCheck().status` по умолчанию;
- `tests/deployed_m12b.py`: `check_deploy` (после `verify_release`,
  недостающие образы → `provider_images_missing` с `missing_images`,
  таймаут 30 с), `check_bizprofile` (любой провайдер, но совпадает с
  последней попыткой; пустой/не-строковый провайдер — провал; `providers`
  в результате), `main` (детали `CheckError` в выводе и файле, `redact`).

Авторский набор — `tests.test_provider_images`, `tests.test_deployed_m12b`
и чекер `docs/specs/checks/m28_provider_images.py` (печатает `ok`).
Команды (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.test_provider_images tests.test_deployed_m12b`

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m28_provider_images.py`

Мутант убит, если падает хотя бы одна команда (запиши какая). 18–24
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
