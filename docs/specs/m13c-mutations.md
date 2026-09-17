# M13c — независимые мутации тестов deployed runner

17.09.2026. Проверочная задача cx, не реализация. Директива владельца 17.09:
«доделывай все до конца кодексом». Правку и тесты писала другая cx-панель.

Клон /home/user/exec-clones/abg-m13c-mutations-20260917, ветка
m13c-mutations, origin push DISABLED. SOURCE_SHA `123bffe` (FINAL M13c,
полный SHA — `git rev-parse 123bffe` в клоне).
Выход: /home/user/.cache/abg-coord-20260917/m13c-mutations/.

## Что мутировать

Продукт мутаций — изменения M13c в `tests/deployed_m12b.py`: `main()` (разбор
`--release`/`--evidence`, пересчёт `SHA`/`RELEASE`/`IMAGE`/`EVIDENCE`, выбор
режима), `check_bizprofile`, ветка `bizprofile` в `worker()`, `save(...,
exclusive=True)`, `wait_gap`/`save` с `folder=None`. Прочитать целиком
`docs/specs/m13c-deploy.md` и `git diff 4409f8a 123bffe`.

Авторский набор — `tests.test_deployed_m12b`. Команда (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_deployed_m12b`

20–30 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: аргументы (регулярка sha допускает
заглавные / любые 40 символов / любую длину; убрать проверку абсолютного пути;
`parser.error` → `print` без выхода; валидация после `mkdir` каталога улик;
не пересчитывать `RELEASE` или `IMAGE` или `EVIDENCE`; `IMAGE` из `SHA[:7]`);
запрос bizprofile (передавать `expected_text` = маркер; `expected_text: None`
в теле; `allow_browser=false`; другой `budget_ms`; порядок страниц обратный;
убрать `wait_gap`); критерий прохождения (убрать по одному каждое условие:
`ok`, `provider`, provider последней попытки, `success`, `challenge`,
`error_type`, `marker_found`; `all` → `any`; проверять первую попытку вместо
последней); ошибки (исключение первой страницы прерывает цикл; ошибка не
делает `passed=False`); улики (не писать архив; `exclusive=False`; архив
после `require`; `bizprofile.json` не писать; content или URL попадает в
улики; маркер уходит в API вместо проверки у себя); worker (`marker_found`
всегда True; ветка bizprofile без `Authorization`).

Для каждого: id, ось, diff, SHA256 исходника/мутанта/восстановления,
доказательство активации изменённой строки авторским набором, команда/cwd/rc,
лог, упавший тест и строка assertion. Syntax/import error — invalid. Нет вызова
— survivor «непокрыто». Equivalent — только с доказательством. Тест на отказ
должен падать по причине мутации, а не по побочному эффекту.

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, survivors с пояснением),
`mutations.json`, `commands.json`, `logs/`, `SHA256SUMS`. В конце —
восстановленный green, `git status` клона пуст, HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`), реальный Docker-сокет
в контейнеры не монтировать, НЕ запускать `tests/deployed_m12b.py` вне
unittest (никаких deployed-проверок), не трогать `/home/user/services/**`,
сервис, секреты, `/home/user/.cache/abg-coord-20260917/m13c*` кроме своего
выхода. Не править продукт, тесты, specs, TASKS/CHANGELOG. Без push,
reviewers, других моделей, новых панелей, sudo, host installs. Исполнение кода
только в Docker 1002:1002; host Python — файлы/git/оркестрация. report.json не
требуется. На quota error — сохранить доказательство и остановиться. После
пакета остановиться с путём к result.md.
