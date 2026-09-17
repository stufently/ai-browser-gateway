# M13c-fix — тест на заголовок Authorization в запросах worker к API

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `123bffe9f505e77bcf9c534c98cd4716eb8bebe5` — FINAL M13c (выкладка принята, сервис работает).
Клон /home/user/exec-clones/abg-m13c-fix-20260917, ветка m13c-fix, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай все до конца кодексом»).

Сервис `ai-browser-gateway` (127.0.0.1:8765), `/home/user/services/**` и
`/home/user/.cache/abg-coord-20260917/m13c/` НЕ трогать; deployed-проверки
(`tests/deployed_m12b.py` вне unittest) НЕ запускать. Push/merge запрещены.
Импорт и assertions — только Docker 1002:1002 с `--network none`; host —
git/файлы/оркестрация.

## Задача

Независимый мутационный прогон по FINAL M13c
(`/home/user/.cache/abg-coord-20260917/m13c-mutations/result.md`, мутант
M37, diff `mutants/M37/mutation.diff`) выжил: в `worker()` для действия
`bizprofile` не добавляется `Authorization: Bearer <token>` — 47 тестов
`tests.test_deployed_m12b` проходят. Заглушка `fake_http` в
`tests/test_deployed_m12b.py` проверяет адрес и тело, но не заголовки.

Только тесты, runner НЕ менять. В `tests/test_deployed_m12b.py`:
1. Для запросов worker к `/v1/fetch` в действиях `bizprofile` и `api`
   проверять, что `Authorization` ровно `Bearer <токен из /run/token без
   пробелов по краям>`, а в `health` заголовка нет, в `unauthorized` —
   тоже нет (иначе проверка 401 бессмысленна). Удобно — в существующих
   заглушках HTTP (`fake_http` и аналог для `api`, если есть), через
   `request.get_header('Authorization')`.
2. Токен по-прежнему не должен попадать в вывод worker (существующая
   проверка сохраняется).

Обязательная проверка причины: применить diff M37 к копии дерева вне клона и
показать, что новый/изменённый тест падает на assertion заголовка и зелёный
на BASE; также симметричный мутант «Authorization не добавляется для `api`»
(в копии) — падает. Вывод — в note AC-883. Существующие assertions не
ослаблять.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением `worker()` и `fake_http` на
123bffe. Live-запросы не нужны.

## Разрешения

Правка только `tests/test_deployed_m12b.py`. Копии дерева для мутантов — во
временном каталоге вне клона. Commit в клоне.

## Не трогать

`tests/deployed_m12b.py`, остальные tests и probes, bench/**, gateway/**,
deploy/**, scripts/**, docs, другие specs, TASKS/CHANGELOG,
`/home/user/services/**`. Сначала закоммитить эту спеку byte-identical
(`docs/specs/m13c-fix.md`).

## Критерии приёмки

- **AC-881.** Авторский набор runner зелёный:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_deployed_m12b'`
- **AC-882.** Runner и прочий код не изменены:
  `bash -c 'git diff --exit-code 123bffe9f505e77bcf9c534c98cd4716eb8bebe5 HEAD -- tests/deployed_m12b.py bench gateway scripts deploy'`
- **AC-883.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-884.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 123bffe9f505e77bcf9c534c98cd4716eb8bebe5 HEAD -- . ":(exclude)tests/test_deployed_m12b.py" ":(exclude)docs/specs/m13c-fix.md"'`
- **AC-885.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13c-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 123bffe9f505e77bcf9c534c98cd4716eb8bebe5 --range 123bffe9f505e77bcf9c534c98cd4716eb8bebe5..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-881…AC-885,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"123bffe9f505e77bcf9c534c98cd4716eb8bebe5","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-881","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13c-fix-20260917 --spec /home/user/exec-clones/abg-m13c-fix-20260917/docs/specs/m13c-fix.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если новый тест не проходит на
BASE, не падает на мутанте M37 по заявленной причине, или закрыть дыру можно
только правкой runner. Runner, спеку, AC, BASE и оснастку не менять, rc не
выдумывать.
