# M13a-fix — captcha в теле сохраняет cf-mitigated; mutation gate M8

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2` — FINAL M13a.
Клон /home/user/exec-clones/abg-m13a-fix-20260917, ветка m13a-fix, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»). M13a писала другая cx-панель.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002; host — git/файлы/оркестрация. Провайдерские образы не пересобирать.

## Задача

Codex result review M13a нашёл, координатор подтвердил чтением кода:

1. **Captcha-страница становится чистой.** `ScraplingAdapter.navigate` удаляет
   `cf-mitigated`, если `detect_challenge(status, None, body)` не
   `suspected`/`interactive`. Но без заголовка виджет captcha в теле
   (`_CAPTCHA_ATTR`, правило `body_captcha`) при 2xx не подтверждён
   (`captcha_confirmed` опирается на заголовок) → вердикт `none`. Итог: HTTP
   200 + `cf-mitigated: challenge` + `<input name="captcha">` даёт
   `challenge=none`, и `accept_page` принимает страницу без `expected_text`.
   Требование: заголовок удаляется ТОЛЬКО если вердикт тела без заголовков
   `none` И среди имён сработавших правил нет `body_captcha`. Любой другой
   случай — заголовок сохраняется, вердикт как до M13a. Прочие условия M13a
   (2xx, `None`/`{}` различаются, исходный словарь ответа не мутируется) не
   меняются. `detect_challenge` и `tests/test_detect.py` НЕ менять.
2. **Сломан mutation gate M8.** `tests/mutation_gate_scrapling.py` мутант 3
   (`headers = None`) ссылается на удалённый в M13a
   `test_scrapling_passes_response_headers`; гейт падает на чистом коде.
   Перенаправить мутант 3 на существующий тест, который его убивает ПО ПРИЧИНЕ
   (строка assertion про headers), обновив `test` и `assert`. Остальные
   мутанты гейта не менять.

Тесты в `tests/test_probe.py` (`ScraplingAdapterTests`, через `run_probe`,
как в M13a): 200 + `cf-mitigated: challenge` + тело с captcha-атрибутом
(src/class/id/name) и без решающих CF-маркеров → заголовок сохранён, challenge
`suspected`, `body_captcha` и `header_cf_mitigated` в маркерах; тот же
статус с чистым телом → заголовок по-прежнему удаляется (контроль). Тест должен
падать на BASE по причине captcha.

Документ `docs/research/08-bizprofile-scrapling.md` — одна-две фразы про
исключение captcha.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением BASE: `detect_challenge` (probe.py
296–352: `captcha_confirmed = bool(header_names or decisive_body or status in
(403, 429))`, header_verdict возвращается первым), `_CAPTCHA_ATTR` (274–277),
гейт `tests/mutation_gate_scrapling.py:45-50`. Живой прогон M13a дал у
bizprofile маркеры только `body_cf_challenge_platform` — предположение: captcha-
атрибута в реальных страницах нет, live останется зелёным; если нет — это
blocker, не ослабление.

## Разрешения

Правка `bench/providers/docker/probe.py` (только условие в
`ScraplingAdapter.navigate`), `tests/test_probe.py`,
`tests/mutation_gate_scrapling.py` (только мутант 3),
`docs/research/08-bizprofile-scrapling.md`. Live-запросы к bizprofile.net: не
больше 6 за прогон, пауза ≥30 с. Commit в клоне.

## Не трогать

`detect_challenge` и его правила, gateway/**, остальной bench/**, deploy/**,
scripts/**, остальные tests и frozen probes, другие specs, TASKS/CHANGELOG,
`/home/user/services/**`. Сначала закоммитить эту спеку byte-identical
(`docs/specs/m13a-fix.md`).

## Критерии приёмки

- **AC-911.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-912.** Frozen probes и детектор зелёные и неизменны:
  `bash -c 'git diff --exit-code c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-913.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-914.** Live bizprofile без expected_text:
  `bash -c 'python3 tests/live_m13a_bizprofile.py'`
- **AC-915.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)tests/mutation_gate_scrapling.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)docs/specs/m13a-fix.md"'`
- **AC-916.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2 --range c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-911…AC-916,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"c0a6f17009d47b4f9bd452b3e7e5e1fa94312de2","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-911","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-fix-20260917 --spec /home/user/exec-clones/abg-m13a-fix-20260917/docs/specs/m13a-fix.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: live bizprofile после
правки не проходит (класс отказа и имена правил детектора без тела); нужна
правка `detect_challenge`, policy продукта или frozen probes; мутант 3 гейта
нельзя убить существующим тестом по причине headers. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
