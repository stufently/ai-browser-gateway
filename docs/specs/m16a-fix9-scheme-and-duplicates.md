# M16a-fix9 — схема URL и дублирующиеся атрибуты

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `42611a9932abae762e4353c4a7fa7e4ecc66c9c0` — FINAL M16a-fix8.
Клон /home/user/exec-clones/abg-m16a-fix9-20260918, ветка m16a-fix9,
origin push DISABLED. Исполнитель — cx (директива владельца: «доделывай все
через кодекс»). Решение владельца 18.09.2026: чинить обе находки точечно.

Детектор `bench/providers/docker/probe.py` решает, отдана ли страница или это
челлендж. Ложная `captcha` на честном HTTP 200 останавливает продукт на
`Step.human`, и страница не отдаётся — это главный дефект, ради которого
существует вся цепочка M16a.

## Зачем

Две находки по FINAL M16a-fix8, обе воспроизведены координатором в НАСТОЯЩЕМ
Chromium (`abg-playwright:m2`, `new URL` + `classList` + `createHTMLDocument`),
обе дают ложную `captcha` на HTTP 200:

1. **Обратный слэш заменяется безусловно** (регресс, внесённый самой fix8;
   находка Codex). Браузер считает `\` разделителем пути только для
   special-схем. Замер: `new URL("data:text/javascript,//recaptcha\api.js?render=explicit")`
   даёт path `text/javascript,//recaptcha\api.js` — слэш СОХРАНЁН; то же у
   `blob:`. А `recaptcha\api.js` (относительный) и `https:\\www.google.com\recaptcha\api.js`
   дают `/recaptcha/api.js` — слэш заменён. Наш детектор после fix8 заменяет
   всегда, поэтому безобидный `data:`-скрипт с комментарием `//…` стал
   `captcha`: на BASE fix7 было `none`, после fix8 — `captcha`.
2. **Дублирующийся атрибут**. HTML-токенизатор браузера оставляет ПЕРВЫЙ
   одноимённый атрибут и отбрасывает последующие; замер в Chromium:
   `<div class="foo" class="g-recaptcha">` → `getAttribute("class")` = `foo`,
   `classList` = `["foo"]`; `<script src="one.js" src="two.js">` → `one.js`.
   Python отдаёт оба в `attrs`, а `dict(...)` оставляет ПОСЛЕДНИЙ. Дефект
   существует с самого появления разбора атрибутов, fix8 его не вносила.

## Задача

1. **Схема решает, заменять ли слэш.** Заменять `\` на `/` в `src` только
   когда значение относительное (схемы нет) либо схема — special. Набор
   special-схем по стандарту URL: `http`, `https`, `ws`, `wss`, `ftp`, `file`;
   сравнение регистронезависимое. Схема определяется как
   `[A-Za-z][A-Za-z0-9+.-]*` перед первым `:`.
2. **Порядок.** Обрезку краёв перенести ПЕРЕД заменой слэша, чтобы схема
   определялась по уже очищенному значению: NUL → U+FFFD, затем удаление
   `\t\n\r`, затем обрезка краёв, затем условная замена `\`, затем прежний
   разбор фрагмента и query. Перестановка обрезки и удаления `\t\n\r`
   поведение не меняет — доказано мутационным прогоном M16a-fix8 (мутант M04
   признан equivalent: множество удаляемых `\t\n\r` — подмножество множества
   обрезки, операции коммутируют; 349 различающих входов дали 0 расхождений).
3. **Первый дубль побеждает.** Строить словарь атрибутов так, чтобы при
   одноимённых атрибутах оставался ПЕРВЫЙ (например, проход по `reversed(attrs)`).
   Замена NUL → U+FFFD сохраняется для всех значений.
4. **Тесты `tests/test_detect.py`.** Полные кортежи, не только вердикт.
   Все значения ниже ПОСЧИТАНЫ координатором на прототипе правки, а не
   выведены рассуждением; `cf` — строка
   `<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>`:
   - `data:`, `blob:`, `javascript:` со слэшем и `render=explicit` на 200 →
     `("none", ("body_cf_challenge_platform", "body_captcha"))`;
   - относительный `recaptcha\api.js?render=explicit`, абсолютный
     `https:\\www.google.com\recaptcha\api.js?render=explicit` и он же с
     `HTTPS:` в верхнем регистре на 200 →
     `("captcha", ("body_cf_challenge_platform", "body_captcha", "body_captcha_interactive"))`;
   - `<div class="foo" class="g-recaptcha"></div>` на 200 →
     `("none", ("body_cf_challenge_platform", "body_captcha"))`, на 403 →
     `("access_denied", ("body_captcha", "status_403"))`;
   - обратный порядок `<div class="g-recaptcha" class="foo"></div>` на 200 →
     `("captcha", ("body_cf_challenge_platform", "body_captcha", "body_captcha_interactive"))`
     — первый дубль и есть виджет;
   - `<script src="one.js" src="recaptcha/api.js?render=explicit"></script>` на
     200 → `("none", ("body_cf_challenge_platform", "body_captcha"))`;
     обратный порядок → `captcha` с тем же полным кортежем, что строкой выше.
5. **Мутанты `tests/mutation_gate.py`**: два новых — по одному на пункт 1 и
   пункт 3; каждый обязан убиваться своим новым тестом. Определения прежних
   мутантов, чьи строки `old` сдвинулись правкой (в первую очередь мутант
   обратного слэша), привести в соответствие. Итого в воротах 142.
6. **Документ** `docs/research/04-phase1-verdict.md`: в раздел
   «Соответствие разбору браузера (M16a-fix8)» добавить абзац про схему и
   дубли со ссылкой на замеры в Chromium.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 в образе `abg-playwright:m2` (Chromium,
provider_version 1.62.0, `--network none`): поведение `new URL` для `data:`,
`blob:`, относительного пути и `https:` с обратными слэшами; правило первого
дубля для `class`, `src`. Проверено на прототипе правки: все кортежи пункта 4
и то, что существующий набор из 607 тестов остаётся зелёным.

Предположение: имена помощников, место константы со списком схем и способ
обхода `attrs` — на усмотрение автора.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py`, `docs/research/04-phase1-verdict.md`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix9-scheme-and-duplicates.md` byte-identical.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных, фикстуры, другие specs, TASKS.md,
CHANGELOG.md, `secrets/**`, `/home/user/services/**`. Сеть не нужна.
Push и merge запрещены.

## Критерии приёмки

- **AC-190.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-191.** Non-special схемы больше не дают ложную captcha, special и относительные — дают:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; mk=lambda v: cf+\"<script src=\\\"\"+v+\"\\\"></script>\"; none=(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")); cap=(\"captcha\",(\"body_cf_challenge_platform\",\"body_captcha\",\"body_captcha_interactive\")); [sys.exit(\"non-special: \"+v+\" -> \"+repr(m.detect_challenge(200,{},mk(v)))) for v in (\"data:text/javascript,//recaptcha\\\\api.js?render=explicit\",\"blob:https://e/recaptcha\\\\api.js?render=explicit\",\"javascript://recaptcha\\\\api.js?render=explicit\") if m.detect_challenge(200,{},mk(v))!=none]; [sys.exit(\"special: \"+v+\" -> \"+repr(m.detect_challenge(200,{},mk(v)))) for v in (\"recaptcha\\\\api.js?render=explicit\",\"https:\\\\\\\\www.google.com\\\\recaptcha\\\\api.js?render=explicit\",\"HTTPS:\\\\\\\\www.google.com\\\\recaptcha\\\\api.js?render=explicit\") if m.detect_challenge(200,{},mk(v))!=cap]; print(\"ok\")"'`
- **AC-192.** Из дублирующихся атрибутов берётся первый:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; none=(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")); cap=(\"captcha\",(\"body_cf_challenge_platform\",\"body_captcha\",\"body_captcha_interactive\")); assert m.detect_challenge(200,{},cf+\"<div class=\\\"foo\\\" class=\\\"g-recaptcha\\\"></div>\")==none, m.detect_challenge(200,{},cf+\"<div class=\\\"foo\\\" class=\\\"g-recaptcha\\\"></div>\"); assert m.detect_challenge(403,{},\"<div class=\\\"foo\\\" class=\\\"g-recaptcha\\\"></div>\")==(\"access_denied\",(\"body_captcha\",\"status_403\")), m.detect_challenge(403,{},\"<div class=\\\"foo\\\" class=\\\"g-recaptcha\\\"></div>\"); assert m.detect_challenge(200,{},cf+\"<div class=\\\"g-recaptcha\\\" class=\\\"foo\\\"></div>\")==cap; assert m.detect_challenge(200,{},cf+\"<script src=\\\"one.js\\\" src=\\\"recaptcha/api.js?render=explicit\\\"></script>\")==none; assert m.detect_challenge(200,{},cf+\"<script src=\\\"recaptcha/api.js?render=explicit\\\" src=\\\"one.js\\\"></script>\")==cap; print(\"ok\")"'`
- **AC-193.** Поведение M16a-fix8 не сдвинуто:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys,time; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; mk=lambda v: cf+\"<script src=\\\"\"+v+\"\\\"></script>\"; none=(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")); cap=(\"captcha\",(\"body_cf_challenge_platform\",\"body_captcha\",\"body_captcha_interactive\")); assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=explicit\\x00\"))==none; assert m.detect_challenge(403,{},\"<div class=\\\"g-recaptcha\\u00a0foo\\\"></div>\")==(\"access_denied\",(\"body_captcha\",\"status_403\")); assert m.detect_challenge(200,{},cf+\"<div class=\\\"g-recaptcha\\tfoo\\\"></div>\")==cap; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=explicit \"))==cap; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render= explicit\"))==none; assert m.detect_challenge(200,{},mk(\"xrecaptcha/api.js?render=explicit\"))==none; assert m.detect_challenge(403,{},\"<div class></div>\")==(\"access_denied\",(\"status_403\",)); t=time.perf_counter(); m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=\"+\" \"*32000+\"KEY\")); d=time.perf_counter()-t; assert d<2.0, d; print(\"ok\", round(d,4))"'`
- **AC-194.** Мутационные ворота: два новых убиты, всего 142:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 142 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-195.** Документ:
  `bash -c 'grep -q "data:" docs/research/04-phase1-verdict.md && grep -q "дубл" docs/research/04-phase1-verdict.md'`
- **AC-196.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 42611a9932abae762e4353c4a7fa7e4ecc66c9c0 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix9-scheme-and-duplicates.md" && git ls-files --error-unmatch docs/specs/m16a-fix9-scheme-and-duplicates.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix9-20260918 --base 42611a9932abae762e4353c4a7fa7e4ecc66c9c0 --range 42611a9932abae762e4353c4a7fa7e4ecc66c9c0..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-190…AC-196,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"42611a9932abae762e4353c4a7fa7e4ecc66c9c0","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-190","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix9-20260918 --spec /home/user/exec-clones/abg-m16a-fix9-20260918/docs/specs/m16a-fix9-scheme-and-duplicates.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
какой-то из посчитанных кортежей пункта 4 недостижим (тогда показать
фактический результат и объяснить, какое правило детектора его даёт — это
ошибка координатора, а не повод менять правило); мутант не убивается своим
тестом; правка требует выхода за разрешённые файлы. Спеку, AC, BASE и оснастку
не менять, rc не выдумывать, чужое не трогать. Обходить несовместимость
запрещено.
