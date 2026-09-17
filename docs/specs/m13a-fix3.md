# M13a-fix3 — challenge-platform доверяется только как пассивный скрипт jsd

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `375bdbfe0231cd2f68b36ce2654c9239a966bb42` — FINAL M13a-fix2.
Клон /home/user/exec-clones/abg-m13a-fix3-20260917, ветка m13a-fix3, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»; выбор владельца 17.09 —
«сузить + принять остаток»). M13a, fix и fix2 писали другие cx-панели.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002; host — git/файлы/оркестрация. Провайдерские образы не пересобирать.

## Задача

Codex result review M13a-fix2 нашёл, координатор подтвердил чтением
`_BODY_RULES`: правило `body_cf_challenge_platform` срабатывает на ЛЮБУЮ
подстроку `/cdn-cgi/challenge-platform`, в том числе на скрипт самой страницы
проверки (`/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1`). Поэтому
200 + `cf-mitigated: challenge` + страница «Checking your browser» с одним
этим маркером теряет заголовок и получает `challenge=none`.

Требование: в `ScraplingAdapter.navigate` к условиям fix2 (2xx, headers не
`None`, есть `cf-mitigated`, вердикт тела без заголовков `none`, имена правил
⊆ {`body_cf_challenge_platform`, `body_noindex_nofollow`}) добавить: если
среди имён есть `body_cf_challenge_platform`, то КАЖДОЕ вхождение
`/cdn-cgi/challenge-platform` в теле (без учёта регистра, тело декодируется
так же, как в `detect_challenge`) продолжается ровно `/scripts/jsd/`. Иначе
заголовок сохраняется, вердикт как до M13a. Проверку сделать маленьким
helper'ом рядом с адаптером; `detect_challenge`, `_BODY_RULES` и
`tests/test_detect.py` НЕ менять.

Остаточный риск, принятый владельцем 17.09.2026: тело без каких-либо
CF-маркеров (пустой набор правил), например самописная форма captcha без
атрибутов `_CAPTCHA_ATTR`, при 2xx + устаревшем `cf-mitigated` по-прежнему
теряет заголовок. Его НЕ закрывать; записать одним абзацем в
`docs/research/08-bizprofile-scrapling.md` (сценарий, почему эвристикой тела
не закрывается, что живой Cloudflare-челлендж всегда несёт CF-маркеры).

Тесты в `tests/test_probe.py` (`ScraplingAdapterTests`, через `run_probe`),
падающие на BASE по причине:
- 200 + `cf-mitigated` + тело только с
  `<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=x">`
  (и вариант с заглавными буквами в пути) → заголовок сохранён, `suspected`,
  `header_cf_mitigated` и `body_cf_challenge_platform` в маркерах;
- тело с ДВУМЯ вхождениями: jsd и orchestrate → заголовок сохранён;
- контроль: только `/cdn-cgi/challenge-platform/scripts/jsd/main.js` (и тот же
  с `noindex,nofollow`) → заголовок удалён, `none`.
Существующие тесты fix/fix2 сохранить.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: спека M13a фиксирует у живой карточки
bizprofile скрипт `/cdn-cgi/challenge-platform/scripts/jsd/main.js`; live
M13a/fix/fix2 дал маркеры только `body_cf_challenge_platform`. Предположение:
у главной и карточки нет других путей под `/cdn-cgi/challenge-platform`; если
live покажет иное — blocker с именами правил и путём после префикса (без
тела), не расширение условия.

## Разрешения

Правка `bench/providers/docker/probe.py` (только условие в
`ScraplingAdapter.navigate` и helper рядом), `tests/test_probe.py`,
`docs/research/08-bizprofile-scrapling.md`. Live-запросы к bizprofile.net: не
больше 6 за прогон, пауза ≥30 с. Commit в клоне.

## Не трогать

`detect_challenge` и его правила, gateway/**, остальной bench/**, deploy/**,
scripts/**, остальные tests (включая `tests/mutation_gate_scrapling.py`) и
frozen probes, другие specs, TASKS/CHANGELOG, `/home/user/services/**`.
Сначала закоммитить эту спеку byte-identical (`docs/specs/m13a-fix3.md`).

## Критерии приёмки

- **AC-941.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-942.** Frozen probes и детектор зелёные и неизменны:
  `bash -c 'git diff --exit-code 375bdbfe0231cd2f68b36ce2654c9239a966bb42 HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-943.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-944.** Live bizprofile без expected_text:
  `bash -c 'python3 tests/live_m13a_bizprofile.py'`
- **AC-945.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 375bdbfe0231cd2f68b36ce2654c9239a966bb42 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)docs/specs/m13a-fix3.md"'`
- **AC-946.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-fix3.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 375bdbfe0231cd2f68b36ce2654c9239a966bb42 --range 375bdbfe0231cd2f68b36ce2654c9239a966bb42..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-941…AC-946,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"375bdbfe0231cd2f68b36ce2654c9239a966bb42","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-941","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-fix3-20260917 --spec /home/user/exec-clones/abg-m13a-fix3-20260917/docs/specs/m13a-fix3.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: live bizprofile после
правки не проходит (класс отказа и имена правил детектора без тела); нужна
правка `detect_challenge`, policy продукта, гейта или frozen probes. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
