# M19-fix2 — повторный сигнал не ломает выход по прерыванию

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `4d84fdbe3527df973deda8d065ca75a87a1abddf` — вершина ветки
`m19-fix1` (результат M19-fix1, в main не влит).
Клон /home/user/exec-clones/abg-m19-fix2-20260919, ветка m19-fix2,
origin push DISABLED. Исполнитель — cx.

## Зачем

M19-fix1 принята: все семь критериев координатор перезапустил сам, pass.
Ревью Codex нашло дефект, координатор его воспроизвёл:

1. **Второй сигнал во время обработки первого вылетает наружу.** Обработчик в
   `gateway.oneshot.main` бросает `_Interrupted` при КАЖДОМ сигнале, если не идёт
   запуск `Popen`. Первый сигнал уже раскручивает лестницу; второй, пришедший,
   пока `main` печатает `{"error": "interrupted"}` или восстанавливает
   обработчики в `finally`, выбрасывает `_Interrupted` за пределы `main`:
   traceback, код 1 вместо 4, а если он пришёл посреди восстановления —
   прежние обработчики остаются не восстановлены. Двойной сигнал — обычное
   дело: Ctrl-C дважды, раннер CI шлёт TERM процессу и группе.

И одна дыра в тестах, найденная мутацией координатора:

2. **Никакой тест не требует, чтобы завершённый probe выпадал из множества
   активных.** Мутант «`self._active.discard(proc.pid)` → `pass`» выжил на
   `tests.test_oneshot`. Последствие без теста: прерывание шлёт SIGKILL и в
   группы давно завершившихся probe (на переиспользованный PID — чужой группе).

## Что проверено вживую, а что предположение

Проверено координатором в тестовом образе (`sha256:cad9a2c8…`) на дереве
BASE: скрипт, где `communicate` probe вызывает обработчик SIGTERM, а запись
строки `interrupted` в stderr вызывает его второй раз, — `main` не возвращает
код, наружу выходит `_Interrupted`. Правка «бросать только на ПЕРВОМ сигнале»:

```python
def interrupt(signum, frame):
    first = not launcher._interrupted
    launcher._interrupted = True
    launcher.kill_active()
    if first and not launcher._starting:
        raise _Interrupted
```

на том же скрипте даёт `rc=4`, обработчики восстановлены, `tests.test_oneshot`
зелёный. Повторный сигнал при этом по-прежнему убивает активные группы
(`kill_active` вызывается всегда). Предположений о коде нет.

## Задача

1. `gateway/oneshot.py`: `_Interrupted` бросается только на первом сигнале
   прогона; повторные сигналы только убивают активные группы (SIGKILL) и
   возвращаются. Отложенный путь (сигнал во время `Popen`) не менять.
2. Тесты в `tests/test_oneshot.py`, класс `OneshotTests`, ровно с именами:
   - `test_repeated_signal_still_exits_interrupted` — второй сигнал приходит
     (а) во время записи строки `interrupted` в stderr и (б) во время
     восстановления обработчиков; оба раза `main` возвращает 4, stdout пуст,
     последняя строка stderr — `{"error": "interrupted"}`, обработчики
     SIGTERM/SIGINT/SIGHUP после возврата равны исходным;
   - `test_finished_probe_not_killed_on_interrupt` — первый probe завершился,
     сигнал приходит во время второго: `os.killpg` вызван ровно один раз, с
     PID второго probe и SIGKILL.
3. Мутанты в `tests/mutation_gate_gateway.py` — два новых, каждый убивается
   своим тестом из пункта 2: (а) обработчик бросает на каждом сигнале (условие
   `first and` убрано); (б) `self._active.discard(proc.pid)` → `pass`.
   Итого 29.
4. Закоммитить эту спеку `docs/specs/m19-fix2-second-signal.md`
   byte-identical первым коммитом.

## Разрешения

Правка `gateway/oneshot.py`, `tests/test_oneshot.py`,
`tests/mutation_gate_gateway.py`. Сборка образа (сеть только на сборку) и
прогоны образом из критериев. Commit в клоне.

## Не трогать

Чекеры `docs/specs/checks/*.py`, `deploy/**`, `bench/**`, прочие модули
`gateway/**`, `scripts/**`, README.md, другие тесты и specs, TASKS.md,
CHANGELOG.md, `secrets/**`, `/home/user/services/**`, registry (ничего не
push'ить). `pyproject.toml`: `dependencies = []`. Push и merge запрещены.

## Критерии приёмки

- **AC-270.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-271.** Тесты one-shot зелёные, два новых теста существуют:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_oneshot tests.test_oneshot.OneshotTests.test_repeated_signal_still_exits_interrupted tests.test_oneshot.OneshotTests.test_finished_probe_not_killed_on_interrupt'`
- **AC-272.** Образ пересобирается, оба чекера M19 проходят внутри него и не изменены:
  `bash -c 'docker build -q -f deploy/Dockerfile.oneshot -t abg-oneshot:m19fix2 . >/dev/null && printf "%s\n" "72ae5dfb854470b159bc9511d3e83ea819f820d09b41f3836dc3ef75d6f0dddb  docs/specs/checks/m19_fix1_process.py" "ba67a2a044f8acde01c3195643b932a514dc4a1af642622d9b21251c74526aec  docs/specs/checks/m19_oneshot_image.py" | sha256sum -c --quiet && test "$(timeout 900 docker run --rm --network none --user 1002:1002 --entrypoint /usr/bin/tini -v "$PWD/docs/specs/checks/m19_fix1_process.py:/check.py:ro" abg-oneshot:m19fix2 -s -- python3 /check.py)" = ok && test "$(timeout 900 docker run --rm --network none --user 0:0 --entrypoint python3 -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m19fix2 /check.py)" = ok'`
- **AC-273.** Мутационные ворота шлюза: 29 мутантов, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 29 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-274.** Вне разрешённых путей чисто, спека в истории:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && git diff --exit-code 4d84fdbe3527df973deda8d065ca75a87a1abddf HEAD -- . ":(exclude)gateway/oneshot.py" ":(exclude)tests/test_oneshot.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/specs/m19-fix2-second-signal.md" && git ls-files --error-unmatch docs/specs/m19-fix2-second-signal.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m19-fix2-20260919 --base 4d84fdbe3527df973deda8d065ca75a87a1abddf --range 4d84fdbe3527df973deda8d065ca75a87a1abddf..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 и кодом 3 — при таких ошибках повторов не делать, записать в note
и продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-270…AC-274,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"4d84fdbe3527df973deda8d065ca75a87a1abddf","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-270","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m19-fix2-20260919 --spec /home/user/exec-clones/abg-m19-fix2-20260919/docs/specs/m19-fix2-second-signal.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер координатора требует поведения, противоречащего этой спеке; мутант не
убивается своим тестом; требуется правка вне разрешённых файлов. Спеку,
чекеры, AC, BASE и оснастку приёмки не менять, rc не выдумывать, чужое не
трогать, ничего не публиковать в registry.
