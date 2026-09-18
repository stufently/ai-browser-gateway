# M16a-fix — captcha только при интерактивном виджете

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `5fa9f968ee3fb4e183545f0f79f11436b2196315` — main после слияния M16a и коммита спек M16a-fix и m16a-mutations.
Клон /home/user/exec-clones/abg-m16a-fix-20260918, ветка m16a-fix,
origin push DISABLED. Исполнитель — cx. Реквизит — `docs/specs/m16a-captcha-false-positive.md`
(прочитать целиком) и `git diff e80a5ef c90a395`.

## Зачем

M16a убрала ложную `captcha` на честной странице, но ревью Codex показало цену:
страница-заслон с ИНТЕРАКТИВНЫМ виджетом captcha на HTTP 200 (одна метка
Cloudflare, обычный title, без заголовка `cf-mitigated`) теперь получает `none`,
и продукт без `expected_text` принимает её текст за целевой контент. Решение
владельца 18.09.2026 — различать виджеты по разметке.

Ключ различения проверен на живой фикстуре `tests/fixtures/lowendtalk_200_grecaptcha.html`:
там стоит НЕвидимая reCAPTCHA v3 (`recaptcha/api.js?render=…`, `grecaptcha.execute`,
`grecaptcha.ready`), и ни `g-recaptcha`, ни `data-sitekey`, ни `h-captcha`,
ни `cf-turnstile` в ней нет (проверено координатором `grep -ci` по всем четырём
фикстурам: ни одна не содержит интерактивных меток). Невидимая v3 ставит
странице балл и никогда не требует человека — её присутствие НЕ улика челленджа.
Видимый виджет решает человек — он улика.

Почему это важно для продукта: вердикт `captcha` в `gateway/product.py`
превращается в `F.interactive_challenge` и ведёт прямо в `Step.human` —
лестница останавливается, браузер не пробуется. `suspected` и `access_denied`
ведут к браузеру. Поэтому `captcha` обязана требовать настоящего виджета.

## Задача

Ровно в `bench/providers/docker/probe.py`, функция `detect_challenge` и таблицы
рядом с ней:

1. Ввести распознавание ИНТЕРАКТИВНОГО виджета отдельно от нынешнего
   `_CAPTCHA_ATTR`. Считать интерактивным: класс `g-recaptcha`, `h-captcha`
   или `cf-turnstile`; атрибут `data-sitekey`; подключение
   `recaptcha/api.js` БЕЗ параметра `render=`. Не считать интерактивным
   `recaptcha/api.js?render=…` и вызовы `grecaptcha.execute`/`grecaptcha.ready`.
   При срабатывании добавлять в возвращаемые метки имя
   `body_captcha_interactive` ПОСЛЕ `body_captcha`; имя `body_captcha` и
   регулярка `_CAPTCHA_ATTR` остаются как есть.
2. `captcha_confirmed` привести к честному виду: `decisive_body or status in
   (403, 429)`. Дизъюнкты `header_names` и `body_enough` удалить — они
   недостижимы в точке использования (ранние `return` по `header_verdict` и по
   `body_enough`), это независимо подтверждено мутациями Grok 18.09.2026
   (M07, M08 — equivalent с доказательством).
3. Ветку `captcha` выдавать только при интерактивном виджете:
   вместо `if captcha_names and captcha_confirmed:` — условие, требующее
   срабатывания интерактивного распознавания И `captcha_confirmed`.
   Порядок веток (`header_verdict` → `body_enough` → `captcha` → статус →
   `none`) не менять.
4. `RULE_PROVENANCE` дополнить записью `body_captcha_interactive` со значением
   `ASSUMED` (как у `body_captcha`): разметка виджета — наблюдение, а не
   документированный контракт.

Ожидаемые изменения поведения (все — намеренные):

| вход | было после M16a | стало |
| --- | --- | --- |
| фикстура lowendtalk, 200 | `none` + обе метки | без изменений |
| фикстура lowendtalk, 403 | `captcha` | `access_denied` (виджета нет, уводим в браузер, а не к человеку) |
| 1 метка CF + `<div class="g-recaptcha" data-sitekey=…>`, 200 | `none` | `captcha` |
| тот же виджет БЕЗ меток CF, 200 | `none` | `none` (обычная форма логина) |
| интерактивный виджет БЕЗ меток CF + статус 500 или 404 | `none` | `none` (подтверждают только 403/429, а не любой 4xx/5xx) |
| НЕинтерактивный captcha-атрибут + 403 | `captcha` | `access_denied` (уводим в браузер, а не к человеку) |
| НЕинтерактивный captcha-атрибут + 429 | `captcha` | `rate_limited` |

Тесты в `tests/test_detect.py`. Координатор прогнал прототип этой правки
18.09.2026: ожидание меняется РОВНО у пяти существующих тестов, и все пять
обязаны быть обновлены по существу, а не ослаблены:

- `test_captcha_with_403_is_captcha_and_named` → теперь `access_denied`
  (тело — `<img id="captcha-history">`, виджета нет);
- `test_captcha_with_429_is_captcha_and_named` → теперь `rate_limited`
  (тело — `<div class="g-captcha">`, это не `g-recaptcha`);
- `test_lowendtalk_grecaptcha_on_403_is_captcha` → теперь `access_denied`;
- `test_provenance_covers_every_rule_and_nothing_else` → в набор `named`
  добавить `body_captcha_interactive`;
- `test_assumed_rule_never_decides_a_verdict_alone` → в `ASSUMED_SAMPLES`
  добавить минимальное тело, поднимающее ТОЛЬКО новое правило
  (`<div class="g-recaptcha" data-sitekey="k"></div>`): на 200 оно обязано
  давать `none` и называть метку.

Кроме того `test_exact_provenance_of_the_one_unmeasured_rule` больше не про
«одно» правило: расширить его на оба `assumed`-правила и переименовать
соответственно.

Добавить случаи из таблицы, включая два, закрывающие выживших мутантов прогона Grok:
статус вне `{200, 403, 429}` вместе с captcha-атрибутом (мутант `status >= 400`)
и body-иглы в ВЕРХНЕМ регистре (мутант «сравнивать по `text`, не по `lowered`»:
тело `<p>CHALLENGES.CLOUDFLARE.COM CF_CHL_OPT</p>` на 200 обязано дать
`suspected` с обеими метками). Новых фикстур не заводить — тела задавать в
тестах строками, как уже принято в этом файле.

В `tests/mutation_gate.py` ДОБАВИТЬ (не править существующие) ровно три мутанта
на новую логику: снять требование интерактивности в ветке `captcha`; заменить
`status in (403, 429)` на `status >= 400`; сравнивать body-иглы по `text`
вместо `lowered`. У каждого — свой тест из авторского набора, который его убивает.

`docs/research/04-phase1-verdict.md`: в раздел «Ложная captcha на 200 (M16a)»
добавить подраздел «Интерактивный виджет (M16a-fix)» — находка Codex, ключ
различения, таблица выше, и честная пометка, что разметка виджетов —
предположение, а не контракт.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 на РАБОТАЮЩЕМ прототипе этой правки: все
строки таблицы выше воспроизведены ровно так, как записаны, и падают ровно
пять перечисленных тестов. В фикстуре lowendtalk только v3
(`render=`), интерактивных меток нет ни в одной из четырёх фикстур;
вердикт `captcha` ведёт в `Step.human` без попытки браузера
(`gateway/product.py:82`, `162`); мутации Grok дали 21 kill / 2 survivor /
3 equivalent, откат M16a убивается, оба выживших мутанта — ровно те, что
закрывает эта веха.

Предположение: перечисленные классы и атрибуты покрывают практически
встречающиеся интерактивные виджеты. Проверяется вживую только выкладкой M16b.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py` (только добавление трёх мутантов),
`docs/research/04-phase1-verdict.md`. Docker-прогоны образом из критериев.
Commit в клоне.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных файлов, существующие фикстуры и
`tests/fixtures/README.md`, `_BODY_RULES`, `_SUPPORTING_BODY_RULES`,
`_CAPTCHA_ATTR`, порядок веток `return`, `RULE_PROVENANCE["body_captcha"]`
(остаётся `ASSUMED`), другие specs, TASKS.md, CHANGELOG.md, `secrets/**`,
`/home/user/services/**`. Сеть не нужна: все прогоны `--network none`.
Push и merge запрещены. Спека `docs/specs/m16a-fix-interactive-captcha.md`
уже отслеживается в BASE — её не менять и не коммитить заново; критерий
чистоты дерева считает её изменение отклонением.

## Критерии приёмки

- **AC-115.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-116.** Живая фикстура: 200 без изменений, 403 больше не captcha:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); b=open(\"tests/fixtures/lowendtalk_200_grecaptcha.html\",encoding=\"utf-8\").read(); assert m.detect_challenge(200,{},b)==(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")), m.detect_challenge(200,{},b); assert m.detect_challenge(403,{},b)[0]==\"access_denied\", m.detect_challenge(403,{},b)"'`
- **AC-117.** Интерактивный виджет закрывает находку Codex:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); w=\"<div class=\\\"g-recaptcha\\\" data-sitekey=\\\"k\\\"></div>\"; cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; v,n=m.detect_challenge(200,{},cf+w); assert v==\"captcha\", (v,n); assert \"body_captcha_interactive\" in n, n; assert m.detect_challenge(200,{},w)[0]==\"none\", m.detect_challenge(200,{},w); assert m.detect_challenge(500,{},w)[0]==\"none\", m.detect_challenge(500,{},w); assert m.detect_challenge(404,{},w)[0]==\"none\", m.detect_challenge(404,{},w)"'`
- **AC-118.** Невидимая v3 уликой не считается, регистр body-игл не важен:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; v3=\"<script src=\\\"https://www.google.com/recaptcha/api.js?render=KEY\\\"></script>\"; assert m.detect_challenge(200,{},cf+v3)[0]==\"none\"; assert \"body_captcha_interactive\" not in m.detect_challenge(200,{},cf+v3)[1]; u,un=m.detect_challenge(200,{},\"<p>CHALLENGES.CLOUDFLARE.COM CF_CHL_OPT</p>\"); assert u==\"suspected\", (u,un); assert \"body_cf_challenges_host\" in un and \"body_cf_chl_opt\" in un, un; assert m.RULE_PROVENANCE[\"body_captcha\"]==\"assumed\" and m.RULE_PROVENANCE[\"body_captcha_interactive\"]==\"assumed\""'`
- **AC-119.** Заголовок и настоящий интерстишл не сломаны:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); i=open(\"tests/fixtures/cf_interstitial_200body_403.html\",encoding=\"utf-8\").read(); assert m.detect_challenge(403,{},i)[0]==\"suspected\", m.detect_challenge(403,{},i); assert m.detect_challenge(200,{\"cf-mitigated\":\"challenge\"},i)[0]==\"suspected\"; assert m.detect_challenge(200,{\"cf-mitigated\":\"interactive\"},i)[0]==\"interactive\""'`
- **AC-120.** Мутационные ворота с тремя новыми мутантами:
  `bash -c 'test "$(git diff 5fa9f968ee3fb4e183545f0f79f11436b2196315 HEAD -- tests/mutation_gate.py | grep -c "^-[^-]")" -eq 0 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/runner/execute.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-121.** Документы и провенанс:
  `bash -c 'grep -q "Интерактивный виджет (M16a-fix)" docs/research/04-phase1-verdict.md && grep -q "render=" docs/research/04-phase1-verdict.md && git grep -q "\"body_captcha\": ASSUMED," -- bench/providers/docker/probe.py && git grep -q "_CAPTCHA_ATTR = re.compile" -- bench/providers/docker/probe.py'`
- **AC-122.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 5fa9f968ee3fb4e183545f0f79f11436b2196315 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix-interactive-captcha.md" && git ls-files --error-unmatch docs/specs/m16a-fix-interactive-captcha.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 5fa9f968ee3fb4e183545f0f79f11436b2196315 --range 5fa9f968ee3fb4e183545f0f79f11436b2196315..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 8 записей AC-115…AC-122,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"5fa9f968ee3fb4e183545f0f79f11436b2196315","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-115","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix-20260918 --spec /home/user/exec-clones/abg-m16a-fix-20260918/docs/specs/m16a-fix-interactive-captcha.md --timeout 3600`
и НЕ запускает мутационные ворота параллельно с этой командой: ворота правят
файлы дерева на месте, два одновременных прогона в одном клоне оставляют
мутантов применёнными (наблюдалось 18.09.2026 на приёмке M16a).

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется править запрещённые пути; какая-то из строк таблицы ожидаемого
поведения недостижима без изменения порядка веток `return`; новый мутант не
убивается ни одним тестом авторского набора (это дыра в тестах — доложить, а
не ослаблять мутанта); ворота падают на мутанте, не относящемся к этой вехе.
Спеку, AC, BASE и существующих мутантов не менять, rc не выдумывать.
