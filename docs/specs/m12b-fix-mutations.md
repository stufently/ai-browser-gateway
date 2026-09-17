# M12b-fix — независимые мутации новых тестов runner

17.09.2026. Проверочная задача cx, не реализация. Директива владельца 17.09:
«доделывай всё, используя кодекс». Runner писала другая cx-панель.

Клон /home/user/exec-clones/abg-m12b-fix-mutations-20260917, ветка
m12b-fix-mutations, origin push DISABLED. SOURCE_SHA
`895bc83e9f5b4e2339a68783fe8adcad162b8b64` (FINAL M12b-fix).
Выход: /home/user/.cache/abg-coord-20260917/m12b-fix-mutations/.

## Что мутировать

Продукт мутаций — `tests/deployed_m12b.py` (функции `redact`, `docker`,
`parse_api`, `api_evidence`, `echo_result`, `classify_profiles`,
`rotation_path`, `first_egress`, `assert_egress`, `wait_gap`, `worker`).
Прочитать целиком его, `docs/specs/m12b-deploy.md` и `docs/specs/m12b-fix.md`.
Прошлый прогон (SOURCE `25dfa5c`) дал 5 survivors — M07 non-200 с валидным
телом, M09 `ok` не bool, M10 отрицательный `elapsed_ms`, M11 инфраструктурная
ошибка только в attempts, M21 две egress-попытки; веха m12b-fix добавила тесты.
Обязательно повторить эти пять и мутировать НОВЫЕ правила: строгие множества
error_type/challenge/next_step/step, диапазон status 100..599, age_hours,
read-only проверка release (symlink, лишний/недостающий файл, hash, режимы,
отсутствующий manifest) и отсутствие записей.
Авторский набор — ТОЛЬКО `tests.test_deployed_m12b`. Команда (сначала green на
SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_deployed_m12b`

28–36 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: редакция (URL userinfo, Bearer,
token=, hex64, ключи словаря); `parse_api` (не-200, не-JSON, схема, attempts,
отказ на provider_error/environment_error); классификация echo (direct_ip,
duplicate_ip, http_*, invalid_ip, timeout); `rotation_path` (wraparound,
промежуточные нерабочие, пул <3); `first_egress`/`assert_egress` (direct
content_missing, ровно один egress, ok, IP в content, точный профиль);
`wait_gap` (30 с на hostname, разные hostname не ждут); worker (echo-сетевой
отказ внешний, API-отказ внутренний, тело не выходит наружу).

Для каждого: id, ось, diff, SHA исходника/мутанта/восстановления, доказательство
активации изменённой строки авторским набором, команда/cwd/rc, лог, упавший
тест и строка assertion. Syntax/import error — invalid. Нет вызова — survivor
«непокрыто». Equivalent — только с доказательством. Тест на отказ должен падать
по причине мутации.

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, survivors с пояснением),
`mutations.json`, `commands.json`, `logs/`, `SHA256SUMS`. В конце —
восстановленный green, `git status` клона пуст, HEAD == SOURCE_SHA.

Ничего не коммитить. Не запускать режимы runner против сервиса, не ходить в сеть
(`--network none`), не трогать `/home/user/services/**`, секреты, Docker-сокет
в контейнерах. Не править продукт, тесты, specs, TASKS/CHANGELOG. Без push,
reviewers, других моделей, новых панелей, sudo, host installs. Исполнение кода
только в Docker 1002:1002; host Python — файлы/git/оркестрация. report.json не
требуется. На quota error — сохранить доказательство и остановиться.
