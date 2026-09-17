# M13a-fix4 — Turnstile и прочие CF-строки челленджа сохраняют cf-mitigated

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `647b19357cda76ee7fcba3b47ac81ffdbc93ac3c` — FINAL M13a-fix3.
Клон /home/user/exec-clones/abg-m13a-fix4-20260917, ветка m13a-fix4, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»; выбор владельца 17.09 —
«сузить + принять остаток»: остаток — только тело БЕЗ CF-маркеров).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002; host — git/файлы/оркестрация. Провайдерские образы не пересобирать.

## Задача

Codex result review M13a-fix3 нашёл, координатор подтвердил чтением
`_BODY_RULES`/`_CAPTCHA_ATTR`: виджет Cloudflare Turnstile
(`<div class="cf-turnstile" data-sitekey=…>`) не даёт ни одного правила
детектора. Поэтому 200 + `cf-mitigated: challenge` + текст проверки +
Turnstile + разрешённый jsd-скрипт получает `challenge=none`.

Это CF-маркер, он не входит в принятый владельцем остаток. Чтобы не закрывать
маркеры по одному, в `ScraplingAdapter.navigate` добавить к условиям fix3
ещё одно: в теле (декодирование и регистр — как в
`_scrapling_only_jsd_platform_paths`) ПОСЛЕ удаления всех вхождений
`/cdn-cgi/challenge-platform/scripts/jsd/` нет ни одной из подстрок
константы (одна frozenset/tuple рядом с адаптером):
`turnstile`, `cf-chl`, `cf_chl`, `challenge-platform`,
`challenges.cloudflare.com`, `cf-challenge`, `cf-captcha`, `hcaptcha`,
`recaptcha`, `g-recaptcha`, `h-captcha`, `/cdn-cgi/challenge`.
Если любая есть — заголовок сохраняется, вердикт как до M13a. Прочие условия
fix2/fix3 остаются (они по-прежнему нужны: вердикт `none`, множество правил,
только jsd-пути). `detect_challenge`, `_BODY_RULES`, `tests/test_detect.py` НЕ
менять.

Тесты в `tests/test_probe.py` (`ScraplingAdapterTests`, через `run_probe`),
падающие на BASE по причине: для КАЖДОЙ подстроки константы — 200 +
`cf-mitigated` + тело из разрешённого jsd-скрипта и этой подстроки (в
естественной разметке, например `class="cf-turnstile"`, `<div
class="h-captcha">`, `<script src="https://www.google.com/recaptcha/api.js">`),
плюс вариант в верхнем регистре для `cf-turnstile` → заголовок сохранён,
`suspected`, `header_cf_mitigated` в маркерах. Контроль: только jsd-скрипт и
обычный контент со словами вроде «challenge»/«cloudflare» без подстрок
константы → заголовок удалён, `none`. Существующие тесты fix/fix2/fix3
сохранить. В `docs/research/08-bizprofile-scrapling.md` — одна-две фразы
(список строк и что остаток — только тело без них).

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: чтение `_BODY_RULES` (5 строк) и
`_CAPTCHA_ATTR` (атрибут со словом captcha) — Turnstile не покрыт. Live
M13a–fix3 у bizprofile зелёный с единственным jsd-скриптом. Предположение:
на главной и карточке bizprofile нет подстрок константы вне jsd-пути; если
live краснеет — blocker с именем найденной подстроки (без тела), не сужение
константы.

## Разрешения

Правка `bench/providers/docker/probe.py` (только условие в
`ScraplingAdapter.navigate`, helper и константа рядом), `tests/test_probe.py`,
`docs/research/08-bizprofile-scrapling.md`. Live-запросы к bizprofile.net: не
больше 6 за прогон, пауза ≥30 с. Commit в клоне.

## Не трогать

`detect_challenge` и его правила, gateway/**, остальной bench/**, deploy/**,
scripts/**, остальные tests (включая `tests/mutation_gate_scrapling.py`) и
frozen probes, другие specs, TASKS/CHANGELOG, `/home/user/services/**`.
Сначала закоммитить эту спеку byte-identical (`docs/specs/m13a-fix4.md`).

## Критерии приёмки

- **AC-961.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-962.** Frozen probes и детектор зелёные и неизменны:
  `bash -c 'git diff --exit-code 647b19357cda76ee7fcba3b47ac81ffdbc93ac3c HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py tests/test_detect.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.test_detect'`
- **AC-963.** Mutation gate M8 убивает все мутанты и восстанавливает дерево:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_scrapling.py && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`
- **AC-964.** Live bizprofile без expected_text:
  `bash -c 'python3 tests/live_m13a_bizprofile.py'`
- **AC-965.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 647b19357cda76ee7fcba3b47ac81ffdbc93ac3c HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_probe.py" ":(exclude)docs/research/08-bizprofile-scrapling.md" ":(exclude)docs/specs/m13a-fix4.md"'`
- **AC-966.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13a-fix4.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 647b19357cda76ee7fcba3b47ac81ffdbc93ac3c --range 647b19357cda76ee7fcba3b47ac81ffdbc93ac3c..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-961…AC-966,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"647b19357cda76ee7fcba3b47ac81ffdbc93ac3c","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-961","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13a-fix4-20260917 --spec /home/user/exec-clones/abg-m13a-fix4-20260917/docs/specs/m13a-fix4.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: live bizprofile после
правки не проходит (класс отказа и имена правил детектора без тела); нужна
правка `detect_challenge`, policy продукта, гейта или frozen probes. Спеку, AC, BASE и
оснастку не менять, rc не выдумывать, ретраями не добиваться зелёного.
