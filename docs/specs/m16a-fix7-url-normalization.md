# M16a-fix7 — нормализация `src` по стандарту URL

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `6b2e0077753db899722deb314023e6df736067b0` — вершина `m16a-fix6`
(FINAL предыдущей вехи; fix6 в main НЕ влита и сливается вместе с этой).
Клон /home/user/exec-clones/abg-m16a-fix7-20260918, ветка m16a-fix7, origin push DISABLED. Исполнитель — cx.
Реквизит — `docs/specs/m16a-fix6-test-holes.md` (прочитать целиком).

## Зачем

Ревью Codex по M16a-fix6 нашло, что подслучай теста
`test_render_value_preserves_surrounding_spaces` закрепляет НЕВЕРНОЕ поведение.
Координатор проверил утверждение в живом Chrome (его собственный парсер
`new URL(src, base)`, 18.09.2026) и получил более широкую картину:

| `src` в разметке | Chrome | детектор на BASE |
|---|---|---|
| `recaptcha/api.js?render=explicit ` | `render=explicit` | `none` ❌ |
| ` recaptcha/api.js?render=explicit` | путь `/recaptcha/api.js`, `render=explicit` | `none` ❌ |
| `recaptcha/api.js?render=explicit\n` | `render=explicit` | `none` ❌ |
| `recaptcha/api.js?render=exp\tlicit` | `render=explicit` | `none` ❌ |
| `recaptcha/api.js?render= explicit` | `render=" explicit"` | `none` ✅ верно |

Стандарт URL (WHATWG, шаг разбора) предписывает: удалить ведущие и замыкающие
C0-управляющие и пробел из входной строки, а табы, LF и CR — удалить ВЕЗДЕ.
Мы не делаем ни того, ни другого, поэтому четыре из пяти входов дают ложный
`none`: страница с настоящим интерактивным виджетом принимается за контент, и
продукт отдаёт её как результат. Это тот же класс дефекта, ради которого
затевалась M16, только в обратную сторону.

## Задача

1. **`bench/providers/docker/probe.py`, разбор `src` в `InteractiveCaptcha`.**
   Перед отсечением фрагмента нормализовать значение атрибута как это делает
   браузер: удалить все U+0009, U+000A, U+000D в любой позиции, затем снять
   ведущие и замыкающие C0-управляющие (U+0000–U+001F) и пробел (U+0020).
   Порядок важен: сначала удаление, потом обрезка. Пробелы ВНУТРИ значения
   параметра не трогать — они значимы (пятая строка таблицы).
2. **`tests/test_detect.py`.** Подслучай `'explicit '` в
   `test_render_value_preserves_surrounding_spaces` меняет ожидание на
   `("captcha", ("body_cf_challenge_platform", "body_captcha",
   "body_captcha_interactive"))`; подслучай `' explicit'` остаётся `none`.
   Добавить случаи: пробел перед путём; `\n` в конце; `\t` внутри значения;
   `\r` внутри пути — все дают интерактивный вердикт. Оставить хотя бы один
   вход, где значимый пробел внутри значения по-прежнему даёт `none`.
3. **`tests/mutation_gate.py`.** Два новых мутанта: снять удаление
   `[\t\n\r]`; снять обрезку краёв. Каждый обязан убиваться новым тестом.
   Итого в воротах 136.
4. **`docs/research/04-phase1-verdict.md`.** Абзац: почему нормализация нужна
   и по какому правилу; что проверено живым Chrome; что пробел внутри значения
   значим и `render= explicit` остаётся невидимой v3.

## Что проверено вживую, а что предположение

Таблица выше — замер координатора в живом Chrome 18.09.2026 через
`new URL(src, 'https://example.test/')`; колонка «детектор на BASE» — прогон
`detect_challenge` в образе из критериев. Python-разборщик (`urllib.parse`)
для этой проверки НЕ авторитетен: он снимает только ведущие пробелы, а
замыкающие оставляет, то есть браузеру не эквивалентен — на него не опираться.

Предположение: имя и место помощника нормализации — на усмотрение автора.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py`, `docs/research/04-phase1-verdict.md`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix7-url-normalization.md` byte-identical.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных, фикстуры, другие specs, TASKS.md,
CHANGELOG.md, `secrets/**`, `/home/user/services/**`. Сеть не нужна.
Push и merge запрещены.

## Критерии приёмки

- **AC-170.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-171.** Четыре входа таблицы стали интерактивными, пятый остался невидимой v3:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; mk=lambda v: cf+\"<script src=\\\"\"+v+\"\\\"></script>\"; inter=[\"recaptcha/api.js?render=explicit \", \" recaptcha/api.js?render=explicit\", \"recaptcha/api.js?render=explicit\\n\", \"recaptcha/api.js?render=exp\\tlicit\"]; bad=[(v, m.detect_challenge(200,{},mk(v))) for v in inter if m.detect_challenge(200,{},mk(v))[0]!=\"captcha\"]; assert not bad, bad; v3=mk(\"recaptcha/api.js?render= explicit\"); assert m.detect_challenge(200,{},v3)[0]==\"none\", m.detect_challenge(200,{},v3); print(\"ok\")"'`
- **AC-172.** Прежние границы разбора `src` не сдвинуты:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; mk=lambda v: cf+\"<script src=\\\"\"+v+\"\\\"></script>\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js#frag?render=KEY\"))[0]==\"captcha\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=explicit;foo=1\"))[0]==\"none\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?RENDER=KEY\"))[0]==\"captcha\"; assert m.detect_challenge(200,{},mk(\"xrecaptcha/api.js?render=explicit\"))[0]==\"none\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=KEY\"))[0]==\"none\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=explicit\"))[0]==\"captcha\"; print(\"ok\")"'`
- **AC-173.** Мутационные ворота: два новых убиты, всего 136:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 136 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-174.** Документ:
  `bash -c 'grep -q "WHATWG" docs/research/04-phase1-verdict.md && grep -q "render= explicit" docs/research/04-phase1-verdict.md'`
- **AC-175.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 6b2e0077753db899722deb314023e6df736067b0 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix7-url-normalization.md" && git ls-files --error-unmatch docs/specs/m16a-fix7-url-normalization.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix7-20260918 --base 6b2e0077753db899722deb314023e6df736067b0 --range 6b2e0077753db899722deb314023e6df736067b0..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-170…AC-175,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"6b2e0077753db899722deb314023e6df736067b0","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-170","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix7-20260918 --spec /home/user/exec-clones/abg-m16a-fix7-20260918/docs/specs/m16a-fix7-url-normalization.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться, если: нормализация ломает существующий тест или фикстуру
(приложить фактический вердикт); какой-то из входов таблицы после правки даёт
НЕ интерактивный вердикт; новый мутант не убивается; ворота падают на мутанте
не из этой вехи. Правило «пробел внутри значения значим» не нарушать: если
ради зелёных тестов приходится обрезать значение параметра — это ошибка,
остановись.
