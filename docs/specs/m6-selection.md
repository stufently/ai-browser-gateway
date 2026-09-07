# Веха M6 — правило отбора по нескольким измерениям

| | |
|---|---|
| Клон | `/home/user/exec-clones/abg-m6-selection`, ветка `m6-selection` |
| Базовый коммит | HEAD ветки `main` на момент клонирования |
| Исполнитель | **Grok** |
| Ревью и кросс-мутации | **Codex** (противоположный исполнитель) |

## Где работать

- Клон: `/home/user/exec-clones/abg-m6-selection`, ветка `m6-selection` от `main`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Спека уже в дереве, редактировать её не нужно.
- Зависимостей нет: стандартная библиотека, `python3 -m unittest`.
- Ни сети, ни Docker у тебя нет. Всё проверяемое — на поддельных объектах и на
  записях прогонов, которые ты сам кладёшь в фикстуру.

## Задача и почему

Сейчас отчёт **сам себе противоречит**, и это видно в одном документе. Прогон
`m4_combined.jsonl`, команда с умолчаниями, ничего не подкручено:

```
| Провайдер | Медианный возраст, ч |
| wayback   | 220.61 |
| rss       | 0.02   |

| Провайдер | Взял | Incremental | Unique | Решение |
| wayback   | 2 | 2 | 1 | оставить |
| rss       | 1 | 0 | 0 | исключить: incremental 0.0000 < 0.05 and unique = 0 |
```

То есть инструмент советует выбросить провайдера, который приносит содержимое
возрастом **минуту**, в пользу того, который приносит содержимое возрастом
**девять суток** — и молчит об этом.

### Механизм: порядок внутри тира не определён

`incremental()` считает, что провайдер добавил **к префиксу списка**. Список —
`--order`, по умолчанию `sorted(PROVIDERS, key=tier)`. Тиры сейчас такие:

```
curl 0, wayback 0, rss 0, curl_cffi 1, primp 1,
playwright 2, patchright 2, camoufox 3, pydoll 3
```

Три провайдера в тире 0, два в тире 1, два в тире 2, два в тире 3. Сортировка
устойчива, значит внутри тира порядок = **порядок объявления в реестре**. Он
ничего не выражает: строку в файле можно поменять местами, и вердикт поменяется.

Замерено на всех шести перестановках тира 0 (`m4_combined.jsonl`):

| Порядок | curl | wayback | rss |
|---|---|---|---|
| curl → rss → wayback | исключить | **оставить** | **оставить** |
| curl → wayback → rss | исключить | оставить | **исключить** |
| rss → curl → wayback | исключить | оставить | **оставить** |
| rss → wayback → curl | исключить | оставить | **оставить** |
| wayback → curl → rss | исключить | оставить | **исключить** |
| wayback → rss → curl | исключить | оставить | **исключить** |

`rss` получает «оставить» в трёх порядках из шести и «исключить» в трёх. Разница
— только позиция в списке. Умолчание продукта попадает в худшую половину.

### Чем клетка «уже решена» на самом деле не решена

`solved_cells` знает про клетку один бит: успех. На `target:cf-lowendtalk`
успешны оба, но:

| Провайдер | `entrance_age_hours` |
|---|---|
| `rss` | **0.0172** (62 секунды) |
| `wayback` | **431.86** (18 суток) |

Правило считает их взаимозаменяемыми. Для задачи «доставать нужные страницы»
восемнадцатисуточный снимок — часто не та страница.

## Все измерения, по которым провайдеры различаются

Пункт спеки, а не введение: правило нельзя чинить, не перечислив, между чем оно
выбирает. Ниже — всё, что **есть в записи прогона**, с пометкой, измерено оно
или нет.

1. **Покрытие.** `success` по клетке. Измерено, это основной результат.
2. **Свежесть содержимого.** `entrance_age_hours`. Измерено, но **только у
   обходных входов**: у `curl`, браузеров и прочих прямых провайдеров поле
   всегда `None`. `None` означает «не измерено», а не «свежее» и не «протухшее».
3. **Стоимость — это ТРИ несравнимые оси, а не одна.** Медианы по сохранённым
   прогонам:

   | Провайдер | Режим | elapsed, мс | cpu, мс | RSS, МиБ |
   |---|---|---|---|---|
   | `curl` | cold | 18 | 659 | 34 |
   | `primp` | cold | 27 | 219 | 34 |
   | `playwright` | cold / warm | 502 / **14** | 906 / 927 | 562 / 562 |
   | `patchright` | cold / warm | 878 / **24** | 2126 / 2150 | 1538 / 1550 |
   | `pydoll` | cold / warm | 1460 / **23** | 3376 / 3409 | 1329 / 1327 |
   | `rss` | cold | 258 | 933 | 46 |
   | `wayback` | cold | **5416** | 986 | 38 |

   Читается так: `wayback` — **самый медленный по времени** и почти **самый
   дешёвый по памяти**; `pydoll` в тёплом режиме быстрее `curl` по времени, но
   стоит **в сорок раз больше памяти** и втрое больше процессора. Тёплый старт
   экономит время (в ~40 раз) и **не экономит ни процессор, ни память** — они
   уплачены при старте и остаются. Единого числа «стоимость» не существует;
   `tier` в реестре — грубая ручная сводка, а не измерение.
4. **Стабильность.** **НЕ ИЗМЕРЕНА.** Повторов одной клетки в одинаковых условиях
   в проекте нет ни одного. Всё, что можно сказать про «провайдер нестабилен», —
   предположение. В правило её не вводить, в отчёте не изображать.
5. **Доступность входа на цели.** `not_measured`: у `rss` вход настроен только у
   одной цели из двух. Это свойство ЦЕЛИ, а не провайдера, и оно уже отделено
   вехой M4. Правило обязано не считать это ни успехом, ни отказом.
6. **Эффект прокси.** **НЕ ИЗМЕРЕН НИ РАЗУ.** Машинерия из M5 есть, кредов нет.
   Любая строка вида «через прокси провайдер X проходит» — выдумка.

## Что оптимизирует правило, а что остаётся ограничением

- **Оптимизирует — покрытие клеток.** Это цель проекта: достать нужную страницу.
- **Свежесть — квалификатор покрытия, а не отдельная цель.** Клетка, решённая
  заметно более старым содержимым, не считается тем же решением.
- **Стоимость — порядок разбора, а не критерий.** Она решает, кого рассматриваем
  раньше, и никогда — кого выкидываем.
- **Стабильность и эффект прокси — вне правила**, пока не измерены.

## Что сделать

### 1. Новый модуль `bench/report/select.py`

`bench/report/coverage.py` **не трогать**: его арифметика верна и покрыта
тестами вехи M1, `incremental()` остаётся как отчётное число. Новое правило
живёт рядом.

```python
def canonical_order(records) -> list[str]:
    """Порядок разбора из ДАННЫХ, а не из порядка строк в реестре."""

def keep_set(records, *, age_tolerance_hours: float = 1.0) -> dict[str, tuple[bool, str]]:
    """Провайдер -> (оставить, причина). От порядка записей не зависит."""
```

**`canonical_order`** сортирует провайдеров по ключу
`(tier, медианный cpu_ms по успешным записям, имя)`. Первые два — измерения,
третий — детерминированный разрыв ничьей. Провайдер без успешных записей берёт
`cpu_ms = +inf`: разбираем его последним. Порядок строк в реестре в ключ **не
входит**.

**`keep_set`** идёт по `canonical_order` и оставляет провайдера, если он
приносит хотя бы одну клетку, которой у уже оставленных нет **в сопоставимом
качестве**. Клетка `C`, решённая провайдером `P`, считается уже покрытой, если
её решает кто-то из оставленных `Q`, и при этом:

- возраст обоих неизвестен (`None`) — покрыта;
- возраст известен у обоих и `age(Q) <= age(P) + age_tolerance_hours` — покрыта;
- **иначе не покрыта** — в частности, когда `age(Q)` известен и хуже, и когда у
  одного возраст известен, а у другого нет.

Причина возвращается текстом и обязана называть, ЧЕМ провайдер полезен
(«клетка `target:cf-lowendtalk` свежее на 431.8 ч») либо почему нет.

`age_tolerance_hours` — **политика, а не измерение**. Умолчание `1.0` выбрано
как «в пределах часа считаем одинаково свежим»; это решение владельца, и в
докстринге так и написать. Числа, полученного замером, здесь нет.

### 2. Правило не зависит от порядка — это обязано быть доказано

Тот же набор записей, поданный в любом порядке, обязан давать **побайтово тот
же** результат `keep_set`. То же для `canonical_order`.

Это не «желательно» — это единственное, ради чего веха существует.

### 3. Пустой набор — не «все условия выполнены»

Квантор «все измерения удовлетворяют условию» на пустом наборе **истинен**, и
критерий позеленеет, не начав работать. Поэтому везде, где правило или тест
проходит по набору клеток/провайдеров/измерений:

- сначала утверждается **непустота** набора, отдельной проверкой, до цикла;
- если условие говорит про РАЗЛИЧИЕ («три разных измерения», «возрасты
  отличаются»), утверждается **мощность множества различных значений**, а не
  длина списка: три одинаковых измерения — набор непустой, а условие на нём
  ложно, и тест пройдёт впустую;
- только потом — само условие.

Касается и боевого кода (`keep_set` на пустых записях возвращает пустой словарь,
а не «всех оставить»), и тестов.

### 4. Отчёт говорит, почему провайдер выкинут

`build_report` берёт колонку «Решение» из `keep_set`, а не из
`keep_decision`. Числа `Взял`/`Incremental`/`Unique` остаются как есть —
это отчётность, и `--order` продолжает задавать **порядок строк** в таблицах.
На решение `--order` больше не влияет никак.

В таблице решений добавить колонку, называющую измерение, которое решило:
покрытие или свежесть.

### 5. Тесты

Помимо тестов на пункты выше — обязательны:

1. **Один набор в двух порядках даёт одинаковый вердикт.** Записи перемешать и
   подать дважды; результаты сравнить целиком. Тест ловит класс, не зная, какое
   измерение забыли.
2. **Регрессия на настоящем случае.** Фикстура из трёх провайдеров, где `rss`
   решает клетку возрастом 0.017 ч, `wayback` — ту же возрастом 431.86 ч и ещё
   одну свою, `curl` не решает ничего. Ожидание: оставлены `rss` и `wayback`,
   выкинут `curl` — **при любом порядке**.
3. `None`-возраст не считается ни свежим, ни протухшим: провайдер с неизвестным
   возрастом не покрывает провайдера с известным, и наоборот.
4. `not_measured` не делает провайдера ни полезным, ни бесполезным.

Плюс мутации в `tests/mutation_gate.py` — **не меньше чем по одной на каждый
пункт 1–4** поверх имеющихся 91.

🚨 **Проверь, что мутация ЛЕГЛА, прежде чем считать её убитой.** Для мутанта,
который выжил, нужно отдельное доказательство, что мутированная строка вообще
**исполняется** (маркер в точке), — иначе «выжил» означает «ветка недостижима», а
не «дыра в тестах».

## Не трогать

- `bench/report/coverage.py` — контракт вехи M1; `incremental()`,
  `solved_cells()`, `keep_decision()` остаются как есть и продолжают
  использоваться для отчётных чисел.
- `bench/models.py`, `bench/runner/`, `bench/providers/`, `bench/scenarios.py`,
  `bench/server/` — вехи M1–M5 закрыты, правило отбора живёт в отчёте.
- `--order` из CLI не удалять: он остаётся порядком строк.
- Существующие 273 теста и 91 мутация — не удалять и не ослаблять.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/` — **не трогать
  вообще**: журнал и чейнджлог пишет координатор.
- Ветку `main` в клоне не двигать. Никаких `.github/workflows/`, никаких
  сторонних зависимостей.
- 🚨 **Не выдумывать чисел.** Стабильность не измерена, эффект прокси не измерен.
  Никаких «провайдер X стабильнее Y» в коде, тестах, докстрингах и отчёте.

## Критерии приёмки

- **AC-601 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -m unittest discover -s tests -t . -q'`

- **AC-602 — мутационный гейт: не меньше 95 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=95 else 1)" && python3 tests/mutation_gate.py'`

- **AC-603 — вердикт не зависит от порядка записей.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
import itertools, random
from bench.report.select import canonical_order, keep_set
from tests.m6_helpers import fixture_records
records = fixture_records()
assert len(records) >= 6, len(records)
assert len({record.provider for record in records}) == 3, \"нужны три РАЗНЫХ провайдера\"
assert len({record.cell for record in records}) >= 2, \"нужны две РАЗНЫЕ клетки\"
ages = {record.entrance_age_hours for record in records if record.success}
assert len(ages) >= 2, \"возрасты в фикстуре обязаны РАЗЛИЧАТЬСЯ\"
first_order, first_keep = canonical_order(records), keep_set(records)
seen = 0
for _ in range(50):
    shuffled = list(records)
    random.shuffle(shuffled)
    assert canonical_order(shuffled) == first_order, shuffled
    assert keep_set(shuffled) == first_keep, shuffled
    seen += 1
assert seen == 50, seen
"'`

- **AC-604 — свежий провайдер не выкидывается ради протухшего.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
from bench.report.select import keep_set
from tests.m6_helpers import fixture_records
decisions = keep_set(fixture_records())
assert set(decisions) == {\"curl\", \"rss\", \"wayback\"}, sorted(decisions)
assert decisions[\"rss\"][0] is True, decisions[\"rss\"]
assert decisions[\"wayback\"][0] is True, decisions[\"wayback\"]
assert decisions[\"curl\"][0] is False, decisions[\"curl\"]
assert \"cf-lowendtalk\" in decisions[\"rss\"][1], decisions[\"rss\"][1]
"'`

- **AC-605 — порядок разбора берётся из данных, а не из реестра.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
import bench.providers.registry as registry
from bench.report.select import canonical_order
from tests.m6_helpers import fixture_records
records = fixture_records()
before = canonical_order(records)
original = registry.PROVIDERS
registry.PROVIDERS = tuple(reversed(list(original)))
try:
    after = canonical_order(records)
finally:
    registry.PROVIDERS = original
assert before == after, (before, after)
"'`

- **AC-606 — неизвестный возраст не считается ни свежим, ни протухшим.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -m unittest -q tests.test_select.AgeSemanticsTests.test_unknown_age_does_not_cover_known tests.test_select.AgeSemanticsTests.test_known_age_does_not_cover_unknown'`

- **AC-607 — пустой набор не выдаёт «всех оставить».**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
from bench.report.select import canonical_order, keep_set
assert keep_set([]) == {}, keep_set([])
assert canonical_order([]) == [], canonical_order([])
"'`

- **AC-608 — `not_measured` не делает провайдера ни полезным, ни бесполезным.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -m unittest -q tests.test_select.NotMeasuredTests'`

- **AC-609 — отчёт на настоящем прогоне больше не советует выкинуть `rss`.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
from bench.report.build import build_report
from tests.m6_helpers import write_real_run
path = write_real_run()
text = build_report(path, order=[\"curl\", \"wayback\", \"rss\"])
row = [line for line in text.splitlines() if line.startswith(\"| rss |\")]
assert row, text
assert \"исключить\" not in row[0], row[0]
assert \"| curl |\" in text and any(\"исключить\" in line for line in text.splitlines() if line.startswith(\"| curl |\")), text
"'`

- **AC-610 — контракт M1 не тронут.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && git diff --name-only $(git merge-base main HEAD)..HEAD | python3 -c "
import sys
changed = sys.stdin.read().split()
forbidden = [name for name in changed
             if name.startswith((\"bench/models.py\", \"bench/runner/\", \"bench/providers/\",
                                 \"bench/scenarios.py\", \"bench/server/\", \"bench/report/coverage.py\"))]
assert not forbidden, forbidden
"'`

- **AC-611 — стабильность и эффект прокси не выдуманы.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
import subprocess
changed = subprocess.run([\"git\", \"diff\", \"--name-only\",
                          subprocess.run([\"git\",\"merge-base\",\"main\",\"HEAD\"], capture_output=True, text=True, check=True).stdout.strip() + \"..HEAD\"],
                         capture_output=True, text=True, check=True).stdout.split()
import pathlib
bad = []
for name in changed:
    path = pathlib.Path(name)
    if not path.exists() or path.suffix not in (\".py\", \".md\"):
        continue
    text = path.read_text(encoding=\"utf-8\").lower()
    for word in (\"стабильнее\", \"стабильность провайдера\", \"прокси помогает\", \"flaky\"):
        if word in text:
            bad.append((name, word))
assert not bad, bad
"'`

- **AC-612 — состав работы и чистое дерево.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && git ls-files --error-unmatch bench/report/select.py tests/test_select.py tests/m6_helpers.py >/dev/null && python3 -c "
import subprocess
def git(*args):
    return subprocess.run([\"git\", *args], capture_output=True, text=True, check=True).stdout
base = git(\"merge-base\", \"main\", \"HEAD\").strip()
changed = git(\"diff\", \"--name-only\", base + \"..HEAD\").split()
stray = [name for name in changed if not (name.startswith((\"bench/report/\", \"tests/\")) or name == \"bench/cli.py\")]
assert not stray, stray
dirty = [line for line in git(\"status\", \"--porcelain\").splitlines()
         if line.strip() and \"report.json\" not in line and \"report-blocked.md\" not in line]
assert not dirty, dirty
"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно двенадцать, формат прежний. 🚨 Строку
`command` копируй из спеки **дословно**.

Файл `tests/m6_helpers.py` пишешь ты; `fixture_records()` обязан возвращать
записи трёх провайдеров с настоящими числами из раздела «Задача и почему»
(`rss` 0.0172 ч, `wayback` 431.86 ч и вторая его клетка, `curl` без успехов),
а `write_real_run()` — класть их в JSONL и возвращать путь.

## Контракт на невыполнимое

Требование невыполнимо, противоречит контрактам M1–M5 или требует правки
`coverage.py` — **остановись и доложи**. Обходить запрещено: `|| true`, `set +e`,
ослабление проверки под тест, правка файлов из «Не трогать».
