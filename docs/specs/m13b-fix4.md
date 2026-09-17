# M13b-fix4 — полные ID контейнеров в уборке (--no-trunc)

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `49a876f7fd189d7b69bb510dde8f2e20bff5cf0f` — FINAL M13b-fix3.
Клон /home/user/exec-clones/abg-m13b-fix4-20260917, ветка m13b-fix4, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»). M13b-fix…fix3 писали другие cx-панели.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002 с `--network none`; host — git/файлы/оркестрация. Реальный
Docker-сокет в контейнеры не монтировать.

## Задача

Codex result review M13b-fix3 нашёл, координатор подтвердил чтением
`bench/runner/execute.py:_cleanup`: `docker ps --all --quiet --filter
label=<identity>` без `--no-trunc` возвращает сокращённые 12-символьные ID,
которые уходят в `docker rm --force`. Docker разрешает ссылку сначала по
имени (moby `daemon/container.go` GetContainer): если у чужого контейнера имя
совпадает с коротким ID нашего, удаляется чужой, `rm` успешен, уборка
возвращается, а свой контейнер остаётся жить.

Требование: все вызовы `docker ps` в `DockerLauncher._cleanup` добавляют
`--no-trunc` (полный 64-символьный ID); в `docker rm --force` передаются только
ID, полученные так или прочитанные из cidfile (клиент Docker пишет туда полный
ID). Больше ничего в поведении fix…fix3 не менять: уникальная метка, единый
дедлайн 30 с, `timeout=remaining`, `env`, `stdin=DEVNULL`, немедленная
проверка по метке после неуспешного `rm`, пауза перед повторным `rm`,
«увиденный» контейнер + пустой успешный `ps` → возврат, исходный
`TimeoutExpired` тем же объектом.

Тесты в `tests/test_execute.py` (`DockerLauncherTests`): обновить точные
ожидания команды `ps` (добавлен `--no-trunc`); новый тест, падающий на BASE по
причине: фейковый Docker моделирует контейнеры с полным ID и именами, `ps` без
`--no-trunc` отдаёт 12-символьный префикс, с `--no-trunc` — полный ID, `rm`
разрешает ссылку сначала по точному имени, затем по полному ID/префиксу; чужой
контейнер назван коротким ID нашего → после уборки свой удалён, чужой жив.
Существующие тесты fix…fix3 сохранить (кроме механического добавления флага в
ожидаемые команды).

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: `_cleanup` строит `['docker', 'ps',
'--all', '--quiet', '--filter', 'label=' + identity]`; frozen probe
`tests/probe_m13_late_container.py` (строки ~171–192) разбирает только
`--filter` и отдаёт свои ID, флаг `--no-trunc` его не ломает — предположение
до прогона AC-971; если краснеет — blocker с тестом и строкой assertion.
Утверждение про приоритет имени — из ссылки Codex на moby v29.8.0, координатор
её не открывал: это предположение, тест моделирует его явно.

## Разрешения

Правка `bench/runner/execute.py` (только `DockerLauncher._cleanup`),
`tests/test_execute.py`. Commit в клоне.

## Не трогать

Probe `tests/probe_m13_late_container.py`, frozen probes M9–M12, gateway/**,
остальной bench/**, deploy/**, scripts/**, остальные tests, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m13b-fix4.md`).

## Критерии приёмки

- **AC-971.** Probe M13 зелёный и неизменный:
  `bash -c 'test "$(sha256sum tests/probe_m13_late_container.py | cut -d" " -f1)" = 68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m13_late_container'`
- **AC-972.** Frozen probes M9–M12 неизменны и зелёные:
  `bash -c 'git diff --exit-code 49a876f7fd189d7b69bb510dde8f2e20bff5cf0f HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-973.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-974.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 49a876f7fd189d7b69bb510dde8f2e20bff5cf0f HEAD -- . ":(exclude)bench/runner/execute.py" ":(exclude)tests/test_execute.py" ":(exclude)docs/specs/m13b-fix4.md"'`
- **AC-975.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13b-fix4.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 49a876f7fd189d7b69bb510dde8f2e20bff5cf0f --range 49a876f7fd189d7b69bb510dde8f2e20bff5cf0f..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-971…AC-975,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"49a876f7fd189d7b69bb510dde8f2e20bff5cf0f","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-971","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13b-fix4-20260917 --spec /home/user/exec-clones/abg-m13b-fix4-20260917/docs/specs/m13b-fix4.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если probe M13 нельзя сделать
зелёным правкой только `bench/runner/execute.py`, если правка ломает frozen
probe M9–M12, или если probe требует поведения, противоречащего контракту выше
(записать тест и строку assertion). Probe, спеку, AC, BASE и оснастку не
менять, rc не выдумывать.
