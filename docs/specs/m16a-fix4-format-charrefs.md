# M16a-fix4 — гигантские числовые сущности в продуктовом форматтере

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `7878a40a9f7dad207c768af74f39d0f09148b737` — вершина `m16a-fix3`
(FINAL предыдущей вехи; цепочка M16a-fix…fix4 в main ещё НЕ влита и сливается
одним заходом после этой правки).
Клон /home/user/exec-clones/abg-m16a-fix4-20260918, ветка m16a-fix4,
origin push DISABLED. Исполнитель — cx. Реквизит — спека
`docs/specs/m16a-fix3-charrefs-and-template.md` (прочитать целиком: в ней
описан ровно тот же приём для детектора).

## Зачем

Веха M16a-fix3 закрыла лимит `int()` в 4300 цифр на трёх маршрутах
`bench/providers/docker/probe.py`. Ревью Codex по ней и независимая проверка
координатора нашли ЧЕТВЁРТЫЙ маршрут — в продукте, а не в пробнике:

`gateway/format_html.py`, класс `Document(HTMLParser)` создаётся с
`convert_charrefs=True` и в `__init__` сразу зовёт `self.feed(html)` на сыром
теле страницы. `HTMLParser` при этом зовёт `html.unescape`, и десятичная
сущность длиннее 4300 цифр роняет разбор наружу:

```
ValueError: Exceeds the limit (4300 digits) for integer string conversion
```

Замерено координатором на BASE в разрешённом образе, тело
`<title>t</title><p>x &#<5000 девяток>; y</p><a href=/l>L</a>`:

| format | BASE |
|---|---|
| `text` | ok (берётся готовым из outcome) |
| `html` | ok (отдаётся как есть) |
| `markdown` | **ValueError** |
| `links` | **ValueError** |
| `meta` | **ValueError** |

Падение происходит и когда сущность лежит в тексте, и когда в значении
атрибута. `gateway/api_http.py` ловит это общим `except Exception` и отвечает
**HTTP 500 `internal_error`**: враждебная страница превращается в отказ шлюза.

Этот путь открыла именно M16a-fix3. До неё такая страница роняла детектор,
лестница доходила до `ok=False`, а `render_content` на неуспешном исходе
возвращает пустое значение, не доходя до `Document`. После fix3 детект
проходит, `ok=True` — и падает форматтер. То есть в проде дефект проявится
ровно с выкаткой M16, поэтому чинить его надо ДО деплоя M16b.

## Задача

1. **Тот же приём, что в детекторе, в `gateway/format_html.py`.** Модульный
   помощник (имя на усмотрение автора): десятичная числовая ссылка
   `&#<цифры>` с заведомо out-of-range значением заменяется на U+FFFD
   (`"\ufffd"`) ДО подачи разметки в парсер. Правило слово в слово как в
   M16a-fix3:
   - ведущие нули снимаются перед подсчётом длины (лимит CPython считает и их:
     `int("0"*4299 + "65")` уже падает);
   - восемь и более оставшихся цифр → U+FFFD (максимальный кодпоинт
     0x10FFFF = 1114111, семь цифр, больше не бывает);
   - иначе ссылка выписывается обратно с нормализованными цифрами и той же
     завершающей `;`, если она была (`;` в `html._charref` необязательна);
   - **шестнадцатеричные ссылки не трогать**: лимит цифр действует только для
     оснований, не являющихся степенью двойки, `int(s, 16)` не падает никогда,
     а `html.unescape` сам отдаёт U+FFFD на значении вне диапазона.
2. **Точка применения — одна: `Document.__init__` перед `self.feed(html)`.**
   Других вызовов `unescape`/`HTMLParser` в `gateway/**` нет (проверено
   координатором `grep`), поэтому одного места достаточно и второе заводить не
   надо.
3. **Код НЕ импортировать из `bench/providers/docker/probe.py`.** Пробник
   монтируется в контейнеры провайдеров одним файлом (`--mount
   ...target=/opt/abg/probe.py`) и обязан оставаться самодостаточным, а
   `gateway/**` в контейнер провайдера не попадает. Дублирование десятка строк
   здесь осознанное — поставить комментарий с указанием на парный помощник в
   пробнике, чтобы правки шли парой.
4. **Тесты** в `tests/test_gateway_format.py`: все пять форматов переживают
   сущность и в тексте, и в атрибуте, и с `;`, и без; границы не сдвинуты
   (значения ниже замерены координатором на BASE и обязаны сохраниться).
5. **Мутанты** в `tests/mutation_gate_gateway.py`: ровно три новых (снять
   клипование; убрать снятие ведущих нулей; сдвинуть порог с 8 на 7 цифр),
   каждый обязан убиваться новым тестом. Итого в воротах 8.
6. **Документ** `docs/research/04-phase1-verdict.md`: абзац о том, что то же
   правило применяется в продуктовом форматтере, одной фразой про причину
   дублирования.

### Замеренные границы (markdown, `render_content(o,'markdown')`)

| вход в `<p>…</p>` | результат на BASE и после правки |
|---|---|
| `&#65;` | `A` |
| `&#0000065;` | `A` |
| `&#1114109;` | `\U0010fffd` |
| `&#1114112;` | `\ufffd` |
| `&#9999999;` | `\ufffd` (семь цифр, клипование не при чём) |
| `&#x` + 5000 `f` + `;` | `\ufffd` (hex не трогаем) |
| `&#` + 5000 `9` + `;` | **BASE: ValueError**, после правки `\ufffd` |
| `&#` + 5000 `0` + `65;` | **BASE: ValueError**, после правки `A` |

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 на BASE в образе из критериев:
падение `Document` на сущности в тексте и в атрибуте; таблица пяти форматов
выше; таблица границ выше; `except Exception` → 500 в `gateway/api_http.py`;
ранний выход `render_content` при `ok=False`; отсутствие других
`unescape`/`HTMLParser` в `gateway/**`; `tests/mutation_gate_gateway.py`
сейчас даёт `Gateway mutants killed: 5/5`; огромный `Content-Length` в API
падает в `except ValueError` и честно отвечает 400 — это НЕ дефект и чинить
его не надо.

Предположение: имя помощника и место комментария — на усмотрение автора.

## Разрешения

Правка `gateway/format_html.py`, `tests/test_gateway_format.py`,
`tests/mutation_gate_gateway.py`, `docs/research/04-phase1-verdict.md`.
Docker-прогоны образом из критериев. Commit в клоне. Первым коммитом
закоммитить эту спеку `docs/specs/m16a-fix4-format-charrefs.md`
byte-identical: она приезжает untracked, без этого критерий чистоты дерева
недостижим.

## Не трогать

`bench/**` (включая `probe.py` — он уже починен веху назад), `gateway/**`
кроме `format_html.py`, `scripts/**`, `deploy/**`, `tests/**` кроме двух
названных файлов, фикстуры, другие specs, TASKS.md, CHANGELOG.md,
`secrets/**`, `/home/user/services/**`. Сеть не нужна: все прогоны
`--network none`. Push и merge запрещены.

## Критерии приёмки

- **AC-140.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-141.** Все пять форматов переживают гигантскую сущность в тексте и в атрибуте, с `;` и без:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "from bench.escalate import Step; from bench.models import FailureReason as F; from gateway.models import GatewayOutcome; from gateway.format import render_content, MODES; refs=[\"&#\"+\"9\"*5000+\";\", \"&#\"+\"9\"*5000, \"&#\"+\"0\"*5000+\"65;\", \"&#\"+\"0\"*5000+\"65\"]; frags=[r for r in refs]+[\"<a href=/l title=\\\"\"+r+\"\\\">L</a>\" for r in refs]; bodies=[\"<title>t\"+f+\"</title><p>x \"+f+\" y</p><a href=/l>L</a>\" for f in frags]; outs=[GatewayOutcome(True,\"https://a/x\",\"https://a/x\",b,\"x\",\"curl\",None,F.none,Step.stop,(),0) for b in bodies]; [render_content(o,m) for o in outs for m in MODES]; print(\"ok\")"'`
- **AC-142.** Границы форматтера не сдвинуты:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "from bench.escalate import Step; from bench.models import FailureReason as F; from gateway.models import GatewayOutcome; from gateway.format import render_content; md=lambda frag: render_content(GatewayOutcome(True,\"https://a/x\",\"https://a/x\",\"<p>\"+frag+\"</p>\",\"t\",\"curl\",None,F.none,Step.stop,(),0),\"markdown\"); cases=[(\"&#65;\",\"A\"),(\"&#0000065;\",\"A\"),(\"&#1114109;\",\"\\U0010fffd\"),(\"&#1114112;\",\"\\ufffd\"),(\"&#9999999;\",\"\\ufffd\"),(\"&#x\"+\"f\"*5000+\";\",\"\\ufffd\"),(\"&#\"+\"9\"*5000+\";\",\"\\ufffd\"),(\"&#\"+\"0\"*5000+\"65;\",\"A\"),(\"L&#\"+\"9\"*5000+\"R\",\"L\\ufffdR\")]; bad=[(f[:16],md(f),e) for f,e in cases if md(f)!=e]; assert not bad, bad; print(\"ok\")"'`
- **AC-143.** Форматтер и детектор дают один и тот же ответ на одном входе:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; from bench.escalate import Step; from bench.models import FailureReason as F; from gateway.models import GatewayOutcome; from gateway.format import render_content; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); frags=[\"&#\"+\"9\"*5000+\";\", \"&#\"+\"0\"*5000+\"65;\", \"&#1114109;\", \"&#x\"+\"f\"*5000+\";\"]; bad=[]; [bad.append((f[:16], render_content(GatewayOutcome(True,\"https://a/x\",\"https://a/x\",\"<title>\"+f+\"</title>\",\"t\",\"curl\",None,F.none,Step.stop,(),0),\"meta\")[\"title\"], m._title(\"<title>\"+f+\"</title>\"))) for f in frags if render_content(GatewayOutcome(True,\"https://a/x\",\"https://a/x\",\"<title>\"+f+\"</title>\",\"t\",\"curl\",None,F.none,Step.stop,(),0),\"meta\")[\"title\"] != m._title(\"<title>\"+f+\"</title>\")]; assert not bad, bad; print(\"ok\")"'`
- **AC-144.** Мутационные ворота шлюза: три новых мутанта убиты, всего 8, дерево на месте:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c "killed |") && test "$n" -eq 8 && test -z "$(git status --porcelain -- tests/mutation_gate_gateway.py gateway/format_html.py ":(exclude)report.json")"'`
- **AC-145.** Документ:
  `bash -c 'grep -q "format_html" docs/research/04-phase1-verdict.md && grep -q "4300" docs/research/04-phase1-verdict.md'`
- **AC-146.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code 7878a40a9f7dad207c768af74f39d0f09148b737 HEAD -- . ":(exclude)gateway/format_html.py" ":(exclude)tests/test_gateway_format.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-fix4-format-charrefs.md" && git ls-files --error-unmatch docs/specs/m16a-fix4-format-charrefs.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m16a-fix4-20260918 --base 7878a40a9f7dad207c768af74f39d0f09148b737 --range 7878a40a9f7dad207c768af74f39d0f09148b737..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

Мутационные ворота гонять ТОЛЬКО последовательно и только в своём клоне: они
правят файлы дерева на месте, два одновременных прогона оставляют мутантов
применёнными (наблюдалось дважды 18.09.2026).

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-140…AC-146,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"7878a40a9f7dad207c768af74f39d0f09148b737","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-140","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-fix4-20260918 --spec /home/user/exec-clones/abg-m16a-fix4-20260918/docs/specs/m16a-fix4-format-charrefs.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется править запрещённые пути или тесты вне двух названных; клипование
ломает существующий тест форматов или замеренную границу (приложить
фактическое значение — тогда ошибка в спеке, а не в коде); находится ещё один
маршрут в `gateway/**`, роняющий разбор на числовой сущности (приложить его);
новый мутант не убивается; ворота падают на мутанте не из этой вехи. Спеку,
AC, BASE и остальных мутантов не менять, rc не выдумывать.
