# M13b-fix — уборка контейнера, созданного демоном после таймаута клиента

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `5a508e4ec116066ab439b8b9c80aa001692d4412` (main: M12, M13b probe влит).
Клон /home/user/exec-clones/abg-m13b-fix-20260917, ветка m13b-fix, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца», выбрана уборка поздних
контейнеров). Probe писала другая cx-панель.

Сервис `ai-browser-gateway` и `/home/user/services/**` НЕ трогать; реальный
Docker-сокет в тестовые контейнеры не монтировать. Push/merge запрещены. Импорт и
assertions — только Docker 1002:1002, `--network none`; host — git/файлы.

## Задача

`bench/runner/execute.py:DockerLauncher.run` запускает `docker run --cidfile
<tmp> …` через `subprocess.run(timeout=…)`. При `TimeoutExpired` контейнер
убирается ТОЛЬКО если cidfile уже есть и не пуст. Если клиент убит до записи
cidfile (медленный create, занятый демон), демон создаёт и запускает контейнер
ПОСЛЕ возврата `run` (Moby 29.8.0 `daemon/create.go` не отменяет create при
обрыве клиента), и его никто не убирает.

Контракт (проверяет frozen `tests/probe_m13_late_container.py`, SHA256
`68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402`, 6 тестов; на BASE 2 assertion failures «late container survived
launcher return», 4 green):
- после `TimeoutExpired` у `docker run` `run` не возвращается, пока
  контейнер ЭТОГО вызова не убран или не истёк ограниченный горизонт порядка
  существующего лимита уборки 30 с; затем поднимает ТОТ ЖЕ `TimeoutExpired`;
- идентичность вызова — уникальная на каждый вызов, launcher сам добавляет её в
  argv `docker run`; поиск и удаление только по ней (два вызова с одинаковыми
  метками `abg.request` и чужие контейнеры не трогать);
- cidfile успел записаться — удаляется этот контейнер, как сейчас;
- ошибки уборки (OSError/SubprocessError, ненулевой rc) не меняют исходное
  исключение; бесконечного ожидания нет;
- нормальный путь (rc 0/ненулевой, не-`docker run` команды), проброс
  env/timeout/argv провайдера, stdin=DEVNULL, без shell, возвращаемый кортеж —
  без изменений.

Тесты в `tests/test_execute.py` (фейковый `subprocess.run`, без sleep как
синхронизации): уникальность идентичности между двумя вызовами; поздний
контейнер найден и удалён по точной идентичности; ошибка/исключение при уборке
сохраняет `TimeoutExpired`; горизонт ограничен (фейковые часы или
`time.monotonic` через patch); cidfile-путь. Падать ПО ПРИЧИНЕ (assert на argv
вызовов docker), не на побочном эффекте.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: тело `DockerLauncher.run` на BASE (cidfile-
only уборка), `LabeledLauncher.run` (`gateway/service.py:73-91`, метки
owner/instance/role/request одинаковы для всех попыток запроса), probe на BASE —
6 тестов, 2 failures; на двух независимых эталонах координатора probe + frozen
M9/M12 + полный unittest green (620 тестов). Docker 29.8.0: `docker ps --all
--quiet --filter label=k=v`, `--filter name=`, `docker rm --force`.
Предположение: 30 с горизонта не ломают бюджеты M12 shutdown — это проверят
frozen probes M12 в AC-922.

## Разрешения

Правка `bench/runner/execute.py` (только `DockerLauncher` и helper рядом),
`tests/test_execute.py`. Commit в клоне.

## Не трогать

`tests/probe_m13_late_container.py` и все frozen probes, gateway/**, остальной
bench/**, deploy/**, scripts/**, остальные tests, specs, TASKS/CHANGELOG,
`/home/user/services/**`. Сначала закоммитить эту спеку byte-identical
(`docs/specs/m13b-fix.md`).

## Критерии приёмки

- **AC-921.** Probe M13 зелёный и неизменный:
  `bash -c 'test "$(sha256sum tests/probe_m13_late_container.py | cut -d" " -f1)" = 68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m13_late_container'`
- **AC-922.** Frozen probes M9–M12 неизменны и зелёные:
  `bash -c 'git diff --exit-code 5a508e4ec116066ab439b8b9c80aa001692d4412 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-923.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-924.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 5a508e4ec116066ab439b8b9c80aa001692d4412 HEAD -- . ":(exclude)bench/runner/execute.py" ":(exclude)tests/test_execute.py" ":(exclude)docs/specs/m13b-fix.md"'`
- **AC-925.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13b-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 5a508e4ec116066ab439b8b9c80aa001692d4412 --range 5a508e4ec116066ab439b8b9c80aa001692d4412..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-921…AC-925,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"5a508e4ec116066ab439b8b9c80aa001692d4412","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-921","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13b-fix-20260917 --spec /home/user/exec-clones/abg-m13b-fix-20260917/docs/specs/m13b-fix.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если probe M13 нельзя сделать
зелёным правкой только `bench/runner/execute.py`, если правка ломает frozen
probe M9–M12, или если probe требует поведения, противоречащего контракту выше
(записать тест и строку assertion). Probe, спеку, AC, BASE и оснастку не
менять, rc не выдумывать.
