# M13a-fix2 — одиночный CF-маркер в теле сохраняет cf-mitigated

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `c32da3c0806b9e969fe66ff24ee2e221cf38faf2` — FINAL M13a-fix.
Клон /home/user/exec-clones/abg-m13a-fix2-20260917, ветка m13a-fix2, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»). M13a и M13a-fix писали другие cx-панели.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002; host — git/файлы/оркестрация. Провайдерские образы не пересобирать.

## Задача

Codex result review M13a-fix нашёл, координатор подтвердил чтением
`detect_challenge`: одиночный решающий CF-маркер тела (например `cf_chl_opt`,
`__cf_chl`, `challenges.cloudflare.com`) без заголовка даёт вердикт `none`
(нужно два маркера или title «just a moment»). Поэтому HTTP 200 +
`cf-mitigated: challenge` + тело проверки браузера с одним `_cf_chl_opt`
теряет заголовок, получает `challenge=none`, и `accept_page` принимает
страницу без `expected_text` (до M13a — `challenge_suspected`).

Требование: в `ScraplingAdapter.navigate` заголовок `cf-mitigated` удаляется
ТОЛЬКО если вердикт `detect_challenge(status, None, body)` — `none` И каждое
имя сработавшего правила входит в множество
{`body_cf_challenge_platform`, `body_noindex_nofollow`} (пустое множество
имён — тоже удаление). Живая страница bizprofile даёт ровно
`body_cf_challenge_platform` (скрипт `/cdn-cgi/challenge-platform/scripts/jsd/main.js`
стоит на обычных страницах за Cloudflare). Любое другое имя
(`body_cf_chl_opt`, `body_cf_chl`, `body_cf_challenges_host`, `body_captcha`,
…) — заголовок сохраняется, вердикт как до M13a. Прочие условия (2xx, `None`/`{}`
различаются, исходный словарь ответа не мутируется) не меняются.
Допустимые имена записать одной константой рядом с адаптером.
`detect_challenge` и `tests/test_detect.py` НЕ менять.

Тесты в `tests/test_probe.py` (`ScraplingAdapterTests`, через `run_probe`):
для КАЖДОГО из `cf_chl_opt`, `__cf_chl`, `challenges.cloudflare.com` —
200 + `cf-mitigated: challenge` + тело с одним этим маркером → заголовок
сохранён, challenge `suspected`, маркер тела и `header_cf_mitigated` в
маркерах; контроль: тело только с `/cdn-cgi/challenge-platform` (и вариант с
добавленным `noindex,nofollow`, если он не превращает вердикт в suspected) →
заголовок удалён, challenge `none`. Тесты должны падать на BASE по причине
одиночного маркера. Существующие captcha-тесты сохранить.
`tests/mutation_gate_scrapling.py` не менять, он должен остаться зелёным.

Документ `docs/research/08-bizprofile-scrapling.md` — уточнить абзац про
условие удаления (одна-две фразы).

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением BASE: `_BODY_RULES` (probe.py
~261–267), `body_enough = just_a_moment or len(decisive_body) >= 2`, вердикт
`none` возвращает имена сработавших правил. Живой прогон M13a/M13a-fix дал у
bizprofile маркеры только `body_cf_challenge_platform`. Предположение: так
остаётся и сейчас; если live покажет другой маркер — это blocker с именами
правил, не расширение множества.

## Разрешения

Правка `bench/providers/docker/probe.py` (только условие в
`ScraplingAdapter.navigate` и константа рядом), `tests/test_probe.py`,
`docs/research/08-bizprofile-scrapling.md`. Live-запросы к bizprofile.net: не
больше 6 за прогон, пауза ≥30 с. Commit в клоне.

## Не трогать

`detect_challenge` и его правила, gateway/**, остальной bench/**, deploy/**,
scripts/**, остальные tests (включая `tests/mutation_gate_scrapling.py`) и
frozen probes, другие specs, TASKS/CHANGELOG, `/home/user/services/**`.
Сначала закоммитить эту спеку byte-identical (`docs/specs/m13a-fix2.md`).

## Критерии приёмки

- **AC-921.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-922.** Frozen probes и детектор зелёные и неизменны:
  `bash -c 'git diff --exit-code c32da3c0806b9e969fe66ff24ee2e221cf38faf2 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-923.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-924.** Live bizprofile без expected_text:
  `bash -c 'python3 tests/live_m13a_bizprofile.py'`
- **AC-925.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code c32da3c0806b9e969fe66ff24ee2e221cf38faf2 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)docs/specs/m13a-fix2.md"'`
- **AC-926.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-fix2.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base c32da3c0806b9e969fe66ff24ee2e221cf38faf2 --range c32da3c0806b9e969fe66ff24ee2e221cf38faf2..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-921…AC-926,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"c32da3c0806b9e969fe66ff24ee2e221cf38faf2","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-921","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-fix2-20260917 --spec /home/user/exec-clones/abg-m13a-fix2-20260917/docs/specs/m13a-fix2.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: live bizprofile после
правки не проходит (класс отказа и имена правил детектора без тела); нужна
правка `detect_challenge`, policy продукта, гейта или frozen probes. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
