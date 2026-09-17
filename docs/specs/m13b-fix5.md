# M13b-fix5 — тесты на выжившие мутанты уборки контейнеров

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `9c23c1769c8565a42492bccb4c975004753d2ee6` — FINAL M13b-fix4.
Клон /home/user/exec-clones/abg-m13b-fix5-20260917, ветка m13b-fix5, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Импорт и assertions — только Docker 1002:1002 с
`--network none`; host — git/файлы/оркестрация. Реальный Docker daemon тестами
не трогать.

## Задача

Независимый мутационный прогон по FINAL M13b-fix4
(`/home/user/.cache/abg-coord-20260917/m13b-mutations2/result.md`, diffs в
`diffs/`) оставил двух выживших у `tests.test_execute.DockerLauncherTests`:

- **M03** — к командам, отличным от `docker run`, добавляется
  `--label abg.launch=…`. Ловит только frozen probe; авторский набор не
  вызывает не-`docker run`.
- **M28** — после сна в конце итерации `pause_before_removal` не
  сбрасывается. Сценарий: `rm` rc=1 → `ps` rc≠0 → сон в конце итерации →
  успешный `ps` с ID → лишний второй сон перед `rm`. Тест
  `test_failed_empty_listing_does_not_prove_seen_container_was_removed`
  проходит на обоих.

Только тесты, код НЕ менять. В `DockerLauncherTests` (`tests/test_execute.py`,
фейковые часы/sleep/subprocess, как в соседних тестах):
1. Не-`docker run` команды (например `docker ps`, `docker image inspect`,
   `python3 -c …`) передаются в `subprocess.run` ровно тем же argv, без
   `--cidfile`/`--label`, и при таймауте не запускают уборку.
2. Точная последовательность вызовов и снов для сценария M28: между
   неуспешным `ps` и следующим `rm` ровно один сон (в конце итерации), после
   успешного `ps` перед `rm` снов нет. Проверять полный список событий
   (`sleep`/команды в порядке), а не только их число.

Обязательная проверка причины: применить diff M03 и M28 по отдельности к
копиям дерева вне клона и показать, что каждый новый тест падает на своём
мутанте на assertion из пункта 1/2 и зелёный на BASE; вывод — в note AC-993.
Существующие тесты не менять.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением diffs M03/M28 и
`DockerLauncher.run/_cleanup` на 9c23c17. Live-запросы и Docker daemon не нужны.

## Разрешения

Правка только `tests/test_execute.py`. Копии дерева для мутантов — во
временном каталоге вне клона. Commit в клоне.

## Не трогать

`bench/**` (включая execute.py), `tests/probe_m13_late_container.py` и прочие
probes, gateway/**, deploy/**, scripts/**, остальные tests, docs, другие
specs, TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту
спеку byte-identical (`docs/specs/m13b-fix5.md`).

## Критерии приёмки

- **AC-991.** Probe M13 зелёный и неизменный:
  `bash -c 'test "$(sha256sum tests/probe_m13_late_container.py | cut -d" " -f1)" = 68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m13_late_container'`
- **AC-992.** Frozen probes M9–M12 неизменны и зелёные:
  `bash -c 'git diff --exit-code 9c23c1769c8565a42492bccb4c975004753d2ee6 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-993.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-994.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 9c23c1769c8565a42492bccb4c975004753d2ee6 HEAD -- . ":(exclude)tests/test_execute.py" ":(exclude)docs/specs/m13b-fix5.md"'`
- **AC-995.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13b-fix5.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 9c23c1769c8565a42492bccb4c975004753d2ee6 --range 9c23c1769c8565a42492bccb4c975004753d2ee6..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-991…AC-995,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"9c23c1769c8565a42492bccb4c975004753d2ee6","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-991","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13b-fix5-20260917 --spec /home/user/exec-clones/abg-m13b-fix5-20260917/docs/specs/m13b-fix5.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если новый тест не проходит на
BASE, не падает на своём мутанте (M03 или M28) по заявленной причине, или
закрыть дыру можно только правкой кода. Код, probe, спеку, AC, BASE и
оснастку не менять, rc не выдумывать.
