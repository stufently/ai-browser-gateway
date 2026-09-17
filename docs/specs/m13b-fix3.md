# M13b-fix3 — без горячего цикла rm→ps при устойчивой ошибке удаления

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `498c4d3c230495bdbb99fb5358f3d985ea55a35e` — FINAL M13b-fix2.
Клон /home/user/exec-clones/abg-m13b-fix3-20260917, ветка m13b-fix3, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»). M13b-fix и fix2 писали другие cx-панели.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002 с `--network none`; host — git/файлы/оркестрация. Реальный
Docker-сокет в контейнеры не монтировать.

## Задача

Codex result review M13b-fix2 нашёл, координатор подтвердил чтением
`bench/runner/execute.py:_cleanup`: после ненулевого `docker rm` безусловный
`continue` обходит `time.sleep`. Если контейнер остаётся видимым по метке, а
`rm` устойчиво падает (daemon error, removal in progress), цикл `ps→rm` идёт
без пауз весь бюджет 30 с — с фейковыми командами по 1 мс это ~30 000 вызовов
Docker.

Требование (контракт поведения): после неуспешного `rm` проверка по метке
(`docker ps --all --quiet --filter label=<identity>`) выполняется СРАЗУ, без
паузы — чтобы уже удалённый контейнер (fix2) по-прежнему давал немедленный
возврат. Но если эта проверка показала контейнер (или сама не удалась), перед
следующим `rm` обязательна пауза `time.sleep(min(0.1, remaining))`, как в
остальных ветках цикла. Иначе говоря: между двумя последовательными вызовами
`docker rm` всегда есть хотя бы один `time.sleep` с положительным аргументом.
Все прочие свойства M13b-fix/fix2 сохраняются: уникальная метка, единый
дедлайн 30 с, `timeout=remaining`, `env`, `stdin=DEVNULL`, только свой
контейнер, исходный `TimeoutExpired` тем же объектом, «увиденный» контейнер +
пустой успешный `ps` → немедленный возврат, неуспешный `ps` ничего не
доказывает, нормальный путь не меняется.

Тесты в `tests/test_execute.py` (`DockerLauncherTests`, фейковые
`subprocess.run`, часы и `time.sleep`), падающие на BASE по причине:
- `rm` всегда rc=1, `ps` по метке всегда возвращает id (cidfile есть и нет):
  между любыми двумя последовательными `rm` в журнале вызовов есть `sleep` с
  аргументом > 0; число вызовов ограничено (фейковые вызовы не двигают часы,
  двигает только `sleep`) — например, не больше ~2 × 30/0.1 + константа; итог —
  исходный TimeoutExpired, часы не дальше дедлайна;
- контроль fix2 остаётся зелёным: `rm` rc=1, следующий `ps` пуст → возврат без
  `sleep`.
Существующие тесты fix/fix2 сохранить.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением BASE: `continue` после
`removed.returncode != 0` (~строка 84) стоит до блока `remaining`/`sleep` в
конце итерации. Предположение: frozen probe `tests/probe_m13_late_container.py`
не требует отсутствия пауз после неуспешного `rm`; если краснеет — blocker с
тестом и строкой assertion.

## Разрешения

Правка `bench/runner/execute.py` (только `DockerLauncher._cleanup`),
`tests/test_execute.py`. Commit в клоне.

## Не трогать

Probe `tests/probe_m13_late_container.py`, frozen probes M9–M12, gateway/**,
остальной bench/**, deploy/**, scripts/**, остальные tests, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m13b-fix3.md`).

## Критерии приёмки

- **AC-951.** Probe M13 зелёный и неизменный:
  `bash -c 'test "$(sha256sum tests/probe_m13_late_container.py | cut -d" " -f1)" = 68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m13_late_container'`
- **AC-952.** Frozen probes M9–M12 неизменны и зелёные:
  `bash -c 'git diff --exit-code 498c4d3c230495bdbb99fb5358f3d985ea55a35e HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-953.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-954.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 498c4d3c230495bdbb99fb5358f3d985ea55a35e HEAD -- . ":(exclude)bench/runner/execute.py" ":(exclude)tests/test_execute.py" ":(exclude)docs/specs/m13b-fix3.md"'`
- **AC-955.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13b-fix3.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 498c4d3c230495bdbb99fb5358f3d985ea55a35e --range 498c4d3c230495bdbb99fb5358f3d985ea55a35e..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-951…AC-955,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"498c4d3c230495bdbb99fb5358f3d985ea55a35e","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-951","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13b-fix3-20260917 --spec /home/user/exec-clones/abg-m13b-fix3-20260917/docs/specs/m13b-fix3.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если probe M13 нельзя сделать
зелёным правкой только `bench/runner/execute.py`, если правка ломает frozen
probe M9–M12, или если probe требует поведения, противоречащего контракту выше
(записать тест и строку assertion). Probe, спеку, AC, BASE и оснастку не
менять, rc не выдумывать.
