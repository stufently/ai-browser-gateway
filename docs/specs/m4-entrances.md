# Веха M4 — обходные входы и состояние «не измерено»

| | |
|---|---|
| Репозиторий | `git@gitlab.example.org:9qw/ai-browser-gateway.git` |
| Дата | 07.09.2026 |
| База | клон снимается с `main`; **критерии сравнивают `main..HEAD`**, поэтому ветку `main` в клоне не двигать |
| Исполнитель | **Codex** |
| Почему он | M3 писал Grok; ревью и перекрёстные мутации по этой вехе пойдут к Grok. |

## Где работать

- Клон: `/home/user/exec-clones/abg-m4-entrances`, ветка `m4-entrances` от `main`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Спека уже в дереве (`docs/specs/m4-entrances.md`), редактировать её не нужно.
- Зависимостей нет: стандартная библиотека, `python3 -m unittest`.
- Ни сети, ни Docker у тебя нет. Всё, что нужно для проверки, — фикстуры и
  поддельные объекты, как в вехах M2 и M3.

## Почему эта веха, а не прокси

Координатор просил «обходные входы и прокси» одной вехой. Режу пополам по
правилу «одна веха на прогон»: прокси уезжают в M5 и приедут на готовое
состояние «не измерено», которое вводится здесь. Ничего не теряется — кредов
GoldProxy всё равно ещё нет.

Что говорят замеры фазы 1 (`docs/research/03-stand-b-results.md`):

- **Обходной вход берёт цель, которую не берёт ни один движок.** `bizprofile.net`
  не взяли ни `curl`, ни playwright+stealth, ни patchright, ни боевой `cf-fetch`
  владельца. Wayback отдал её снимком возрастом **3,9 часа**, статус 200, с
  настоящим тайтлом.
- **Браузер не добавил ни одной цели** поверх `curl` с браузерными заголовками.
  То есть incremental даёт именно этот класс, а не рендеринг.
- **Возраст снимка расходится на три порядка** — 3,6 часа у `example.com`, 17 дней
  у LowEndTalk, 115 дней у магазина hqd, а у SPA-страницы и Instagram снимка нет
  вовсе. Поэтому вход обязан возвращать **возраст контента вместе с контентом**:
  для «изменилось ли содержимое» четыре часа годятся, для цены товара нет.

## Что проверено вживую, а что предположение

Проверено постановщиком 07.09.2026, по одному запросу на источник:

1. **API доступности Wayback** — `https://archive.org/wayback/available?url=<цель>`:
   ```json
   {"url": "bizprofile.net", "archived_snapshots": {"closest": {
      "status": "200", "available": true,
      "url": "http://web.archive.org/web/20260906171542/https://www.bizprofile.net/",
      "timestamp": "20260906171542"}}}
   ```
   🚨 **Когда снимка нет, ответ всё равно `200`, а `archived_snapshots` — пустой
   объект `{}`.** На этом уже обожглись 06.09.2026: проверка «код 200 ⇒ снимок
   есть» объявила снимки у всех шести целей, тогда как у двух их не было. Снимок
   считается найденным ТОЛЬКО по непустому `archived_snapshots.closest`.
   `timestamp` — `YYYYMMDDHHMMSS` в UTC.
2. **RSS LowEndTalk** — `https://lowendtalk.com/categories/offers/feed.rss`:
   `200`, 777 448 байт, 100 элементов `<item>`, `<title>` канала —
   `Offers — LowEndTalk`. Это ровно строка `expect` цели `cf-lowendtalk`, которую
   голый `curl` не берёт (`403`). То есть вход измеримо выигрывает клетку.
3. `Дата в RSS` — `<pubDate>Mon, 07 Sep 2026 01:43:20 +0000</pubDate>`, формат
   RFC 822/2822, разбирается `email.utils.parsedate_to_datetime` из стандартной
   библиотеки.

Предположения, помеченные как предположения:

- У остальных целей RSS-ленты **не искали**. Отсутствие ленты в конфиге не
  значит, что её нет, — значит, что мы её не мерили. Это и есть повод для
  состояния «не измерено», а не для нуля.
- Свежесть снимка Wayback меняется от прогона к прогону; числа выше — момент
  замера, а не свойство цели.

## Что сделать

### 1. Состояние «не измерено» — отдельное и явное

В `bench/models.py` добавить **одно** значение: `FailureReason.not_measured`.

Смысл: прогон **не состоялся** по причине вне провайдера — нет настроенного
входа, нет кредов, источник не сконфигурирован. Это не отказ и не успех.

🚨 **«Не измерено» обязано быть состоянием, а не отсутствием строки.** Клетку
нельзя молча пропустить: раннер обязан положить запись со статусом
`not_measured`. Иначе через месяц «замерили, эффекта нет» станет неотличимо от
«так и не замерили», и вывод фазы 1 будет опираться на пустоту, которую примут за
ноль.

В `bench/report/coverage.py` — правило подсчёта:

- запись с `not_measured` **не попадает в числитель** (успехом не является;
  это уже так, потому что `success=False`);
- клетка, у которой **все** записи `not_measured`, **не попадает в знаменатель**
  `total_cells`: мерить её не пытались, и включать её в долю нечестно;
- клетка, у которой хоть одна запись измерена, в знаменателе остаётся.

### 2. Обходные входы как класс провайдеров

В `bench/providers/registry.py` — два провайдера `kind='entrance'`, tier 0:
`wayback` (уже объявлен, реализации не было) и новый `rss`.

**`wayback`** — самодостаточен, конфигурации не требует:

1. `GET https://archive.org/wayback/available?url=<цель>`;
2. пустой `archived_snapshots` ⇒ отказ `content_missing` (снимка нет — это
   настоящий отказ, а не «не измерено»);
3. иначе скачать `closest.url` и вернуть тело;
4. вернуть **возраст снимка в часах** из `timestamp` относительно момента
   прогона.

Разбор ответа выносится в чистую функцию с точной сигнатурой — на неё смотрит
критерий AC-403:

```python
def parse_wayback(payload: dict) -> tuple[str, str] | None:
    """(url снимка, timestamp) либо None, когда снимка нет."""
```

`None` возвращается ровно тогда, когда `archived_snapshots` пуст или в нём нет
`closest`; на код ответа функция не смотрит вовсе, потому что он всегда `200`.

**`rss`** — требует настроенного адреса ленты у цели. Нет адреса ⇒
`not_measured`, а не отказ. Тело для поиска sentinel — сам XML ленты; возраст —
из самого свежего `<pubDate>`, если он есть, иначе возраст неизвестен (`null`,
не ноль).

### 3. Адрес входа приезжает из цели

`bench/targets/targets.toml` — у цели появляется необязательная таблица:

```toml
[target.entrances]
rss = "https://lowendtalk.com/categories/offers/feed.rss"
```

Заполнить **только** для `cf-lowendtalk` — это единственная лента, проверенная
живым запросом. Остальным целям ленты не выдумывать.

`bench/cli.py` кладёт это в ячейку (`cells[name]['entrances']`), а
`bench/runner/execute.py` для провайдера `kind='entrance'`:

- берёт `entrances[<имя провайдера>]` как URL, если он есть;
- если провайдер требует адрес и адреса нет — **записывает `not_measured` и
  контейнер не запускает**;
- `wayback` адреса не требует и работает от URL цели.

Сценарии стенда A обходных входов не имеют: у ячейки `scenario:*` таблицы
`entrances` нет, и любой провайдер-вход даёт там `not_measured`.

### 4. Возраст контента доезжает до записи

`bench/runner/record.py` — **одно** новое поле `entrance_age_hours: float | None`.
`None` означает «возраст неизвестен» и обязан отличаться от `0.0` («контент
свежий»). Поле проходит через JSONL в обе стороны с валидацией, как остальные.

Отчёт (`bench/report/build.py`) показывает медианный возраст по провайдеру-входу
и строку «не измерено» там, где записи `not_measured`; число из «не измерено» не
получается никогда.

### 5. Образы

Два новых `Dockerfile` в `bench/providers/docker/` (`Dockerfile.wayback`,
`Dockerfile.rss`) по образцу `Dockerfile.curl`: `python:3.14-slim`, только
стандартная библиотека, `ENV ABG_PROVIDER=<имя>`, `COPY probe.py`. Никаких
сторонних пакетов: `urllib` и `xml.etree` из стандартной библиотеки достаточно.

### 6. Тесты

- Разбор ответа Wayback: непустой снимок, **пустой `archived_snapshots` при коде
  200**, кривой JSON, возраст из `timestamp`.
- Разбор RSS: sentinel в теле ленты, возраст из `pubDate`, лента без `pubDate`
  (возраст `None`, не ноль).
- `execute_plan`: провайдер-вход без настроенного адреса даёт запись
  `not_measured` и **ни одного запуска контейнера** (поддельный `Launcher`
  обязан остаться без вызовов).
- `coverage`: клетка, где все записи `not_measured`, выпадает из знаменателя;
  клетка с одной измеренной записью — остаётся. 🚨 Набор в тесте обязан быть
  **заведомо непустым**: проверка «доля успехов ≥ X» на пустом множестве
  проходит и не доказывает ничего.
- `record`: `None` и `0.0` в `entrance_age_hours` различимы после JSONL.

Мутации в `tests/mutation_gate.py` — **не меньше восьми новых** поверх 55,
минимум по одной на: снимок ищется по коду ответа, а не по `archived_snapshots`;
`not_measured` попал в знаменатель; отсутствие адреса даёт отказ вместо
`not_measured`; провайдер-вход без адреса всё-таки запускается; `None` возраста
подменён нулём; возраст считается от неверного поля.

## Не трогать

- `bench/scenarios.py`, `bench/server/`, `bench/escalate.py`,
  `bench/providers/docker/probe.py` в части детектора челленджа
  (`detect_challenge`, `RULE_PROVENANCE`, `_decisive_title`, таблицы правил) —
  это контракты вех M1–M3.
- Существующие 196 тестов и 55 мутаций — не удалять и не ослаблять.
- `bench/models.py` — **разрешено ровно одно изменение**: добавить
  `FailureReason.not_measured`. Ничего больше.
- `bench/runner/record.py` — **разрешено ровно одно изменение**: добавить поле
  `entrance_age_hours`. Порядок и смысл остальных полей сохраняются.
- `bench/report/coverage.py` — **разрешено ровно одно изменение**: правило
  знаменателя из пункта 1.
- `tests/fixtures/` — только читать.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/` — **не трогать
  вообще**. Журнал и чейнджлог пишет координатор. В прошлой вехе исполнитель
  правил `TASKS.md` от устаревшей копии, и это молча откатило бы чужую работу.
- Ветку `main` в клоне не переключать и не двигать: от неё считают критерии.
- Никаких `.github/workflows/`. Никаких сторонних зависимостей.
- **Никаких выдуманных адресов лент, целей и чисел.** В конфиг попадает только
  проверенная лента LowEndTalk.

## Критерии приёмки

- **AC-401 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -m unittest discover -s tests -t . -q'`

- **AC-402 — мутационный гейт: не меньше 63 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=63 else 1)" && python3 tests/mutation_gate.py'`

- **AC-403 — снимок Wayback ищется по содержимому ответа, а не по коду.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
empty = probe.parse_wayback({\"url\": \"x\", \"archived_snapshots\": {}})
assert empty is None, empty
found = probe.parse_wayback({\"url\": \"x\", \"archived_snapshots\": {\"closest\": {
    \"status\": \"200\", \"available\": True, \"timestamp\": \"20260906171542\",
    \"url\": \"http://web.archive.org/web/20260906171542/https://www.bizprofile.net/\"}}})
assert found is not None and found[0].endswith(\"bizprofile.net/\"), found
"'`

- **AC-404 — вход без настроенного адреса даёт «не измерено» и не запускает контейнер.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
from bench.models import FailureReason
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
from bench.runner.execute import execute_plan
class Dead:
    def __init__(self): self.calls = []
    def run(self, argv, timeout): self.calls.append(argv); raise AssertionError(\"must not launch\")
cells = {\"target:x\": {\"url\": \"https://example.invalid/\", \"sentinel\": \"S\"}}
plan = build_plan([by_name(\"rss\")], cells, cold=1, warm=0)
launcher = Dead()
records = execute_plan(plan, launcher=launcher, cells=cells, env={})
assert launcher.calls == [], launcher.calls
assert len(records) == 1 and records[0].success is False, records
assert records[0].error_type is FailureReason.not_measured, records[0].error_type
"'`

- **AC-405 — «не измерено» не попадает ни в числитель, ни в знаменатель.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
from bench.models import FailureReason
from bench.report.coverage import incremental
from tests.m4_helpers import record
rows = incremental([
    record(\"curl\", \"target:a\", success=True),
    record(\"rss\", \"target:a\", success=False, error_type=FailureReason.not_measured),
    record(\"rss\", \"target:b\", success=False, error_type=FailureReason.not_measured),
], order=[\"curl\", \"rss\"])
by = {row.provider: row for row in rows}
assert by[\"curl\"].total_cells == 1, by[\"curl\"]
assert by[\"curl\"].solved == 1 and by[\"rss\"].solved == 0, by
"'`

- **AC-406 — неизвестный возраст отличается от нулевого.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
from bench.runner.record import from_jsonl_line, to_jsonl_line
from tests.m4_helpers import record
def roundtrip(age):
    return from_jsonl_line(to_jsonl_line(record(\"wayback\", \"target:a\", success=True, entrance_age_hours=age))).entrance_age_hours
assert roundtrip(None) is None, roundtrip(None)
assert roundtrip(0.0) == 0.0, roundtrip(0.0)
assert roundtrip(3.9) == 3.9, roundtrip(3.9)
"'`

- **AC-407 — лента LowEndTalk на месте, чужих лент не выдумано.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
import tomllib
targets = tomllib.load(open(\"bench/targets/targets.toml\", \"rb\"))[\"target\"]
feeds = {t[\"id\"]: t.get(\"entrances\", {}).get(\"rss\") for t in targets}
assert feeds.get(\"cf-lowendtalk\") == \"https://lowendtalk.com/categories/offers/feed.rss\", feeds
assert [k for k, v in feeds.items() if v and k != \"cf-lowendtalk\"] == [], feeds
"'`

- **AC-408 — запрещённые файлы не тронуты, а `FailureReason` вырос ровно на одно значение.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && git diff --quiet main..HEAD -- bench/scenarios.py bench/server bench/escalate.py README.md TASKS.md CHANGELOG.md docs/research && python3 -c "
from bench.models import FailureReason
before = {\"none\", \"dns_error\", \"timeout\", \"connection_error\", \"tls_error\",
          \"http_403\", \"http_429\", \"http_5xx\", \"javascript_required\",
          \"challenge_suspected\", \"interactive_challenge\", \"content_missing\",
          \"content_mismatch\", \"provider_error\"}
now = {member.value for member in FailureReason}
assert now - before == {\"not_measured\"}, now - before
assert before - now == set(), before - now
"'`

- **AC-409 — состав работы.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && git ls-files --error-unmatch bench/providers/docker/Dockerfile.wayback bench/providers/docker/Dockerfile.rss tests/m4_helpers.py >/dev/null'`

- **AC-410 — дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно десять — по одной на критерий:

```json
{"criteria": [{"id": "AC-401", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

🚨 Строку `command` копируй из спеки **дословно**: в вехе M1 исполнитель
перекавычил её при переносе, и критерий упал с `rc=127` при исправной работе.

Критерии AC-405 и AC-406 опираются на `tests/m4_helpers.py` — маленький модуль с
функцией `record(...)`, которая собирает `RunRecord` с разумными умолчаниями.
Его пишешь ты; это часть вехи, а не постановки.

## Контракт на невыполнимое

Требование невыполнимо или противоречит контрактам M1–M3 — **остановись и
доложи**. Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест,
правка файлов из «Не трогать».

Отдельно: **не заменяй «не измерено» на ноль, пустой список или «не помогло»**,
даже если так короче. Это ровно тот дефект, ради которого веха и вводит
состояние.

## Стыки с соседними вехами

Веха обещает следующей (M5, прокси): готовое состояние `not_measured` и правило
знаменателя, класс провайдеров `entrance` и поле возраста контента. M5 добавит
прокси в `build_argv()` — с кредами из окружения, а не из аргументов командной
строки, потому что аргументы видны в `docker ps` любому на хосте.
