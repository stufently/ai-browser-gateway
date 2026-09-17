# M13a-fix5 — тест на смешанный регистр пассивного JSD-пути

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `5b604c943a4ef087e24cb9958949ea4f37512a18` — FINAL M13a-fix4.
Клон /home/user/exec-clones/abg-m13a-fix5-20260917, ветка m13a-fix5, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002; host — git/файлы/оркестрация.

## Задача

Независимый мутационный прогон по FINAL M13a-fix4
(`/home/user/.cache/abg-coord-20260917/m13a-mutations3/result.md`, мутант
M25) выжил: в `_scrapling_only_jsd_platform_paths` убран `.lower()` —
авторские тесты зелёные. Контрпример: HTTP 200, `cf-mitigated: challenge`,
тело `<script src="/cdn-cgi/challenge-platform/SCRIPTS/JSD/main.js"></script>`
— на FINAL заголовок удалён и `challenge=none`, у мутанта заголовок сохранён и
`suspected`. Спецификация fix3/fix4 требует сравнения без учёта регистра.

Только тест, код НЕ менять. В `tests/test_probe.py`
(`ScraplingAdapterTests`, через `run_probe`) добавить случаи смешанного
регистра, где префикс `/cdn-cgi/challenge-platform` в нижнем регистре, а
продолжение — нет (`/SCRIPTS/JSD/`, `/Scripts/Jsd/`), в str и bytes: заголовок
удалён, `none`. Обязательная проверка причины: применить мутацию M25 к копии
дерева (не к клону) и показать, что новый тест падает именно на assertion
заголовка; результат — в note AC-983. Существующие тесты не менять.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 по diff M25 и чтению helper: на FINAL оба
условия (`_scrapling_only_jsd_platform_paths` и
`_scrapling_has_challenge_strings`) приводят тело к нижнему регистру.
Live-запросы в этой вехе не нужны.

## Разрешения

Правка только `tests/test_probe.py`. Копия дерева для проверки мутанта — во
временном каталоге вне клона. Commit в клоне.

## Не трогать

`bench/**` (включая probe.py), gateway/**, deploy/**, scripts/**, остальные
tests и frozen probes, docs/research, другие specs, TASKS/CHANGELOG,
`/home/user/services/**`. Сначала закоммитить эту спеку byte-identical
(`docs/specs/m13a-fix5.md`).

## Критерии приёмки

- **AC-981.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-982.** Frozen probes и детектор зелёные и неизменны:
  `bash -c 'git diff --exit-code 5b604c943a4ef087e24cb9958949ea4f37512a18 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-983.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-984.** Код продукта не изменён:
  `bash -c 'git diff --exit-code 5b604c943a4ef087e24cb9958949ea4f37512a18 HEAD -- bench gateway'`
- **AC-985.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 5b604c943a4ef087e24cb9958949ea4f37512a18 HEAD -- . ":(exclude)tests/test_probe.py" ":(exclude)docs/specs/m13a-fix5.md"'`
- **AC-986.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-fix5.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 5b604c943a4ef087e24cb9958949ea4f37512a18 --range 5b604c943a4ef087e24cb9958949ea4f37512a18..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-981…AC-986,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"5b604c943a4ef087e24cb9958949ea4f37512a18","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-981","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-fix5-20260917 --spec /home/user/exec-clones/abg-m13a-fix5-20260917/docs/specs/m13a-fix5.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: новый тест не
проходит на BASE или не падает на мутанте M25; нужна
правка `detect_challenge`, policy продукта, гейта или frozen probes. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
