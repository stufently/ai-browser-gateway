# M16a-fix5 — девять дыр в тестах детектора и форматтера (только тесты)

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `63e18d7687e907ac8eee0a80939f66cbeee3aaed` — вершина main (M16a-fix…fix4 уже влиты) (FINAL предыдущей вехи; вся цепочка
M16a-fix…fix5 сливается в main одним заходом после этой вехи).
Клон /home/user/exec-clones/abg-m16a-fix5-20260918, ветка m16a-fix5, origin push DISABLED. Исполнитель — cx.
Реквизит — `docs/specs/m16a-fix2-widget-edges.md`,
`docs/specs/m16a-fix3-charrefs-and-template.md` и отчёт независимых мутаций
`/home/user/.cache/abg-coord-20260918/m16a-fix2-mutations/result.md`
(прочитать целиком; witness-файлы лежат рядом в `logs/`).

## Зачем

Независимый мутационный прогон Grok по M16a-fix2 дал 23 kill / 6 survivor /
1 equivalent / 0 invalid. Все пять обязательных откатов убиты — правка держится.
Но шесть мутантов выжили, и все шесть — covered-but-not-asserted: строка
исполняется, поведение отличается от SOURCE на конкретном входе, а такого входа
в авторском наборе нет. По политике проекта выживший мутант — дыра в ТЕСТАХ.

**Код детектора в этой вехе НЕ меняется.** Задача — зафиксировать тестами то
поведение, которое уже есть, чтобы оно перестало быть случайным.

Шесть дыр (вход → вердикт SOURCE, который и надо закрепить):

1. **M05, регистр class-токенов.** `<div class="G-reCAPTCHA"></div>` + метка CF
   на 200 → `none` без `body_captcha_interactive`: сравнение классов
   регистрозависимое.
2. **M12, регистр в источнике парсера.** Парсер кормится `text`, а не `lowered`:
   тот же `G-reCAPTCHA` и `render=EXPLICIT` + CF на 200 → `none`.
3. **M25, регистр значения `render`.** `?render=EXPLICIT` + CF на 200 → `none`:
   интерактивным считается только строчный `explicit`.
4. **M07, наличие против значения `data-sitekey`.** `<div data-sitekey=""></div>`
   и `<div data-sitekey></div>` на 403 → `captcha`: важно НАЛИЧИЕ атрибута.
5. **M09, фрагмент в `src`.** `recaptcha/api.js#frag?render=explicit` и
   `recaptcha/api.js?render=explicit#frag` + CF на 200 → `captcha`: `#` и всё
   после него отрезается до разбора query.
6. **M11, имя параметра целиком.** `?onload=render`, `?hl=render`,
   `?rendering=KEY`, `?foo=renderer` + CF на 200 → `captcha`: параметром
   считается только `render=`, подстрока `render` не в счёт.

Ещё две дыры — из независимого прогона Grok по M16a-fix3
(`/home/user/.cache/abg-coord-20260918/m16a-fix3-mutations/result.md`,
23 kill / 2 survivor / 5 equivalent / 0 invalid; оба выживших воспроизведены
координатором на SOURCE):

7. **M10, завершающая `;` у клипованной ссылки.**
   `_title("<title>&#65;6</title>")` → `A6` и
   `html_to_text("<p>&#65;6</p>")` → `" A6 "`: помощник обязан вернуть `;` на
   место, иначе цифра за ссылкой приклеивается (`&#656` → `ʐ`). В наборе нет
   входа, где сразу после `;` идёт цифра.
8. **M13, ВСЕ вхождения, а не первое.** Тело с ДВУМЯ гигантскими ссылками
   (`"&#"+"9"*5000+";X&#"+"9"*5000+";"`) → `_title` и `html_to_text` дают
   `"\ufffdX\ufffd"`, а `detect_challenge` на `cf + реф + X + реф + виджет`
   (200) → `("captcha", ("body_cf_challenge_platform",
   "body_captcha_interactive"))`. С `count=1` второй реф роняет разбор.

## Задача

Только `tests/test_detect.py`, `tests/mutation_gate.py`,
`tests/test_gateway_format.py` и `tests/mutation_gate_gateway.py`.
Продуктовый код в этой вехе не меняется ни в `bench/**`, ни в `gateway/**`.

Девятая дыра — та же ось `;`, но в продуктовом форматтере: независимый прогон
Grok по M16a-fix4 (14 kill / 1 survivor / 3 equivalent / 0 invalid) оставил в
живых ровно того же мутанта M10. Замерено: `render_content` формата `markdown`
на теле `<p>&#65;6</p>` даёт `A6`, а без переноса `;` — `ʐ`. Закрыть тестом в
`tests/test_gateway_format.py` и мутантом в `tests/mutation_gate_gateway.py`
(итого в воротах шлюза 9).

1. Добавить тесты на все шесть входов выше, каждый — с ожиданием, записанным в
   этой спеке. Проверять и вердикт, и состав меток, а не только вердикт.
2. Добавить в `tests/mutation_gate.py` ровно восемь мутантов, по одному на дыру:
   токены класса через `.lower()`; `feed(lowered)` вместо `feed(text)`;
   `"explicit"` без учёта регистра; `attributes.get("data-sitekey")` вместо
   `"data-sitekey" in attributes`; снять отсечение `#`; `startswith("render=")`
   → `"render" in part`. Каждый обязан убиваться новым тестом.
3. Мутантов, доказанных эквивалентными, НЕ добавлять: M21 из прогона по fix2
   (`decisive_body` → `body_names`) и пять эквивалентов прогона по fix3 (порог
   8→9, 8→4301, `>=`→`>`, сырой `lowered`, клип в `_title` после схлопывания
   пробелов). Про первый: Grok доказал
   эквивалентность (`body_names` непуст ровно тогда, когда непуст
   `decisive_body`, потому что supporting-правила добавляются только под
   охраной `if body_names`).
4. Заодно перенести в КОНЕЦ файла блок `if __name__ == "__main__":
   unittest.main()` из `tests/test_detect.py`: сейчас он стоит посреди файла, и
   прямой запуск `python3 tests/test_detect.py` молча выполняет не все классы.
   Через `unittest discover` разницы нет — это защита от ошибки прогона.

Итоговое число убитых в воротах — 123 (текущее + 8).

## Контракт на невыполнимое

Остановиться, если: какой-то из шести входов на BASE даёт НЕ тот вердикт, что
записан выше (приложить фактический — это значит, что чинить надо код, а не
тесты, и веха меняет смысл); новый мутант не убивается; ворота падают на
мутанте не из этой вехи. Код детектора не трогать ни при каких условиях.

## Что проверено вживую, а что предположение

Все восемь вердиктов выше замерены координатором на SOURCE соответствующей
вехи в образе из критериев; шесть первых — прогон Grok по M16a-fix2
(23 kill / 6 survivor / 1 equivalent), два последних — прогон по M16a-fix3
(23 kill / 2 survivor / 5 equivalent), оба выживших воспроизведены
координатором лично. Ни один из восьми входов не требует правки кода.

Предположение: имена тестов и способ их группировки — на усмотрение автора.

## Разрешения

Правка `tests/test_detect.py`, `tests/mutation_gate.py`,
`tests/test_gateway_format.py`, `tests/mutation_gate_gateway.py`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix5-test-holes.md` byte-identical.

## Не трогать

`bench/**` (включая `probe.py`) и продуктовый код `gateway/**` — они в этой
вехе не меняются ни при каких условиях; правятся только тесты; `gateway/**`, `scripts/**`, `deploy/**`, `tests/**` кроме четырёх
названных файлов, фикстуры, другие specs, TASKS.md, CHANGELOG.md, `secrets/**`,
`/home/user/services/**`. Сеть не нужна. Push и merge запрещены.

## Критерии приёмки

- **AC-150.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-151.** Продуктовый код не изменён ни на байт:
  `bash -c 'git diff --exit-code 63e18d7687e907ac8eee0a80939f66cbeee3aaed HEAD -- bench/ gateway/'`
- **AC-152.** Прямой запуск файла тестов выполняет ВСЕ классы (блок `__main__` в конце):
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import re,sys; s=open(\"tests/test_detect.py\",encoding=\"utf-8\").read(); i=s.index(\"if __name__\"); assert \"class \" not in s[i:], s[i:i+200]; print(\"ok\")"'`
- **AC-153.** Мутационные ворота: восемь новых убиты, всего 123:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 123 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-154.** Ворота шлюза: девять убитых, дерево на месте:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c "killed |") && test "$n" -eq 9 && test -z "$(git status --porcelain -- tests/mutation_gate_gateway.py gateway/format_html.py ":(exclude)report.json")"'`
- **AC-155.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 63e18d7687e907ac8eee0a80939f66cbeee3aaed HEAD -- . ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)tests/test_gateway_format.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/specs/m16a-fix5-test-holes.md" && git ls-files --error-unmatch docs/specs/m16a-fix5-test-holes.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix5-20260918 --base 63e18d7687e907ac8eee0a80939f66cbeee3aaed --range 63e18d7687e907ac8eee0a80939f66cbeee3aaed..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-150…AC-155,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"63e18d7687e907ac8eee0a80939f66cbeee3aaed","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-150","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix5-20260918 --spec /home/user/exec-clones/abg-m16a-fix5-20260918/docs/specs/m16a-fix5-test-holes.md --timeout 3600`.
