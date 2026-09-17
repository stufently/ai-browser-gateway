# M13b — независимые мутации тестов уборки позднего контейнера (после fix4)

17.09.2026. Проверочная задача cx, не реализация. Директива владельца 17.09:
«доделывай всё до конца». Правку и тесты писала другая cx-панель.

Клон /home/user/exec-clones/abg-m13b-mutations2-20260917, ветка
m13b-mutations2, origin push DISABLED. SOURCE_SHA `9c23c17` (FINAL M13b-fix4,
полный SHA — `git rev-parse 9c23c17` в клоне).
Выход: /home/user/.cache/abg-coord-20260917/m13b-mutations2/. Прогон по
`858fd85` остановлен координатором; fix2/fix3 сразу переделаны.

## Что мутировать

Продукт мутаций — `DockerLauncher.run` и `DockerLauncher._cleanup` в
`bench/runner/execute.py`. Прочитать целиком `docs/specs/m13b-fix.md`, `docs/specs/m13b-fix2.md`, `docs/specs/m13b-fix3.md`, `docs/specs/m13b-fix4.md`,
`docs/specs/m13b-late-container-probe.md` и `git diff 5a508e4 9c23c17`.

Авторский набор — `tests.test_execute.DockerLauncherTests` и отдельно frozen
probe `tests.probe_m13_late_container`. Команды (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_execute.DockerLauncherTests`

и та же с `tests.probe_m13_late_container`. Для каждого мутанта записать
результат ОБОИХ наборов раздельно; kill засчитывается по авторскому набору,
probe — справочно.

20–30 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: идентичность (одна и та же метка на
все запуски; метка не добавляется; метка добавляется и не-`docker run`
командам; фильтр `ps` без `label=` / по префиксу `abg.launch`); бюджет (30 →
60, 30 → 1, дедлайн пересчитывается на каждой итерации, `timeout=remaining` →
`timeout=30`, убрать `remaining > 0` перед rm, бесконечный цикл без
дедлайна); опрос (одна попытка без цикла, выход после пустого `ps`, выход после
неуспешного rm, брать `stdout` при `returncode != 0`); cidfile (игнорировать
cidfile, cidfile без fallback на метку при OSError); ошибки (не ловить
`OSError`/`SubprocessError`, поднять исключение уборки вместо исходного
`TimeoutExpired`); env (не передавать `env` в уборку); `stdin=DEVNULL`
убрать в уборке; «увиденный» контейнер (`seen = False` изначально при
заполненном cidfile, не обновлять `seen` после непустого `ps`, возврат на
пустом `ps` без проверки `seen`, возврат на пустом `ps` при `returncode != 0`,
не сбрасывать `cid` — повторять `rm` по cidfile вслепую, убрать `continue`
после неуспешного `rm`); пауза (убрать `time.sleep` перед повторным `rm`,
не выставлять `pause_before_removal = True`, не сбрасывать его после сна);
полные ID (убрать `--no-trunc`, обрезать найденные ID до 12 символов).

Для каждого: id, ось, diff, SHA256 исходника/мутанта/восстановления,
доказательство активации изменённой строки авторским набором, команда/cwd/rc,
лог, упавший тест и строка assertion. Syntax/import error — invalid. Нет вызова
— survivor «непокрыто». Equivalent — только с доказательством. Тест на отказ
должен падать по причине мутации, а не по побочному эффекту (например,
зависание по таймауту стенда — не kill, а отдельный класс).

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, survivors с пояснением),
`mutations.json`, `commands.json`, `logs/`, `SHA256SUMS`. В конце —
восстановленный green, `git status` клона пуст, HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`), реальный Docker-сокет
в контейнеры не монтировать, не трогать `/home/user/services/**`, сервис,
секреты. Не править продукт, тесты, specs, TASKS/CHANGELOG. Без push,
reviewers, других моделей, новых панелей, sudo, host installs. Исполнение кода
только в Docker 1002:1002; host Python — файлы/git/оркестрация. report.json не
требуется. На quota error — сохранить доказательство и остановиться. После
пакета остановиться с путём к result.md.
