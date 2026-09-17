# M12b-fix — строгий и только читающий deployed-runner

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `25dfa5ce79a53257bc6853f6eaef2a2ae7ac4643` — FINAL M12b.
Клон /home/user/exec-clones/abg-m12b-fix-20260917, ветка m12b-fix, origin
push DISABLED. Исполнитель — cx (директива владельца 17.09.2026: «доделывай
всё, используя кодекс»). Runner писала другая cx-панель; мутации гоняла третья.

Сервис `ai-browser-gateway` на 127.0.0.1:8765 уже работает из release
`929bded313e371808b0747fd9a400696a36638aa`; его НЕ перезапускать, НЕ
останавливать, файлы `/home/user/services/ai-browser-gateway/**` НЕ менять.
Разрешён только запуск режимов runner, перечисленных в AC. Push/merge
запрещены. Исполнение кода — Docker 1002:1002 (кроме хостовых git/файлов и
оркестрации, как уже делает runner). Секреты не печатать и не читать глазами.

## Задача

Приёмка M12b (координатор, Codex result review, независимые мутации 28 → 23
kill / 5 survivor) нашла в `tests/deployed_m12b.py`, его тестах и README:

1. **check_deploy пишет в production.** Он вызывает `scripts/abg-release
   prepare`, который при существующем release делает `chmod` каталога
   `manifests`, а при отсутствии release/manifest создал бы их и скрыл дефект
   выкладки. Заменить на проверку только чтением: `releases/<SHA>` существует,
   не symlink, в дереве нет symlink; `manifests/<SHA>.sha256` — обычный файл,
   не symlink; множество файлов release равно множеству строк manifest, SHA256
   каждого совпадает; обычные файлы 0644, исполняемые 0755, каталоги 0755.
   Никаких записей, chmod и вызова `abg-release`.
2. **parse_api слишком терпим.** Сейчас пропускает неизвестные `error_type`,
   `challenge`, `next_step`, `step`, любые int-статусы и любой тип
   `age_hours`. Требуется строгая схема: верхний `ok` bool, `content` str,
   `elapsed_ms` int ≥ 0, `error_type` ∈ значения `bench.models.FailureReason`,
   `step` ∈ `bench.escalate.Step`, `provider` None или str; в attempts
   `status` None или int 100..599, `error_type` ∈ FailureReason, `challenge` ∈
   `bench.models.ChallengeType`, `next_step` ∈ Step, `age_hours` None или
   конечное число ≥ 0, `elapsed_ms` int ≥ 0, `success` bool, `egress_profile` ∈
   direct/ms1..ms15. Runner монтируется в контейнер ОДНИМ файлом, поэтому
   допустимые значения записать в runner константами, а в
   `tests/test_deployed_m12b.py` добавить тест, что они равны значениям
   перечислений из `bench`.
3. **Выжившие мутанты (дыры тестов).** Добавить тесты, падающие ПО ПРИЧИНЕ:
   - M07: не-200 с ПОЛНОСТЬЮ валидным телом отвергается (код `api_http_error`);
   - M09: валидное тело с `ok` не bool отвергается;
   - M10: attempt с отрицательным `elapsed_ms` при остальной валидной схеме
     отвергается;
   - M11: `provider_error`/`environment_error` ТОЛЬКО в attempts (верх —
     обычный) даёт `api_provider_infrastructure_error`;
   - M21: две egress-попытки в ответе — `egress_not_proven`.
   Проверять код CheckError (`assertRaisesRegex` на точный код), а не только
   класс исключения. Плюс тесты на каждое новое правило п.2 и на read-only
   проверку release п.1 (симлинк, лишний файл, неверный hash, неверный режим,
   отсутствующий manifest — отказ; ни одного вызова записи).
4. **README откат.** Экспортированные ранее `ABG_RELEASE`/`ABG_RUNTIME_IMAGE`
   перекрывают `compose.env`. В разделе «M12b deployed service» команды
   up/stop/откат запускать через `env -u ABG_RELEASE -u ABG_RUNTIME_IMAGE …`
   (или явно оговорить `unset` перед ними).

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: все 8 AC M12b перезапущены (machine_pass);
healthchecks — автоматические success каждые 60 с, fail/recovery при остановке
api; тело `abg-release prepare` на `929bded` (строки manifest(): `mkdir` +
`os.chmod(folder, 0o755)`); перечисления — `bench/models.py`
(`FailureReason`, `ChallengeType`), `bench/escalate.py` (`Step`). Патчи
выживших мутантов — `/home/user/.cache/abg-coord-20260917/m12b-mutations/mutants/M{07,09,10,11,21}/mutation.diff`
(для понимания; после правки п.2 они не применятся). Предположение: реальные
ответы deployed API уже удовлетворяют строгой схеме — AC-704/705 это проверят.

## Разрешения

Правка `tests/deployed_m12b.py`, `tests/test_deployed_m12b.py`, `README.md`,
при необходимости `docs/research/07-deployed-service.md` (только описание
метода). Запуск режимов runner из AC (внешние запросы с тем же ≥30 с на
hostname). Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, остальные tests и frozen probes,
контракт, другие specs, TASKS.md, CHANGELOG.md, `/home/user/services/**`,
healthchecks. Сначала закоммитить эту спеку byte-identical
(`docs/specs/m12b-fix.md`).

## Критерии приёмки

- **AC-701.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-702.** check_deploy проходит и не меняет дерево сервиса (путь, режим, mtime, ctime, размер):
  `bash -c 'snap(){ find /home/user/services/ai-browser-gateway/releases /home/user/services/ai-browser-gateway/manifests -printf "%p %m %T@ %C@ %s\n" | sort | sha256sum; }; a=$(snap) && python3 tests/deployed_m12b.py --check-deploy && b=$(snap) && test "$a" = "$b"'`
- **AC-703.** В runner нет вызова abg-release и записи в каталог сервиса:
  `bash -c '! grep -nE "abg-release|chmod|mkdir|write_text|write_bytes" tests/deployed_m12b.py | grep -v "EVIDENCE\|folder\|save(" | grep -q .'`
- **AC-704.** Egress и ротация через API со строгой схемой:
  `bash -c 'python3 tests/deployed_m12b.py --check-api-egress'`
- **AC-705.** Шесть целей и CLI со строгой схемой:
  `bash -c 'python3 tests/deployed_m12b.py --run-targets'`
- **AC-706.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 25dfa5ce79a53257bc6853f6eaef2a2ae7ac4643 HEAD -- . ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)README.md" ":(exclude)docs/research/07-deployed-service.md" ":(exclude)docs/specs/m12b-fix.md"'`
- **AC-707.** Чистое дерево, спека в git, откат в README без перекрытия:
  `bash -c 'git ls-files --error-unmatch docs/specs/m12b-fix.md >/dev/null && grep -q "ABG_RUNTIME_IMAGE" README.md && grep -qE "env -u ABG_RELEASE|unset ABG_RELEASE" README.md && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 25dfa5ce79a53257bc6853f6eaef2a2ae7ac4643 --range 25dfa5ce79a53257bc6853f6eaef2a2ae7ac4643..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-701…AC-707,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"25dfa5ce79a53257bc6853f6eaef2a2ae7ac4643","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-701","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m12b-fix-20260917 --spec /home/user/exec-clones/abg-m12b-fix-20260917/docs/specs/m12b-fix.md --timeout 2400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
реальный ответ deployed API не проходит строгую схему (это дефект сервиса или
схемы — записать поле и значение без содержимого страниц, не ослаблять схему);
проверку release нельзя сделать без записи; нужен рестарт сервиса или правка
вне разрешённого. Спеку, AC, BASE и оснастку не менять, rc не выдумывать.
