# M12a-tests — закрыть три выживших мутанта

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `aaf5ca79710b41a769276822bd18425b1dbab9d0` — FINAL M12a-fix.
Клон /home/user/exec-clones/abg-m12a-tests-20260917, ветка m12a-tests,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026).
Продукт писала другая cx-панель, мутации гоняла третья; их контекст не нужен.

Только этот клон. Push/merge/deploy запрещены. Импорт и исполнение продукта —
только Docker 1002:1002 на `sha256:cad9a2c8…25ef6` (полный digest в командах
ниже); host — git/files/оркестрация. Сигналы и процессы — только свои и только
внутри Docker. Без sudo, host installs, реальных секретов, чужих деревьев.

## Задача

Это веха ТОЛЬКО ТЕСТОВ. Код продукта верен; независимая мутация 32 вариантов
дала 29 kill и 3 survivor — дыры авторского набора. Патчи выживших лежат в
`docs/specs/m12a-tests-mutants/` (M03, M29, M30). Добавить проверки
НАБЛЮДАЕМОГО поведения, которые на каждом из трёх мутантов падают
assertion-failure (`FAIL:`, не `ERROR:` и не зависание), а на BASE проходят.
Не писать тест, сверяющий текст исходника или конкретную строку кода.

1. **M03 — граничные пробелы токена.** Контракт
   `docs/specs/m12a-service-contract.md`: токен по правилам M11, допускается
   только ЗАВЕРШАЮЩИЙ CR/LF. Сейчас нет проверки, что `b' token'`,
   `b'token '`, `b'\ttoken'`, `b'token\t'`, `b'\ntoken'` отвергаются
   `make_service` до bind. Мутант заменяет `rstrip('\r\n')` на `strip()`.
   Место: `tests/test_service_config.py`.
2. **M29 — синхронное закрытие допуска по сигналу.** Сразу после возврата
   обработчика SIGTERM/SIGINT, ДО завершения `serve_forever`, новый provider
   launch этой установки уже отвергнут (наблюдаемо через `server.factory` /
   `LabeledLauncher` с `gate=server.launches` / HTTP-запрос с фейковым
   Docker IO). Мутант убирает `server.launches.stop()` из обработчика; admission
   тогда закрывается только в `finally`. Детерминированно: задержать
   фактическое завершение `server.shutdown`/`serve_forever` барьером, а не
   sleep. Место: `tests/test_service_shutdown.py`.
3. **M30 — порядок финальной уборки.** Последний вызов `sweep_providers`
   происходит ПОСЛЕ того, как последний допущенный запуск вышел из gate
   (active==0), и при этом контейнер, созданный между последним промежуточным
   sweep и выходом запуска из gate, убран. Мутант переносит финальный sweep в
   начало `drain`. Место: `tests/test_service_shutdown.py`.

Продукт (`gateway/**`, `scripts/**`, `deploy/**`, `bench/**`), остальные тесты,
frozen probes и контракт не менять. Если какое-то свойство нельзя проверить без
правки продукта — это blocker, не обход.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: все 6 AC M12a-fix перезапущены (452 unit
OK, frozen probes OK, live rc=0); авторский набор из 11 модулей — 39 tests OK
на BASE. Патчи M03/M29/M30 применяются к BASE и дают green авторского набора и
frozen probes `tests.probe_m12_service_regressions`, `tests.probe_m12_service`
(перепроверено координатором). Предположение: все три свойства наблюдаемы
через существующие швы (`server.launches`, `server.factory`,
`service.sweep_providers`, `signal.signal`) без правки продукта.

## Разрешения

Правка `tests/test_service_config.py` и `tests/test_service_shutdown.py`,
Docker-прогоны, read-only reviews, commit.

## Не трогать

Всё вне двух тестовых файлов и этой спеки с каталогом патчей. Первым делом
закоммитить в клоне `docs/specs/m12a-tests.md` и `docs/specs/m12a-tests-mutants/`
byte-identical (они приезжают untracked); контракт
`docs/specs/m12a-service-contract.md` уже в git на BASE, его не менять.
Тест-модули с новыми проверками — только `tests/test_service_config.py` и
файл shutdown-тестов рядом (под шаблон `tests/test_service_[cs]*.py`), новые
файлы по этому шаблону не заводить.

## Критерии приёмки

- **AC-501.** Полный unittest:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-502.** Патчи мутантов неизменны:
  `bash -c 'echo "274fc88f834c3b6467568db438f831741212007b9f24fd1c00a44eb189784285  docs/specs/m12a-tests-mutants/M03.patch" | sha256sum -c - && echo "756551373408f9c6f77041f31c7c0c9603bd7c8e22985102de75902fc0d8388a  docs/specs/m12a-tests-mutants/M29.patch" | sha256sum -c - && echo "0c6e8a6f6da1e11fc00c4cb2b9923406c05a9f8e05c428a324b6f1583a62f439  docs/specs/m12a-tests-mutants/M30.patch" | sha256sum -c -'`
- **AC-503.** Каждый из трёх мутантов убит assertion-failure:
  `bash -c 'for m in M03 M29 M30; do d=$(mktemp -d); git archive HEAD | tar -x -C "$d" && patch -s -d "$d" -p1 < docs/specs/m12a-tests-mutants/$m.patch || exit 2; timeout 300 docker run --rm --user 1002:1002 -v "$d":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . -p "test_service_[cs]*.py" > "$d.log" 2>&1; if grep -q "^FAIL:" "$d.log"; then echo "$m killed"; else echo "$m survived"; exit 1; fi; done'`
- **AC-504.** Вне разрешённого ничего не изменено:
  `bash -c 'git diff --exit-code aaf5ca79710b41a769276822bd18425b1dbab9d0 HEAD -- . ":(exclude)tests/test_service_[cs]*.py" ":(exclude)docs/specs/m12a-tests.md" ":(exclude)docs/specs/m12a-tests-mutants"'`
- **AC-505.** Чистое дерево и спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m12a-tests.md docs/specs/m12a-tests-mutants/M03.patch docs/specs/m12a-tests-mutants/M29.patch docs/specs/m12a-tests-mutants/M30.patch >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, поэтому ревьюеры **agy + grok**
(не codex). После commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base aaf5ca79710b41a769276822bd18425b1dbab9d0 --range aaf5ca79710b41a769276822bd18425b1dbab9d0..<REVIEW_SHA> --context "<эта спека и контракт; только чтение>"`
и тот же wrapper `initial grok` с теми же base/range/context. Разобрать ВСЕ
finding_id: fixed с proof/commit, disproved с proof, иначе needs_owner. Один
FIX_ONCE, затем verify теми же ревьюерами на REVIEW..FINAL. Неполный ответ или
таймаут — не принятие; один технический повтор; quota error — без повторов.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-501…AC-505,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"aaf5ca79710b41a769276822bd18425b1dbab9d0","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-501","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m12a-tests-20260917 --spec /home/user/exec-clones/abg-m12a-tests-20260917/docs/specs/m12a-tests.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если
свойство нельзя наблюдать без правки продукта, если мутант не убивается
assertion без проверки текста исходника, или если оснастка ревью/приёмки
отказывает. Спеку, патчи, AC, BASE и оснастку не менять, rc не выдумывать.
