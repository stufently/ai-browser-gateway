# M18-fix3 — сбой записи в stdout из рабочего потока завершает сервер

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `dd37a02e1a37c70d0c8a5f2855bfc7a141939e76` — вершина ветки `m18-fix2`
(M18 + fix1 + fix2, в main не влиты).
Клон /home/user/exec-clones/abg-m18-fix3-20260919, ветка m18-fix3,
origin push DISABLED. Исполнитель — cx.

## Зачем

fix2 перенёс `tools/call` в пул рабочих потоков. Ревью Codex нашло регрессию,
координатор воспроизвёл её процессом: клиент перестаёт читать stdout сервера,
но держит stdin открытым и шлёт `tools/call`. Рабочий поток ловит
`BrokenPipeError`, кладёт его в очередь `failures`, а главный поток спит в
чтении stdin и узнает об ошибке только на EOF. Сервер висит и продолжает ходить
в API шлюза по каждому новому вызову, хотя ответы доставлять некуда. На fix1
(до пула) тот же сценарий завершал процесс. Сбой записи из главного потока
(например, ответ на `ping`) по-прежнему завершает процесс — это не сломано.

## Что проверено вживую, а что предположение

Прочитано в `gateway/mcp_stdio.py` на BASE: `serve(stdin, stdout)` создаёт
очереди `pending` и `failures`, функция `work` на исключении из `emit` делает
`failures.put(exc)` и продолжает; ошибка поднимается в `serve` только после
`join` всех потоков; `main` вызывает `serve(sys.stdin, sys.stdout)` и на
`OSError`/`UnicodeError` печатает `MCP stdio error` в stderr и возвращает 1.
Чекер `docs/specs/checks/m18_fix3_brokenpipe.py` (пишет и владеет координатор)
прогнан: на BASE падает «server still running with stdin open: tools/call»; на
fix1 печатает `ok`; на ручной правке координатора (обработчик сбоя записи,
который `main` передаёт в `serve` и который делает `os._exit(1)`) печатает `ok`,
и при этом чекер fix2 `docs/specs/checks/m18_fix2_process.py` тоже `ok`.
Предположений о коде нет.

## Задача

1. Сбой записи ответа в stdout из рабочего потока приводит к немедленному
   завершению процесса с ненулевым кодом: одна строка `MCP stdio error` в
   stderr, без трейсбека, без токена. Остальные незавершённые вызовы при этом
   не дожидаются — доставить их ответы всё равно некуда.
2. `serve` остаётся тестируемой в процессе: завершение процесса делает
   `main` (через обработчик, который он передаёт в `serve`, или равноценный
   механизм), а не сама `serve`, — юнит-тесты, гоняющие `serve` на
   `io.StringIO`, не должны убивать тест-раннер.
3. Тест `MCPTests.test_worker_output_failure_triggers_handler` в
   `tests/test_mcp_stdio.py`: подменённый stdout, запись в который из
   рабочего потока бросает `BrokenPipeError`, пока stdin ещё не закончился, —
   обработчик сбоя вызывается до EOF (stdin в тесте блокируется, пока
   обработчик не сработает, с таймаутом, чтобы тест не висел).
4. Мутант в `tests/mutation_gate_gateway.py`: обработчик сбоя из рабочего
   потока не вызывается — убивается тестом из пункта 3. Итого в воротах 22.
5. Закоммитить эту спеку `docs/specs/m18-fix3-broken-pipe.md` и чекер
   `docs/specs/checks/m18_fix3_brokenpipe.py` byte-identical первым коммитом.

## Разрешения

Правка `gateway/mcp_stdio.py`, `tests/test_mcp_stdio.py`,
`tests/mutation_gate_gateway.py`. Docker-прогоны образом из критериев
(loopback внутри контейнера доступен). Commit в клоне.

## Не трогать

Чекеры `docs/specs/checks/*.py` — только закоммитить новый, не править ни
один. Всё прочее: `bench/**`, остальные модули `gateway/**`, `deploy/**`,
`scripts/**`, README.md, другие тесты и specs, TASKS.md, CHANGELOG.md,
`secrets/**`, `/home/user/services/**`. Сторонних зависимостей не добавлять.
Поведение fix1/fix2 (версии, ping, `isError`, опускание `id`, вычистка,
параллельность до 8, дренаж на EOF) не менять. Push и merge запрещены.

## Критерии приёмки

- **AC-240.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-241.** Тесты MCP зелёные, новый тест существует:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_mcp_stdio tests.test_mcp_stdio.MCPTests.test_worker_output_failure_triggers_handler'`
- **AC-242.** Чекер fix3 проходит, чекер fix2 по-прежнему проходит, оба не изменены:
  `bash -c 'printf "%s\n" "2a506f968360ee0e720039932362b960f6cb4d155ca4cd172028a7b39f592dd1  docs/specs/checks/m18_fix3_brokenpipe.py" "0181aa99b9e93f9689d4ba3442bacd66709a1c45a2b02e67c43668c60971156d  docs/specs/checks/m18_fix2_process.py" | sha256sum -c --quiet && for c in m18_fix3_brokenpipe m18_fix2_process; do test "$(timeout 120 docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-243.** Мутационные ворота шлюза: 22 мутанта, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 22 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-244.** Вне разрешённых путей чисто, спека и чекер в истории:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && git diff --exit-code dd37a02e1a37c70d0c8a5f2855bfc7a141939e76 HEAD -- . ":(exclude)gateway/mcp_stdio.py" ":(exclude)tests/test_mcp_stdio.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/specs/m18-fix3-broken-pipe.md" ":(exclude)docs/specs/checks/m18_fix3_brokenpipe.py" && git ls-files --error-unmatch docs/specs/m18-fix3-broken-pipe.md docs/specs/checks/m18_fix3_brokenpipe.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m18-fix3-20260919 --base dd37a02e1a37c70d0c8a5f2855bfc7a141939e76 --range dd37a02e1a37c70d0c8a5f2855bfc7a141939e76..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. У Grok 19.09.2026 кончился баланс (HTTP 402):
при quota error повторов не делать, записать в note и продолжать. Если
`accept_run.py` вернёт `blocked` только из-за отсутствия второго ревью — это
известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-240…AC-244,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"dd37a02e1a37c70d0c8a5f2855bfc7a141939e76","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-240","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m18-fix3-20260919 --spec /home/user/exec-clones/abg-m18-fix3-20260919/docs/specs/m18-fix3-broken-pipe.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер координатора требует поведения, противоречащего этой спеке; мутант не
убивается своим тестом; требуется правка вне разрешённых файлов. Спеку,
чекеры, AC, BASE и оснастку приёмки не менять, rc не выдумывать, чужое не
трогать.
