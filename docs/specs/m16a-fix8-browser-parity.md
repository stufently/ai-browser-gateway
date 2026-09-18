# M16a-fix8 — четыре расхождения с браузером в разборе виджета

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `dd63f707b50e795ce631ccff66d22f01d2839e3b` — вершина `m16a-fix7` (FINAL предыдущей вехи; fix6 и fix7 в
main НЕ влиты и сольются вместе с этой).
Клон /home/user/exec-clones/abg-m16a-fix8-20260918, ветка m16a-fix8, origin push DISABLED. Исполнитель — cx.
Реквизит — `docs/specs/m16a-fix7-url-normalization.md` (прочитать целиком).

## Зачем

Ревью по M16a-fix7 дало четыре находки; координатор проверил каждую вживую —
в Docker-образе из критериев и в настоящем Chrome (его собственный HTML-парсер
`document.implementation.createHTMLDocument` и `new URL()`), 18.09.2026.

| вход | Chrome | детектор на BASE | чем плохо |
|---|---|---|---|
| `<script src="a.js?render=explicit\x00">` | NUL в значении атрибута заменяется на **U+FFFD** (код 65533), значение не равно `explicit` | NUL срезается краевой обрезкой → `explicit` | **ложная `captcha`**: обычная страница уходит человеку |
| `<div class="g-recaptcha\u00a0foo">` | один токен `g-recaptcha foo`, виджета нет | `str.split()` делит по NBSP → токен `g-recaptcha` найден | **ложная `captcha`** |
| `<div class="g-recaptcha\u000bfoo">` | один токен, виджета нет | то же деление по вертикальной табуляции | **ложная `captcha`** |
| `<script src="recaptcha\api.js?render=explicit">` | обратный слэш = прямой, путь `/recaptcha/api.js`, виджет интерактивен | путь не совпал | пропуск настоящей капчи |
| обрезка краёв `re.sub(r"^[\x00-\x20]+\|[\x00-\x20]+$", …)` | — | 4000/8000/16000 внутренних пробелов → 0,092 / 0,382 / **1,235 с**; `str.strip` на том же входе — 0,000015 с | недоверенная страница жжёт бюджет запроса |

Первые три — тот самый дефект, ради которого затевалась M16 (ложная `captcha`
на честной странице), и породила их правка предыдущей вехи.

## Задача

Ровно в `bench/providers/docker/probe.py`, класс `InteractiveCaptcha`.

1. **NUL в значениях атрибутов.** Перед любой обработкой заменить `\x00` на
   `"\ufffd"` в значениях атрибутов, которыми пользуется виджет-парсер (как
   минимум `src` и `class`) — это ровно то, что делает HTML-токенайзер
   браузера. После этого краевая обрезка NUL уже не встретит.
2. **Токены `class` — только ASCII-пробелы.** Делить значение по
   `[ \t\n\f\r]+` (пробел, таб, LF, FF, CR), а не `str.split()`: последний
   режет и по NBSP, и по вертикальной табуляции, чего браузер не делает.
   Пустые токены отбрасывать.
3. **Обратный слэш в `src`.** Заменить `\\` на `/` при нормализации: у схем
   http/https стандарт URL считает их эквивалентными.
4. **Линейная обрезка краёв.** Заменить регулярку на `str.strip` по набору
   символов `chr(0)…chr(0x20)` (или эквивалент без возврата), чтобы снять
   квадратичность. Удаление `\t\n\r` по всей строке оставить как есть.

Порядок: NUL → U+FFFD, затем удаление `\t\n\r`, затем замена `\\` на `/`,
затем обрезка краёв, затем прежний разбор фрагмента и query.

5. **Тесты `tests/test_detect.py`.**
   - В `test_script_src_trims_c0_and_space_at_edges` кодпоинт `0x00` больше НЕ
     даёт `captcha`: вынести его в отдельное ожидание `none` (значение
     становится `explicit\ufffd`), диапазон обрезки оставить `0x01…0x20`.
   - Новые случаи: `class` с NBSP и с вертикальной табуляцией на 403 → вердикт
     БЕЗ `body_captcha_interactive`; `class` с табом/LF/FF/CR → виджет найден;
     `src` с обратным слэшем → интерактивный виджет.
   - Регрессия по времени: тело со скриптом, у которого в значении `render`
     32000 пробелов подряд, разбирается быстрее 2 секунд (на BASE — около 5 с,
     после правки — микросекунды; порог с запасом в обе стороны).
6. **Мутанты `tests/mutation_gate.py`**: четыре новых, по одному на пункт 1–4.
   Каждый обязан убиваться своим новым тестом. Итого в воротах 140.
7. **Документ** `docs/research/04-phase1-verdict.md`: абзац про то, что
   детектор повторяет разбор браузера в четырёх местах, и почему (все четыре
   расхождения давали ложный вердикт), со ссылкой на замеры.

## Что проверено вживую, а что предположение

Таблица выше — замеры координатора 18.09.2026: колонка Chrome снята в живом
браузере (`createHTMLDocument` + `classList` + `new URL`), колонка «детектор на
BASE» и тайминги — прогоны в образе из критериев. Отдельно проверено, что
сущности в атрибутах (`&#32;`) Python-парсер раскрывает так же, как браузер,
поэтому отдельной обработки они не требуют.

Предположение: имена помощников и их размещение — на усмотрение автора.

## Разрешения

Правка `bench/providers/docker/probe.py`, `tests/test_detect.py`,
`tests/mutation_gate.py`, `docs/research/04-phase1-verdict.md`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m16a-fix8-browser-parity.md` byte-identical.

## Не трогать

`gateway/**`, `bench/**` кроме названного файла, `scripts/**`, `deploy/**`,
`tests/**` кроме двух названных, фикстуры, другие specs, TASKS.md,
CHANGELOG.md, `secrets/**`, `/home/user/services/**`. Сеть не нужна.
Push и merge запрещены.

## Критерии приёмки

- **AC-180.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-181.** Четыре расхождения закрыты:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; nul=cf+\"<script src=\\\"a/recaptcha/api.js?render=explicit\\x00\\\"></script>\"; assert m.detect_challenge(200,{},nul)[0]==\"none\", m.detect_challenge(200,{},nul); nbsp=\"<div class=\\\"g-recaptcha\\u00a0foo\\\"></div>\"; vt=\"<div class=\\\"g-recaptcha\\u000bfoo\\\"></div>\"; assert m.detect_challenge(403,{},nbsp)==(\"access_denied\",(\"status_403\",)), m.detect_challenge(403,{},nbsp); assert m.detect_challenge(403,{},vt)==(\"access_denied\",(\"status_403\",)), m.detect_challenge(403,{},vt); bs=cf+\"<script src=\\\"recaptcha\\\\api.js?render=explicit\\\"></script>\"; assert m.detect_challenge(200,{},bs)[0]==\"captcha\", m.detect_challenge(200,{},bs); print(\"ok\")"'`
- **AC-182.** Обрезка линейная: 32000 пробелов разбираются быстрее двух секунд:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); import time; cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; body=cf+\"<script src=\\\"recaptcha/api.js?render=\"+\" \"*32000+\"KEY\\\"></script>\"; t=time.perf_counter(); m.detect_challenge(200,{},body); d=time.perf_counter()-t; assert d < 2.0, d; print(\"ok\", round(d,4))"'`
- **AC-183.** Поведение прежних вех не сдвинуто:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); cf=\"<script src=/cdn-cgi/challenge-platform/scripts/jsd/main.js></script>\"; mk=lambda v: cf+\"<script src=\\\"\"+v+\"\\\"></script>\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=explicit \"))[0]==\"captcha\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render= explicit\"))[0]==\"none\"; assert m.detect_challenge(200,{},mk(\"recaptcha/api.js?render=exp\\tlicit\"))[0]==\"captcha\"; assert m.detect_challenge(200,{},mk(\"xrecaptcha/api.js?render=explicit\"))[0]==\"none\"; assert m.detect_challenge(403,{},\"<span data-sitekey=k></span>\")==(\"captcha\",(\"body_captcha_interactive\",)); assert m.detect_challenge(403,{},\"<div class></div>\")==(\"access_denied\",(\"status_403\",)); assert m.detect_challenge(200,{},cf+\"<div class=\\\"g-recaptcha\\tfoo\\\"></div>\")[0]==\"captcha\"; print(\"ok\")"'`
- **AC-184.** Мутационные ворота: четыре новых убиты, всего 140:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py | grep -c убит) && test "$n" -eq 140 && test -z "$(git status --porcelain -- tests/mutation_gate.py bench/providers/docker/probe.py ":(exclude)report.json")"'`
- **AC-185.** Документ:
  `bash -c 'grep -q "U+FFFD" docs/research/04-phase1-verdict.md && grep -q "NBSP" docs/research/04-phase1-verdict.md'`
- **AC-186.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code dd63f707b50e795ce631ccff66d22f01d2839e3b HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix8-browser-parity.md" && git ls-files --error-unmatch docs/specs/m16a-fix8-browser-parity.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix8-20260918 --base dd63f707b50e795ce631ccff66d22f01d2839e3b --range dd63f707b50e795ce631ccff66d22f01d2839e3b..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне: они
правят файлы дерева на месте, одновременный второй прогон оставляет мутантов
применёнными (наблюдалось трижды 18.09.2026).

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-180…AC-186,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"dd63f707b50e795ce631ccff66d22f01d2839e3b","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-180","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix8-20260918 --spec /home/user/exec-clones/abg-m16a-fix8-20260918/docs/specs/m16a-fix8-browser-parity.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с уликами в `report-blocked.md`, если: правка ломает существующий
тест или фикстуру (приложить фактический вердикт); какой-то вход таблицы после
правки даёт не тот вердикт; порог времени в AC-182 не достигается даже после
перехода на `str.strip` (приложить замер); новый мутант не убивается. Пробел
ВНУТРИ значения параметра значимым быть не перестаёт: если ради зелёных тестов
приходится обрезать значение — это ошибка, остановись.
