# M16a-fix6 — тринадцать дыр в тестах разбора виджета (только тесты)

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `8eb45822d7bdba0c9cc30c4dfde0597c2df4362e` — вершина main (M16 закрыта и выкачена).
Клон /home/user/exec-clones/abg-m16a-fix6-20260918, ветка m16a-fix6, origin push DISABLED. Исполнитель — cx.
Реквизит — `docs/specs/m16a-fix5-test-holes.md` и отчёт независимых мутаций
`/home/user/.cache/abg-coord-20260918/m16a-fix5-mutations/result.md`
(прочитать целиком; witness-файлы в `logs/`).

## Зачем

Независимый прогон Grok по M16a-fix5 дал 9 kill / 13 survivor / 1 equivalent /
0 invalid. Контрольный мутант убит — мутации ложатся. Тринадцать выживших —
covered-but-not-asserted: строка исполняется, поведение отличается от SOURCE на
конкретном входе, а такого входа в наборе нет.

**Продуктовый код в этой вехе НЕ меняется** ни в `bench/providers/docker/probe.py`,
ни в `gateway/format_html.py`. Задача — закрепить тестами уже существующее
поведение. Все тринадцать вердиктов ниже ЗАМЕРЕНЫ КООРДИНАТОРОМ на BASE в
образе из критериев; если хоть один не совпал — остановись по контракту.

Дальше `CF` = `<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>`,
статус 200 и пустые заголовки, если не сказано иное.
`IA` = `("captcha", ("body_cf_challenge_platform", "body_captcha", "body_captcha_interactive"))`,
`NA` = `("none", ("body_cf_challenge_platform", "body_captcha"))`.

### Разбор `src` у `<script>`

1. **Фрагмент отрезается вместе с query (M05).**
   `CF + <script src="recaptcha/api.js#frag?render=KEY"></script>` → `IA`.
   `render=` в такой строке НЕ виден (он за `#`), поэтому скрипт считается
   интерактивным. Существующий тест даёт только `render=explicit` и не
   различает порядок отсечения.
2. **Разделитель query — только `&` (M02).**
   `CF + <script src="recaptcha/api.js?render=explicit;foo=1"></script>` → `NA`:
   это ОДИН параметр со значением `explicit;foo=1`, а не `explicit`.
3. **Имя параметра регистрозависимо (M03).**
   `CF + <script src="recaptcha/api.js?RENDER=KEY"></script>` → `IA`:
   `RENDER=` не считается параметром `render=`, значит «render= нет».
4. **Значение не обрезается по краям (M04).**
   `CF + <script src="recaptcha/api.js?render= explicit"></script>` → `NA`
   и то же для `?render=explicit ` (пробел справа).
5. **Имя пути точное, не суффикс (M08).**
   `CF + <script src="xrecaptcha/api.js?render=explicit"></script>` → `NA`;
   то же для `not-recaptcha/api.js` и `grecaptcha/api.js`.
6. **`src` разбирается только у `script` (M09).**
   `CF + <iframe src="recaptcha/api.js?render=explicit"></iframe>` → `NA`.

### Атрибуты и классы

7. **`data-sitekey` на любом теге (M06).** На 403 каждый из
   `<span data-sitekey="k"></span>`, `<input data-sitekey="k">`,
   `<button data-sitekey="k"></button>`, `<p …>`, `<section …>`, `<img …>`
   → `("captcha", ("body_captcha_interactive",))`.
8. **Class-токены делятся по ЛЮБОМУ пробельному символу (M07).**
   `CF + <div class="g-recaptcha\tfoo"></div>` → `IA`; то же с `\n` и `\r`.
9. **Boolean-атрибут `class` не роняет разбор (M18).**
   `<div class></div>` на 403 → `("access_denied", ("status_403",))`.
   Без охраны `or ""` разбор падает с `AttributeError` — тест обязан ловить
   именно вердикт, а не отсутствие исключения.

### Края клипования числовых ссылок (оба файла)

10. **`&` без `#` не трогается (M13).** `_title("<title>&65;6</title>")`
    → `"&65;6"`; `html_to_text("<p>&65;</p>")` → `" &65; "`.
11. **Пустой `&#;` не трогается (M14).** `_title("<title>L&#;R</title>")`
    → `"L&#;R"`; `html_to_text("<p>&#;</p>")` → `" &#; "`.
12. **То же в форматтере (M20).** `render_content(…, "markdown")` на
    `<p>&65;6</p>` → `"\\&65;6"`, на `<p>&65;</p>` → `"\\&65;"`.
13. **Пустой `&#;` в форматтере.** `<p>&#;</p>` → `"\\&\\#;"`,
    `<p>L&#;R</p>` → `"L\\&\\#;R"`.
    (Обратные слэши — работа `escaped()` в markdown, это не опечатка.)

## Задача

Только `tests/test_detect.py`, `tests/mutation_gate.py`,
`tests/test_gateway_format.py`, `tests/mutation_gate_gateway.py`.

1. Тест на каждую из тринадцати позиций, с ожиданием ровно как записано выше.
   Проверять и вердикт, и состав меток.
2. По одному мутанту на позицию: одиннадцать в `tests/mutation_gate.py`
   (позиции 1–11) и два в `tests/mutation_gate_gateway.py` (позиции 12–13).
   Каждый обязан убиваться своим новым тестом.
3. Эквивалентного мутанта прогона (M?? из отчёта, помечен equivalent) НЕ
   добавлять.

Итоговые числа в воротах — 134 и 11.

## Контракт на невыполнимое

Остановиться, если: хоть один из тринадцати входов на BASE даёт НЕ тот вердикт,
что записан (приложить фактический — значит, ошибка в спеке, и веха меняет
смысл); новый мутант не убивается; ворота падают на мутанте не из этой вехи.
Продуктовый код не трогать ни при каких условиях.

## Что проверено вживую, а что предположение

Все тринадцать вердиктов замерены координатором на BASE 18.09.2026 в образе из
критериев; отчёт Grok использован как источник осей, но ожидания в спеке —
собственные замеры. Текущие ворота: 123 мутанта детектора и 9 шлюза (прогон
координатора на FINAL M16a-fix5).

Предположение: имена тестов и их группировка — на усмотрение автора.

## Разрешения

Правка `tests/test_detect.py`, `tests/mutation_gate.py`,
`tests/test_gateway_format.py`, `tests/mutation_gate_gateway.py`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix6-test-holes.md` byte-identical.

## Не трогать

`bench/**` и `gateway/**` (продуктовый код не меняется ни при каких условиях),
`scripts/**`, `deploy/**`, `tests/**` кроме четырёх названных файлов, фикстуры,
другие specs, TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`.
Сеть не нужна. Push и merge запрещены.

## Критерии приёмки

- **AC-160.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-161.** Продуктовый код не изменён ни на байт:
  `bash -c 'git diff --exit-code 8eb45822d7bdba0c9cc30c4dfde0597c2df4362e HEAD -- bench/ gateway/'`
- **AC-162.** Ворота детектора: одиннадцать новых убиты, всего 134:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 134 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-163.** Ворота шлюза: два новых убиты, всего 11:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c "killed |") && test "$n" -eq 11 && test -z "$(git status --porcelain -- tests/mutation_gate_gateway.py gateway/format_html.py ":(exclude)report.json")"'`
- **AC-164.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 8eb45822d7bdba0c9cc30c4dfde0597c2df4362e HEAD -- . ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)tests/test_gateway_format.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/specs/m16a-fix6-test-holes.md" && git ls-files --error-unmatch docs/specs/m16a-fix6-test-holes.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix6-20260918 --base 8eb45822d7bdba0c9cc30c4dfde0597c2df4362e --range 8eb45822d7bdba0c9cc30c4dfde0597c2df4362e..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-160…AC-164,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"8eb45822d7bdba0c9cc30c4dfde0597c2df4362e","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-160","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix6-20260918 --spec /home/user/exec-clones/abg-m16a-fix6-20260918/docs/specs/m16a-fix6-test-holes.md --timeout 3600`.
