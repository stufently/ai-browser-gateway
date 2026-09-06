# Веха M3 — детектор челленджа и правило эскалации

| | |
|---|---|
| Репозиторий | `git@gitlab.example.org:9qw/ai-browser-gateway.git` |
| Дата | 06.09.2026 |
| Базовый коммит | `53cf517` «Spec M3 challenge detector» |
| Исполнитель | **Grok** |
| Почему он | Вехи M1 (Grok) и M2 (Codex) чередуются; ревью и перекрёстные мутации по этой вехе пойдут к Codex. |

## Где работать

- Клон: `/home/user/exec-clones/abg-m3-detector`, ветка `m3-detector` от `main`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Эта спека уже в дереве (`docs/specs/m3-challenge-detector.md`, коммит
  `53cf517`) — читай оттуда, редактировать её не нужно. Зависимостей нет:
  стандартная библиотека, тесты `python3 -m unittest` (на хосте Python 3.14.4).
- Ни сети, ни Docker у тебя нет и не понадобится: всё, что нужно для проверки,
  лежит файлами в `tests/fixtures/`.

## Задача и почему

Вся экономия, ради которой мерилась фаза 1, держится на одном решении: **когда
уходить в браузер**. Замеры дали ответ, который противоречит исходной интуиции:

- Браузер окупается **рендерингом**, а не обходом блокировок. На стенде A `curl`
  берёт 5 сценариев из 12, любой браузер — 8, и вся разница это `js`, `spa` и
  `iframe`.
- На боевых целях браузер **не добавил ни одной цели** поверх `curl` с
  браузерными заголовками (incremental 0 у playwright, patchright, camoufox,
  pydoll). Цель `bizprofile.net` за Cloudflare не взял **ни один** из пяти
  движков, включая боевой `cf-fetch` владельца.

Отсюда правило: **эскалация в браузер — по признаку «контента нет», а не по
признаку «нас не пустили»**. Уход в браузер на каждом отказе стоит полсекунды
холодного старта и полутора гигабайт образа, не давая ничего.

Чтобы правило работало, нужно уметь отличать **страницу-заглушку** от
**страницы, которая пришла пустой, потому что контент дорисовывает JS**. Обе
приходят с непустым телом и часто с кодом `200`. Это и есть веха M3.

## Что проверено вживую, а что предположение

Проверено постановщиком 06.09.2026, руками, на настоящих телах из
`tests/fixtures/` (все три — снятые ответы, не выдумка):

| Файл | Байт | Видимого текста | Маркеров челленджа |
|---|---|---|---|
| `cf_interstitial_200body_403.html` | 5829 | **58** | **6 разных** |
| `js_shell_200.html` | 162 | **8** | 0 |
| `real_page_head.html` | 12004 | 1504 | 0 |

🚨 **Порог по длине текста заглушку и JS-шелл НЕ разделяет** (58 против 8 —
у заглушки видимого текста даже больше). Любое правило вида «тело короче N
символов ⇒ блок» объявит блоком каждую SPA. Такого правила в вехе быть не должно.

Что реально нашлось в теле заглушки (`grep`, счётчики точные):

| Маркер | Вхождений |
|---|---|
| `challenges.cloudflare.com` | 5 |
| `cf_chl_opt` | 7 |
| `__cf_chl` | 3 |
| `/cdn-cgi/challenge-platform` | 1 |
| `Just a moment` (в `<title>`) | 1 |
| `noindex,nofollow` | 1 |

**А подстроки `cf-chl-`, которую ищет нынешний `_challenge()` в `probe.py`, в
настоящем теле нет ни одного раза.** Нынешний детектор ловит эту заглушку
исключительно по `just a moment` — то есть по самому хрупкому из признаков.
Это и есть дефект, который веха чинит.

Проверено живым запросом (один запрос, без повторов) к `https://bizprofile.net/`:

```
403
"cf-mitigated":["challenge"]
"server":["cloudflare"]
"server-timing":["chlray;desc=\"…\""]
```

То есть **заголовок `cf-mitigated` в наших данных реально присутствует** и он
авторитетнее любого признака в теле: он приходит от самого Cloudflare, его нельзя
случайно встретить в контенте чужой страницы.

Проверено, что заголовки вообще можно собрать: `curl` в образе `abg-curl:m2` —
версии 7.88.1, `--write-out '%{header_json}'` (нужен ≥ 7.83) отдаёт все заголовки
ответа JSON-объектом. У `curl_cffi` и `primp` есть `response.headers`, у
Playwright/patchright/camoufox — `response.headers` у объекта, который возвращает
`page.goto()`.

**Предположения, помеченные как предположения:**

- У `pydoll` объекта ответа нет: переход делается через CDP `go_to()`, заголовки
  оттуда не достаются. Считаем, что заголовки для него **недоступны**, и это
  должно отличаться в данных от «заголовков не было».
- Интерактивный челлендж (Turnstile-чекбокс, капча) в наших замерах **не
  встретился ни разу**. Правила для него написать нужно, но пометить в коде
  комментарием, что они не проверены на живом теле.
- Челленджи не-Cloudflare (DataDome, PerimeterX, Akamai) у нас не измерены.
  **Их маркеры выдумывать запрещено.** Таблица правил должна быть расширяемой,
  но приезжать в вехе только с тем, что подтверждено файлами.

## Что сделать

### 1. Таблица правил вместо цепочки `if` (`bench/providers/docker/probe.py`)

Заменить `_challenge(body, status)` на явную таблицу правил и функцию

```python
def detect_challenge(status, headers, body) -> tuple[str, tuple[str, ...]]:
    """Возвращает (тип челленджа, имена сработавших правил)."""
```

Требования:

- **Каждое правило именованное.** Возвращается не только вердикт, но и список
  имён сработавших правил — без него отчёт не объяснит, почему страница признана
  заглушкой.
- **Заголовок `cf-mitigated` авторитетнее тела.** Если он есть — вердикт
  `suspected` (или `interactive`, если значение это говорит), независимо от тела.
- **Ни одного правила по длине тела.** Ни прямо, ни косвенно (доля разметки,
  «мало текста», «нет `<p>`»).
- Тип вердикта — значение `ChallengeType` из `bench/models.py`
  (`none`/`suspected`/`javascript_required`/`interactive`/`captcha`/`rate_limited`/`access_denied`),
  строкой. Новых значений не вводить.
- Порядок разрешения конфликтов задан явно и покрыт тестом: заголовок → маркеры
  тела → код ответа. `403` **без** маркеров это `access_denied`, а не `suspected`:
  «нас не пустили» и «нам показали челлендж» — разные вещи, и следующий шаг у них
  разный.
- Сравнение регистронезависимое для текстовых маркеров и точное — для имён
  заголовков (имена приводить к нижнему регистру).

Функция обязана остаться **чистой**: только аргументы, никаких обращений к сети,
файлам и глобальному состоянию. Следующая веха поднимет её в ядро.

### 2. Сбор заголовков ответа (тот же `probe.py`)

- `_result(...)` получает параметр `headers: dict[str, str] | None`;
  `None` означает **«провайдер заголовки не отдаёт»** и должен отличаться в
  выводе от `{}` («заголовков не было»).
- `curl` — через `--write-out '%{header_json}'`. 🚨 Значение содержит переводы
  строк, поэтому в строке `--write-out` оно должно идти **последним**, а разбор
  меты — по ограниченному числу разделителей (`split("\t", N)`), иначе тело
  разъедется.
- `curl_cffi`, `primp` — `response.headers`.
- `playwright`, `patchright`, `camoufox` — `response.headers` объекта, который
  вернул `page.goto()`; если объект `None` (навигация без ответа) — `None`.
- `pydoll` — `None` с комментарием, почему.
- В JSON-выводе пробника появляются поля `headers` и `challenge_markers`
  (список имён правил). Поле `challenge` остаётся и продолжает означать то же.
  **Ни одно существующее поле вывода не удаляется и не меняет смысла** — на них
  держится `parse_output()` вехи M2.

### 3. Правило эскалации (`bench/escalate.py`, новый модуль ядра)

```python
class Step(StrEnum):
    stop = "stop"                    # успех, идти дальше некуда
    browser = "browser"              # поднять браузер: контента нет, блока нет
    change_egress = "change_egress"  # тот же инструмент с другого адреса
    retry_later = "retry_later"      # сетевой/серверный отказ, повтор позже
    give_up = "give_up"              # страницы нет, эскалировать нечего
    human = "human"                  # автоматика не проходит
    investigate = "investigate"      # дефект нашего кода, а не чужой защиты


def next_step(error_type, challenge, *, egress_changed: bool) -> Step: ...
```

Таблица решений — ровно та, что следует из замеров фазы 1; каждая строка обязана
быть покрыта тестом:

| `error_type` | `challenge` | Шаг | На чём основано |
|---|---|---|---|
| `none` | любой | `stop` | успех |
| `content_missing` | `none` | `browser` | стенд A: `js`, `spa`, `iframe` берёт только браузер |
| `content_missing` | любой другой | `change_egress` | `bizprofile.net` не взял ни один из пяти движков |
| `javascript_required` | `none` | `browser` | то же, что `content_missing` |
| `http_403`, `http_429` | любой | `change_egress` | отказ по репутации адреса; тот же образ и отпечаток с другого адреса дают `200` (измерено в `gpt-web-gateway`) |
| `timeout`, `connection_error`, `dns_error`, `tls_error`, `http_5xx` | любой | `retry_later` | отказ сети или сервера: эскалация ничего не меняет |
| `content_mismatch` | любой | `give_up` | `404` и прочее `4xx`: страницы нет |
| `interactive_challenge` | любой | `human` | интерактив автоматикой не проходится |
| `provider_error` | любой | `investigate` | это дефект нашего кода, а не защита чужого сайта |

Плюс сквозное правило: **если `egress_changed=True`, то `change_egress`
превращается в `human`** — второй адрес уже потрачен.

Модуль импортирует только `bench.models`. Ничего не печатает, никуда не ходит.

### 4. Тесты

Новый `tests/test_detect.py` — **на настоящих файлах из `tests/fixtures/`**, а не
на выдуманной разметке:

- заглушка → `suspected`, сработавших правил **не меньше трёх**;
- JS-шелл → `none`, правил ноль;
- настоящая страница → `none`, правил ноль;
- `cf-mitigated: challenge` на теле без единого маркера → `suspected`
  (заголовок авторитетнее);
- тело в 40 символов без маркеров → `none` (длина ничего не решает);
- `403` без маркеров → `access_denied`, а не `suspected`;
- тело настоящей страницы, в котором просто написано слово «captcha» в тексте
  статьи, **не** должно давать `captcha` без второго признака — правило обязано
  быть устойчивее одного случайного слова.

Новый `tests/test_escalate.py` — по одному тесту на строку таблицы плюс правило
`egress_changed`.

`tests/test_probe.py` — дополнить проверкой, что адаптеры прокидывают заголовки
(на поддельных объектах, как уже сделано для pydoll), и что `None` и `{}`
различимы.

Мутации в `tests/mutation_gate.py` — **не меньше шести новых** поверх 32
имеющихся, минимум по одной на: приоритет заголовка над телом; `403` без
маркеров; возврат имён правил (пустой кортеж вместо реального); строку таблицы
`content_missing + suspected` (подмена на `browser`); правило `egress_changed`;
разбор меты `curl` с заголовками.

## Не трогать

- `bench/models.py`, `bench/scenarios.py`, `bench/server/`, `bench/report/`,
  `bench/runner/record.py`, `bench/runner/matrix.py`, `bench/runner/execute.py`,
  `bench/providers/registry.py` — контракты вех M1 и M2. Нужна правка —
  **остановись и доложи**, не меняй молча.
- Существующие 137 тестов и 32 мутации — не удалять и не ослаблять.
- `tests/fixtures/` — файлы только читать. Ни редактировать, ни «причёсывать»,
  ни добавлять к ним выдуманные тела.
- Семь `Dockerfile` в `bench/providers/docker/` — в этой вехе не меняются:
  новый код живёт в уже копируемом `probe.py`.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/`, `bench/targets/`.
- `docs/specs/m3-challenge-detector.md` — уже закоммичена, правкам не подлежит.
- Никаких `.github/workflows/`. Никаких сторонних зависимостей.
- **Никаких выдуманных чисел и маркеров.** Ни одного признака челленджа, которого
  нет в файлах `tests/fixtures/` или в разделе «Что проверено вживую».

## Критерии приёмки

- **AC-301 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -m unittest discover -s tests -t . -q'`

- **AC-302 — мутационный гейт: не меньше 38 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=38 else 1)" && python3 tests/mutation_gate.py'`

- **AC-303 — детектор на настоящих телах.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
read = lambda name: pathlib.Path(\"tests/fixtures\") / name
block, markers = probe.detect_challenge(403, {}, read(\"cf_interstitial_200body_403.html\").read_text())
assert block == \"suspected\", block
assert len(markers) >= 3, markers
for name in (\"js_shell_200.html\", \"real_page_head.html\"):
    verdict, hits = probe.detect_challenge(200, {}, read(name).read_text())
    assert verdict == \"none\", (name, verdict)
    assert hits == (), (name, hits)
"'`

- **AC-304 — заголовок авторитетнее тела, длина не решает ничего.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
verdict, markers = probe.detect_challenge(200, {\"cf-mitigated\": \"challenge\"}, \"<html><body>hello</body></html>\")
assert verdict == \"suspected\", verdict
assert markers, markers
assert probe.detect_challenge(200, {}, \"<html><body>short</body></html>\")[0] == \"none\"
assert probe.detect_challenge(403, {}, \"<html><body>nope</body></html>\")[0] == \"access_denied\"
"'`

- **AC-305 — правило эскалации.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
from bench.models import ChallengeType, FailureReason
from bench.escalate import Step, next_step
call = lambda e, c, changed=False: next_step(e, c, egress_changed=changed)
assert call(FailureReason.content_missing, ChallengeType.none) is Step.browser
assert call(FailureReason.content_missing, ChallengeType.suspected) is Step.change_egress
assert call(FailureReason.content_missing, ChallengeType.suspected, True) is Step.human
assert call(FailureReason.http_403, ChallengeType.none) is Step.change_egress
assert call(FailureReason.timeout, ChallengeType.none) is Step.retry_later
assert call(FailureReason.content_mismatch, ChallengeType.none) is Step.give_up
assert call(FailureReason.provider_error, ChallengeType.none) is Step.investigate
assert call(FailureReason.none, ChallengeType.none) is Step.stop
"'`

- **AC-306 — контракты M1 и M2 не тронуты.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && git diff --quiet 53cf517..HEAD -- bench/models.py bench/scenarios.py bench/server bench/report bench/runner/record.py bench/runner/matrix.py bench/runner/execute.py bench/providers/registry.py bench/providers/docker/Dockerfile.curl bench/providers/docker/Dockerfile.curl_cffi bench/providers/docker/Dockerfile.primp bench/providers/docker/Dockerfile.playwright bench/providers/docker/Dockerfile.patchright bench/providers/docker/Dockerfile.camoufox bench/providers/docker/Dockerfile.pydoll tests/fixtures'`

- **AC-307 — состав работы; длина тела ничего не решает.**
  Проверяется поведением, а не поиском по исходнику: `len(body)` в пробнике
  законно живёт в поле `bytes`, и запрет по тексту убил бы исправный код.
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && git ls-files --error-unmatch docs/specs/m3-challenge-detector.md bench/escalate.py tests/test_detect.py tests/test_escalate.py >/dev/null && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
for body in (\"\", \"x\", \"<html><body>ok</body></html>\", \"<p>y</p>\" * 50000):
    assert probe.detect_challenge(200, {}, body) == (\"none\", ()), len(body)
"'`

- **AC-308 — дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно восемь — по одной на критерий:

```json
{"criteria": [{"id": "AC-301", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

🚨 Строку `command` копируй из спеки **дословно**. В вехе M1 исполнитель
перекавычил её при переносе в отчёт, и критерий упал с `rc=127` на пустом месте
при полностью исправной работе.

## Контракт на невыполнимое

Требование невыполнимо или противоречит контрактам M1/M2 — **остановись и
доложи**. Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест,
правка файлов из «Не трогать».

Отдельно: **не выдумывай маркеры челленджа**. Если кажется, что нужен признак,
которого нет ни в фикстурах, ни в разделе «Что проверено вживую», — это повод
остановиться и спросить, а не дописать по памяти. Выдуманный маркер даёт
зелёный тест и ложный вердикт на живой цели, и найдётся он через месяц.

## Стыки с соседними вехами

Веха обещает следующей: чистую `detect_challenge()`, готовую к подъёму в ядро
шлюза, и `next_step()` как единственное место, где живёт правило эскалации.
Следующая веха (M4) берёт обходные входы (архив с возрастом снимка, RSS, sitemap,
JSON-эндпоинты) полноценным классом провайдеров и добавляет поддержку прокси в
`build_argv()` — то есть делает шаг `change_egress` исполнимым, а не только
названным.
