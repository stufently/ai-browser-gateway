# M16a-fix3 — гигантские числовые сущности и самозакрытый `<template/>`

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `6ff902fb7746929865c4e8e0db6599d81cbffe4a` — ветка `m16a-fix3` от вершины `m16a-fix2` (ни `m16a-fix`,
ни `m16a-fix2` в main ещё НЕ влиты: вся цепочка сливается после этой правки).
Клон /home/user/exec-clones/abg-m16a-fix3b-20260918, ветка m16a-fix3,
origin push DISABLED. Исполнитель — cx. Реквизит — спеки
`docs/specs/m16a-fix-interactive-captcha.md` и
`docs/specs/m16a-fix2-widget-edges.md` (прочитать целиком).

## Зачем

Ревью Codex по M16a-fix2 дало четыре находки, координатор воспроизвёл ВСЕ
ЧЕТЫРЕ вживую в разрешённом Docker-образе на коммите BASE. Две из них — один
корень, две — самостоятельные.

**Корень (находки 1–3): `int()` с лимитом 4300 цифр.** Python ≥3.11 бросает
`ValueError: Exceeds the limit (4300 digits) for integer string conversion`, и
`html.unescape` наступает на это на любой числовой сущности вида `&#<много
цифр>;`. Прошлая веха закрыла ровно ОДИН путь (`feed` в `try/except`), а
`html.unescape` вызывается ещё в двух местах, и оба на живом маршруте:

1. `_title()` → `_decisive_title()` внутри `detect_challenge`: тело
   `<title>&#999…9;</title>` (5000 девяток) роняет детектор наружу. Успешный
   ответ становится `provider_error` с потерей статуса и меток — даже когда в
   заголовках лежит `cf-mitigated`.
2. `html_to_text()` (через `_VisibleText`, у него `convert_charrefs=True`):
   то же тело роняет извлечение текста. Продукт ВСЕГДА просит содержимое, так
   что починка одного детектора исходный отказ не убирает: `run_probe`
   возвращает `status=None` и ошибку вместо страницы.
3. Тот самый `try/except` вокруг `feed` глушит исключение, но остаток страницы
   остаётся НЕПРОСМОТРЕННЫМ. Вход
   `<script src=/cdn-cgi/…/jsd/main.js></script><div title="&#999…9;"></div><div
   data-sitekey="k"></div>` на 200 даёт `none` вместо `captcha`: настоящий
   виджет за сущностью не виден. Это ровно тот отказ, ради которого веха M16
   и затевалась, только в обратную сторону.

**Находка 4: `<template/>`.** `HTMLParser` по умолчанию разбирает самозакрытый
тег через `handle_startendtag`, то есть зовёт `handle_starttag` и сразу
`handle_endtag` — вложенность `template` возвращается в ноль. По стандарту HTML
косая черта в закрывающей позиции у НЕ-void элемента игнорируется: `<template/>`
ОТКРЫВАЕТ шаблон, и разметка за ним инертна до `</template>`. Вход
`<script src=/cdn-cgi/…/jsd/main.js></script><template/><div
data-sitekey="k"></div></template>` на 200 даёт ложную `captcha` и `Step.human`
без попытки браузера.

## Задача

Ровно в `bench/providers/docker/probe.py`.

1. **Обезвредить гигантские числовые сущности один раз, на входе.** Завести
   модульный помощник (имя на усмотрение автора, например
   `_clip_oversized_charrefs`): числовая сущность, значение которой заведомо
   вне диапазона Unicode, заменяется на символ замены U+FFFD (`"\ufffd"`). Так же поступает и
   стандарт HTML с out-of-range ссылкой, так что это не эвристика, а
   приведение к спецификации.
   - Точка отсчёта «заведомо вне диапазона»: значащих (без ведущих нулей)
     десятичных цифр 8 и больше либо шестнадцатеричных 7 и больше. Максимальный
     кодпойнт `0x10FFFF` = 1114111 — семь десятичных, шесть шестнадцатеричных
     цифр, он и всё меньшее обязаны проходить НЕТРОНУТЫМИ.
   - Завершающая `;` НЕОБЯЗАТЕЛЬНА: `html.unescape` разбирает и `&#999…9` без
     неё (регулярка стандартной библиотеки — `&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|…)`),
     и именно этот вариант остаётся миной, если требовать точку с запятой.
   - Применить в трёх местах: к `text` в самом начале `detect_challenge`
     (сразу после декодирования тела), к телу внутри `html_to_text` перед
     `feed`, и к захваченному заголовку внутри `_title` перед `unescape`.
     Контракт вывода `_title` не меняется: у нормальных страниц результат тот
     же байт в байт.
2. **Снять `try/except` вокруг `widget.feed(text)`.** После пункта 1 входа,
   роняющего `feed`, не осталось: координатор прогнал девять враждебных
   вариантов (`<![invalid]>`, `<!xxxx>`, `</>`, `<?php ?>`, `<!DOCTYPE>`, сущность
   в атрибуте, две тысячи `<` подряд и прочее) — ни один не бросает. А глушение
   ЛЮБОГО исключения вредно: оно прячет и будущую ошибку в коде, и превращает
   заслон в `none`, то есть продукт примет страницу-заслон за целевой контент.
   Необработанное исключение хотя бы уходит в `provider_error`, и лестница
   идёт дальше. Мутанта `110` (снятие `try/except`) при этом УДАЛИТЬ из
   `tests/mutation_gate.py`: его цель исчезает вместе с кодом.
3. **Самозакрытый тег — только открывающий.** Переопределить
   `handle_startendtag` так, чтобы он звал только `handle_starttag` и НЕ звал
   `handle_endtag`. Тогда `<template/>` открывает шаблон, как в браузере, а
   самозакрытый `<div data-sitekey="k"/>` по-прежнему считается виджетом.

Больше в детекторе ничего не менять: порядок веток `return`,
`captcha_confirmed`, `_BODY_RULES`, `_CAPTCHA_ATTR`, `_CAPTCHA_WIDGET_CLASSES`,
имена меток, `RULE_PROVENANCE` и распознавание `render=explicit` остаются как
в BASE.

Проверено координатором на РАБОТАЮЩЕМ прототипе именно этих правок: помощник
клипует `&#<5000 девяток>` с точкой с запятой и без, hex-форму и оба варианта в
атрибуте, но НЕ трогает `&#1114111;`, `&#x10FFFF;`, `&#65;`, `&#x41;`,
`&#0000065;`; на документе 240 КиБ работает за 0.2 мс; переопределённый
`handle_startendtag` даёт на входе `<template/><div data-sitekey=k></div></template>`
ожидаемую последовательность событий.

Тесты в `tests/test_detect.py` — ДОБАВИТЬ новые; из существующих разрешено
менять ровно три, чьё утверждение правка делает сильнее:
`test_oversized_character_reference_does_not_raise`,
`test_parser_error_preserves_recognized_widget`,
`test_parser_error_preserves_header_and_status_verdicts`. Теперь от них
требуется не «не бросает», а «страница просмотрена ЦЕЛИКОМ»: виджет ПОСЛЕ
гигантской сущности (в тексте и в значении атрибута) обязан давать `captcha`.
Имена при желании переименовать по смыслу. Новое покрытие:
- `<title>` с гигантской сущностью + статус 200/403/429 и заголовок
  `cf-mitigated` → функция возвращает те же вердикты, что и без сущности;
- `html_to_text` на теле с гигантской сущностью возвращает текст, а не бросает;
- сущности на границе (`&#1114111;`, `&#x10FFFF;`, `&#65;`, `&#0000065;`) не
  портятся: `_title` даёт прежнюю строку;
- `<template/>` (самозакрытый) + виджет + `</template>` на 200 с меткой CF →
  `none`; самозакрытый `<div data-sitekey="k"/>` в тех же условиях → `captcha`.

В `tests/mutation_gate.py`: УДАЛИТЬ мутанта `110` и ДОБАВИТЬ ровно три новых —
снять клипование в `detect_challenge`; снять клипование в `html_to_text`;
убрать переопределение `handle_startendtag`. Остальных мутантов не трогать.
Итоговое число убитых — 113.

`docs/research/04-phase1-verdict.md`: в подраздел «Интерактивный виджет
(M16a-fix)» добавить абзац про лимит в 4300 цифр, про то, что клипование стоит
на всех трёх маршрутах, и про самозакрытый `<template/>`. Прежний абзац,
где сказано, что сущность в атрибуте обрывает разбор, — ПЕРЕПИСАТЬ: это больше
не так.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 в разрешённом Docker-образе на коммите BASE:
все четыре находки воспроизведены дословно (сущность в `<title>` → наружу летит
`ValueError`; `html_to_text` на том же теле → `ValueError`; сущность в атрибуте
перед виджетом → `('none', ('body_cf_challenge_platform',))`; `<template/>` +
виджет → `('captcha', (…,'body_captcha_interactive'))`). Там же проверены
границы клипования и отсутствие входов, роняющих `feed` после клипования.

Предположение: `&#…` — единственная сущность, способная уронить `html.unescape`
в этом окружении. Именованные сущности ограничены 32 символами самой
регуляркой стандартной библиотеки и в `int()` не попадают.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py` (удалить мутанта 110, добавить три новых),
`docs/research/04-phase1-verdict.md`. Docker-прогоны образом из критериев.
Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix3-charrefs-and-template.md` byte-identical: она приезжает
untracked, и без этого критерий чистоты дерева недостижим.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных файлов, фикстуры и `tests/fixtures/README.md`,
другие specs, TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`.
Сеть не нужна: все прогоны `--network none`. Push и merge запрещены.

## Критерии приёмки

- **AC-130.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-131.** Гигантская сущность больше не роняет ни детектор, ни извлечение текста:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); big=\"&#\"+\"9\"*5000+\";\"; nosemi=\"&#\"+\"9\"*5000; hexbig=\"&#x\"+\"f\"*5000+\";\"; [m.detect_challenge(st,h,b) for b in (\"<title>\"+big+\"</title>\", \"<title>\"+nosemi+\"</title>\", \"<title>\"+hexbig+\"</title>\", big, nosemi) for st in (200,403,429) for h in ({}, {\"cf-mitigated\":\"challenge\"})]; [m.html_to_text(b) for b in (\"<p>\"+big+\"</p>\", \"<p>\"+nosemi+\"</p>\", \"<p>\"+hexbig+\"</p>\")]; print(\"ok\")"'`
- **AC-132.** Страница просмотрена целиком: виджет ПОСЛЕ сущности найден:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; big=\"&#\"+\"9\"*5000+\";\"; w=\"<div data-sitekey=k></div>\"; attr=\"<div title=\\\"\"+big+\"\\\"></div>\"; bodies=(cf+attr+w, cf+big+w, cf+w+big, cf+w+attr); assert all(m.detect_challenge(200,{},b)[0]==\"captcha\" for b in bodies), [m.detect_challenge(200,{},b) for b in bodies]; print(\"ok\")"'`
- **AC-133.** Границы клипования не задеты, `<template/>` инертен, самозакрытый виджет виден:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); assert m._title(\"<title>&#65;&#0000065;&#x41;&#1114109;</title>\")==\"AAA\\U0010fffd\", repr(m._title(\"<title>&#65;&#0000065;&#x41;&#1114109;</title>\")); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; t=cf+\"<template/><div data-sitekey=k></div></template>\"; assert m.detect_challenge(200,{},t)[0]==\"none\", m.detect_challenge(200,{},t); sc=cf+\"<div data-sitekey=k/>\"; assert m.detect_challenge(200,{},sc)[0]==\"captcha\", m.detect_challenge(200,{},sc); print(\"ok\")"'`
- **AC-134.** Поведение прежних вех не сдвинуто:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); b=open(\"tests/fixtures/lowendtalk_200_grecaptcha.html\",encoding=\"utf-8\").read(); i=open(\"tests/fixtures/cf_interstitial_200body_403.html\",encoding=\"utf-8\").read(); assert m.detect_challenge(200,{},b)==(\"none\",(\"body_cf_challenge_platform\",\"body_captcha\")); assert m.detect_challenge(403,{},b)[0]==\"access_denied\"; assert m.detect_challenge(403,{},i)[0]==\"suspected\"; assert m.detect_challenge(200,{\"cf-mitigated\":\"interactive\"},i)[0]==\"interactive\"; cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; w=\"<div class=\\\"g-recaptcha\\\" data-sitekey=\\\"k\\\"></div>\"; assert m.detect_challenge(200,{},w)[0]==\"none\"; assert m.detect_challenge(200,{},cf+w)[0]==\"captcha\"; e=cf+\"<script src=https://www.google.com/recaptcha/api.js?onload=cb&render=explicit></script>\"; assert m.detect_challenge(200,{},e)[0]==\"captcha\"; v3=cf+\"<script src=https://www.google.com/recaptcha/api.js?render=KEY></script>\"; assert m.detect_challenge(200,{},v3)[0]==\"none\"; tp=cf+\"<template><div data-sitekey=k></div></template>\"; assert m.detect_challenge(200,{},tp)[0]==\"none\"; print(\"ok\")"'`
- **AC-135.** Мутационные ворота: мутант 110 удалён, три новых убиты, всего 113:
  `bash -c 'set -o pipefail; test -z "$(grep -n \"\\\"110\\\"\" tests/mutation_gate.py)" && n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 113 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-136.** Документы:
  `bash -c 'grep -q "4300" docs/research/04-phase1-verdict.md && grep -q "template/>" docs/research/04-phase1-verdict.md && grep -q "html_to_text" docs/research/04-phase1-verdict.md'`
- **AC-137.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 6ff902fb7746929865c4e8e0db6599d81cbffe4a HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix3-charrefs-and-template.md" && git ls-files --error-unmatch docs/specs/m16a-fix3-charrefs-and-template.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix3b-20260918 --base 6ff902fb7746929865c4e8e0db6599d81cbffe4a --range 6ff902fb7746929865c4e8e0db6599d81cbffe4a..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне:
они правят файлы дерева на месте, два одновременных прогона оставляют
мутантов применёнными (наблюдалось дважды 18.09.2026).

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 8 записей AC-130…AC-137,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"6ff902fb7746929865c4e8e0db6599d81cbffe4a","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-130","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix3b-20260918 --spec /home/user/exec-clones/abg-m16a-fix3b-20260918/docs/specs/m16a-fix3-charrefs-and-template.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется править запрещённые пути или тесты вне трёх названных; клипование
ломает существующую фикстуру или вердикт; после снятия `try/except` находится
вход, роняющий `feed` (приложить его дословно); новый мутант не убивается ни
одним тестом авторского набора; ворота падают на мутанте, не относящемся к
этой вехе. Спеку, AC, BASE и остальных мутантов не менять, rc не выдумывать.
