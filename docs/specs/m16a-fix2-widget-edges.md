# M16a-fix2 — три дефекта распознавания виджета

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `7b003493d996a30759ccbc612ad9e6d65f895825` — ветка `m16a-fix` (FINAL
предыдущей вехи, ещё НЕ влита в main: сливаем только после этой правки).
Клон /home/user/exec-clones/abg-m16a-fix2-20260918, ветка m16a-fix2,
origin push DISABLED. Исполнитель — cx. Реквизит —
`docs/specs/m16a-fix-interactive-captcha.md` (прочитать целиком).

## Зачем

Ревью Codex по M16a-fix дало три находки, и координатор воспроизвёл ВСЕ ТРИ
вживую в разрешённом Docker-образе на коммите BASE:

1. **Пропуск настоящего виджета.** Условие «`recaptcha/api.js` без `render=`»
   отсекает и `render=explicit` — а это ЯВНЫЙ рендер интерактивной reCAPTCHA v2
   (документация Google, «explicit render»), то есть настоящий виджет.
   Вход `<script src="…/recaptcha/api.js?onload=cb&render=explicit">` + одна
   метка CF на 200 даёт `('none', ('body_cf_challenge_platform','body_captcha'))`,
   а должен давать `captcha`.
2. **Необработанное исключение.** `widget.feed(text)` роняет
   `ValueError: Exceeds the limit (4300 digits) for integer string conversion`
   на теле `"&#" + "9"*5000 + ";"`. Детектор обязан быть чистой функцией без
   отказов: любая страница может нести такую сущность, и успешный ответ
   превратится в `provider_error` с потерей статуса и меток.
3. **Ложная captcha из `<template>`.** Разметка внутри `<template>` инертна —
   это заготовка, а не виджет на странице. Вход
   `<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>` +
   `<template><div data-sitekey="k"></div></template>` на 200 даёт `captcha`,
   то есть продукт уходит в `Step.human` без попытки браузера. Это ровно тот
   класс ложных срабатываний, ради которого затевалась веха M16.

## Задача

Ровно в `bench/providers/docker/probe.py`, внутри `detect_challenge`:

1. `render=explicit` считать ИНТЕРАКТИВНЫМ. Значение `render=<ключ сайта>`
   (любое другое) остаётся невидимой v3 и уликой не является. Отсутствие
   `render=` — по-прежнему интерактивно. Учесть повторы параметра: если среди
   значений `render=` есть `explicit`, это виджет.
2. Разбор разметки не имеет права бросать наружу. Координатор проверил рабочую
   связку: `HTMLParser(convert_charrefs=False)` плюс `try/except` вокруг `feed`,
   где уже распознанное сохраняется, а исключение гасится. Иной способ
   допустим, если он даёт те же результаты в критериях.
3. Содержимое `<template>` игнорировать: считать вложенность открывающих и
   закрывающих `template` и не смотреть теги внутри. Вложенные `<template>`
   учитывать счётчиком, а не флагом.

Больше в детекторе ничего не менять: порядок веток `return`, `captcha_confirmed`,
`_BODY_RULES`, `_CAPTCHA_ATTR`, `_CAPTCHA_WIDGET_CLASSES`, имена меток и
`RULE_PROVENANCE` остаются как в BASE.

Проверено координатором на РАБОТАЮЩЕМ прототипе именно этих трёх правок:
все 52 теста `tests.test_detect` остаются зелёными без единой правки теста, а
три входа выше дают `captcha`, `('none', ())` и `none` соответственно.

Тесты в `tests/test_detect.py` — только ДОБАВИТЬ, существующие не трогать:
- `render=explicit` (в том числе вместе с `onload=`) + одна метка CF на 200 →
  `captcha` с меткой `body_captcha_interactive`; `render=КЛЮЧ` в тех же
  условиях → `none` без этой метки;
- тело `"&#" + "9"*5000 + ";"` и то же тело вместе с настоящим виджетом →
  функция ВОЗВРАЩАЕТ значение, а не бросает (второй случай — проверить, что
  распознанное до сбоя не теряется, если ваш способ это гарантирует; если нет,
  зафиксировать фактическое поведение и объяснить в отчёте);
- виджет внутри `<template>` (и внутри вложенных `<template>`) + метка CF на
  200 → `none`; виджет ПОСЛЕ закрывающего `</template>` в том же теле → `captcha`.

В `tests/mutation_gate.py` ДОБАВИТЬ ровно три мутанта: снять распознавание
`render=explicit`; убрать `try/except` вокруг `feed`; убрать учёт `template`.
Существующие мутанты не трогать — их цели этой правкой не задеты (проверить).

`docs/research/04-phase1-verdict.md`: в подраздел «Интерактивный виджет
(M16a-fix)» добавить абзац о трёх краевых случаях и о том, что детектор не
бросает исключений наружу.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 в разрешённом Docker-образе на коммите BASE:
все три находки воспроизведены дословно теми входами, что записаны выше
(`render=explicit` → `none` вместо `captcha`; `"&#"+"9"*5000+";"` → необработанный
`ValueError` про лимит в 4300 цифр; виджет в `<template>` → ложная `captcha`).
На прототипе из трёх правок (`convert_charrefs=False`, `try/except` вокруг
`feed`, счётчик `template`, `render=explicit` как виджет) все 52 теста
`tests.test_detect` зелёные без единой правки теста, а поведение фикстур,
интерстишла и заголовка `cf-mitigated` не сдвинулось — это и проверяют AC-126.

Предположение: других тегов с инертным содержимым, которые надо пропускать
наравне с `<template>`, на практике не встречается. Проверяется только живым
трафиком после выкладки M16b.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py` (только добавление трёх мутантов),
`docs/research/04-phase1-verdict.md`. Docker-прогоны образом из критериев.
Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix2-widget-edges.md` byte-identical: она приезжает untracked,
и без этого критерий чистоты дерева недостижим.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных файлов, фикстуры и `tests/fixtures/README.md`,
другие specs, TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`.
Сеть не нужна: все прогоны `--network none`. Push и merge запрещены.

## Критерии приёмки

- **AC-123.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-124.** Три находки закрыты ровно как записано:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; e=cf+\"<script src=https://www.google.com/recaptcha/api.js?onload=cb&render=explicit></script>\"; assert m.detect_challenge(200,{},e)[0]==\"captcha\", m.detect_challenge(200,{},e); v3=cf+\"<script src=https://www.google.com/recaptcha/api.js?render=KEY></script>\"; assert m.detect_challenge(200,{},v3)[0]==\"none\", m.detect_challenge(200,{},v3); assert m.detect_challenge(200,{},\"&#\"+\"9\"*5000+\";\")[0]==\"none\"; t=cf+\"<template><div data-sitekey=k></div></template>\"; assert m.detect_challenge(200,{},t)[0]==\"none\", m.detect_challenge(200,{},t); a=cf+\"<template><span></span></template><div data-sitekey=k></div>\"; assert m.detect_challenge(200,{},a)[0]==\"captcha\", m.detect_challenge(200,{},a)"'`
- **AC-125.** Детектор не бросает наружу на враждебной разметке:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); bad=[\"&#\"+\"9\"*5000+\";\", \"&#\"+\"1\"*9000+\";<div data-sitekey=k></div>\", \"<div class=g-recaptcha\", \"<template><template><div data-sitekey=k>\", chr(0)+\"<div data-sitekey=k>\", \"<!--<div data-sitekey=k>-->\"]; [m.detect_challenge(st,{},b) for b in bad for st in (200,403,429,500)]; print(\"ok\")"'`
- **AC-126.** Поведение прежней вехи не сдвинуто:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); b=open(\"tests/fixtures/lowendtalk_200_grecaptcha.html\",encoding=\"utf-8\").read(); i=open(\"tests/fixtures/cf_interstitial_200body_403.html\",encoding=\"utf-8\").read(); assert m.detect_challenge(200,{},b)==(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")); assert m.detect_challenge(403,{},b)[0]==\"access_denied\"; assert m.detect_challenge(403,{},i)[0]==\"suspected\"; assert m.detect_challenge(200,{\"cf-mitigated\":\"interactive\"},i)[0]==\"interactive\"; w=\"<div class=\\\"g-recaptcha\\\" data-sitekey=\\\"k\\\"></div>\"; assert m.detect_challenge(200,{},w)[0]==\"none\"; cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; assert m.detect_challenge(200,{},cf+w)[0]==\"captcha\""'`
- **AC-127.** Мутационные ворота с тремя новыми мутантами:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 111 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-128.** Документы:
  `bash -c 'grep -q "Интерактивный виджет (M16a-fix)" docs/research/04-phase1-verdict.md && grep -q "explicit" docs/research/04-phase1-verdict.md && grep -q "template" docs/research/04-phase1-verdict.md'`
- **AC-129.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 7b003493d996a30759ccbc612ad9e6d65f895825 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix2-widget-edges.md" && git ls-files --error-unmatch docs/specs/m16a-fix2-widget-edges.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 7b003493d996a30759ccbc612ad9e6d65f895825 --range 7b003493d996a30759ccbc612ad9e6d65f895825..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне:
они правят файлы дерева на месте, два одновременных прогона оставляют
мутантов применёнными (наблюдалось дважды 18.09.2026).

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-123…AC-129,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"7b003493d996a30759ccbc612ad9e6d65f895825","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-123","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix2-20260918 --spec /home/user/exec-clones/abg-m16a-fix2-20260918/docs/specs/m16a-fix2-widget-edges.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется править запрещённые пути или существующие тесты; какое-то из трёх
ожиданий недостижимо без изменения порядка веток или `captcha_confirmed`;
новый мутант не убивается ни одним тестом авторского набора; ворота падают на
мутанте, не относящемся к этой вехе. Спеку, AC, BASE и существующих мутантов
не менять, rc не выдумывать.
