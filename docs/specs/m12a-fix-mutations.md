# M12a-fix — независимые мутации новых авторских тестов

17.09.2026. Проверочная задача cx, не реализация. Директива владельца 17.09:
оставшиеся задачи M12 через cx; код писала ДРУГАЯ cx-панель, её контекст
тебе не виден и не нужен.

Клон /home/user/exec-clones/abg-m12a-fix-mutations-20260917, ветка
m12a-fix-mutations, origin push DISABLED. SOURCE_SHA
`aaf5ca79710b41a769276822bd18425b1dbab9d0` (FINAL M12a-fix, не принята).
Выход: /home/user/.cache/abg-coord-20260917/m12a-fix/mutations/.

## Что мутировать

Продукт: `gateway/service.py` (LaunchGate, LabeledLauncher, sweep_providers,
_proxy, read_private, make_service, main), `gateway/health_monitor.py`,
`scripts/abg-provision`, `scripts/abg-release`, rotation в
`gateway/api_http.py`. Прочитать их целиком и контракт
`docs/specs/m12a-service-contract.md`.

Авторский набор (ТОЛЬКО он засчитывает kill):
`tests.test_service tests.test_health_monitor tests.test_provision
tests.test_release tests.test_service_config tests.test_service_launcher
tests.test_service_rotation tests.test_service_shutdown
tests.test_health_monitor_contract tests.test_provision_contract
tests.test_release_contract`.

Команда (сначала green на SOURCE без изменений):

`docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q <набор выше>`

От 24 до 32 смысловых мутантов, по одному изменению, каждый в ОТДЕЛЬНОЙ копии
дерева под выходным каталогом (исходный клон не править). Обязательные оси —
ровно те, что на BASE выжили или не были покрыты:
- make_service: права/uid/тип файлов, конфликт ABG_TOKEN, байты токена,
  формат профилей, instance/port/limit, opt-in rotation;
- таймаут и scope cleanup-команд (`sweep_providers`);
- check_once: тело health (только `ok` literal true), отказ редиректов,
  cap таймаута, ping failure сохраняет результат health, редакция ошибок, loop;
- provision: кодирование пароля И логина, ровно 15 (без ms16), атомарность
  публикации, duplicate/empty/missing source, no-overwrite;
- release: mode 0644 обычных файлов и 0755 исполняемых/каталогов, symlink
  manifest и файла дерева, content mismatch;
- shutdown: убрать `launches.check()` после захвата слота; убрать `stop()` из
  обработчика сигнала; финальный sweep ДО ожидания active==0; не
  декрементировать active в finally; `_proxy` без C1/isspace.

Для каждого: id, ось, diff, SHA исходника/мутанта/восстановления, доказательство
АКТИВАЦИИ (изменённая строка реально исполнена авторским набором — например
coverage-трасса или маркер в копии), команда/cwd/rc, полный лог, упавший тест и
строка assertion. Syntax/import/fixture error — invalid, не kill. Нет вызова
изменённой строки — survivor «непокрыто», не invalid. Эквивалентный мутант —
только с доказательством неотличимости по контракту. У теста на ОТКАЗ проверить,
что он падает по ПРИЧИНЕ мутации, а не из-за другого отказа.

Frozen probes (`tests/probe_*`) и старые тесты НЕ считаются. Live не нужен.

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, список survivors с
пояснением какого свойства не хватает тестам), `mutations.json`,
`commands.json`, `logs/`, `SHA256SUMS`. В конце — восстановленный green той же
командой и `git status` клона пуст, HEAD == SOURCE_SHA.

Не коммитить ничего. Не править продукт, тесты, specs, TASKS/CHANGELOG. Не
push/merge/deploy. Без reviewers, других моделей, новых панелей, sudo, host
installs. Импорт и исполнение продукта — только Docker 1002:1002; host Python
только для файлов/git/оркестрации. Не читать реальные .env/секреты, чужие
деревья и сервисы; внешние цели не нужны. Сигналы/процессы — только внутри
Docker и только свои. report.json не требуется. На quota error — сохранить
доказательство и остановиться. После пакета остановиться, указать путь.
