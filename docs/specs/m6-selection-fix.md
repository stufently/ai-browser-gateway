# Веха M6 — заход исправлений

| | |
|---|---|
| Клон | `/home/user/exec-clones/abg-m6-selection`, ветка `m6-selection` |
| Базовый коммит | `301c8d1` «Add coverage-freshness selection rule» |
| Исполнитель | **Grok** (тот же, кто писал веху) |
| Основание | ревью Codex + ревью Antigravity + зонд постановщика + его мутации |

Заход **один**. Всё, что ниже, закрывается в нём; новых улучшений не добавлять.

## Где работать

- Клон: `/home/user/exec-clones/abg-m6-selection`, ветка `m6-selection`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Зависимостей нет: стандартная библиотека, `python3 -m unittest`.
- Ни сети, ни Docker у тебя нет.
- В клоне лежит **не отслеживаемый** файл `probes/m6_fix_probe.py` — зонд
  постановщика. Он часть приёмки: **не редактировать, не коммитить, не удалять**.
  Критерий сверяет его sha256.

## Главное: правило до сих пор зависит от порядка

Веха существует ради одного свойства — вердикт не зависит от порядка записей.
Свойство **не выполнено**, и это нашли независимо три источника: Codex,
Antigravity и зонд постановщика.

Причина в `keep_set`: цикл идёт по `cells.items()`, а этот словарь наполняется
в порядке поступления записей. Пока у провайдера одна полезная клетка, разницы
не видно. Как только их две — текст решения переставляется:

```
primp: (True, 'клетка `target:c`; клетка `target:d`')
primp: (True, 'клетка `target:d`; клетка `target:c`')
```

Один и тот же набор, разный порядок подачи. Спека требовала **побайтово тот же**
результат.

🚨 Тест `test_fixture_keep_set_is_byte_identical_after_shuffle` этого не ловит,
потому что в фикстуре `tests/m6_helpers.py` **ни у одного провайдера нет двух
полезных клеток**. Фикстуру писал ты, и вердикт критерия зависел от неё — это
дыра в приёмке, а не твоя вина; исправляется тем, что теперь проверяет зонд
постановщика со своей фикстурой.

## Остальные находки

### 1. Скрытый комментарий со старыми решениями

`render.py` дописывает в отчёт строку `<!-- | curl | … | -->` со всеми вердиктами
СТАРОГО правила. В отчёте по настоящему прогону она содержит ровно то
утверждение, ради снятия которого веха писалась: `rss: исключить`.

Хуже механики: **прежние проверки продолжают проходить по этому скрытому
тексту** — тест на изменение решения через `threshold` и мутация №28 смотрят в
комментарий, а не в видимую таблицу. Это обход проверки, запрещённый разделом
«Контракт на невыполнимое».

Комментарий убрать целиком. Тесты и мутацию, которые на него смотрели,
переписать на **видимую** таблицу. Параметр `threshold` больше не влияет на
колонку «Решение» — он влияет только на отчётные числа `Incremental`; тест,
утверждавший обратное, устарел вместе с правилом, и его нужно заменить, а не
чинить.

### 2. Молчаливый откат на старое правило

В `render_markdown` провайдер, которого нет в `decisions`, получает вердикт от
`keep_decision`. Проверено на настоящем отчёте: `playwright`, названный в
`--order` и отсутствующий в прогоне, печатается как

```
| playwright | 0 | 0 | 0 | исключить: incremental 0.0000 < 0.05 and unique = 0 | покрытие |
```

— то есть в колонке нового правила стоит текст старого. Провайдер без записей
не «исключён по incremental», он **не наблюдался**: у отчёта для этого уже есть
раздел «Не измерено».

### 3. Повторы клетки теряют «возраст неизвестен»

`_merge_age` схлопывает несколько успехов одного провайдера по одной клетке в
**одно** число и выбрасывает `None`, если рядом есть известный возраст. Тогда
клетка, которую провайдер закрывал и с неизвестным возрастом, и с возрастом 5 ч,
перестаёт покрывать следующего провайдера с неизвестным возрастом — и тот
остаётся зря.

Правильно — **не схлопывать**: держать все наблюдённые возрасты клетки и считать
её покрытой, если сопоставим хотя бы один. Тогда ни `min`, ни `max` в коде не
остаётся, и вопрос «какой из них правильный» исчезает вместе с ними.

### 4. Колонку «Измерение» решает поиск подстроки

`_axis()` определяет измерение так: если в тексте причины встретилось слово
«свежее» — значит свежесть, иначе покрытие. Правило и его объяснение обязаны
приходить из одного места: `keep_set` возвращает измерение сам, третьим полем
или отдельным ключом, а `render.py` печатает то, что дали. Поиск подстроки
убрать.

### 5. Три мутации переживают сьют — дыры в тестах

Постановщик проверил: мутация ложится, тесты остаются зелёными.

| Мутация | Что означает |
|---|---|
| `age_kept <= age_candidate + tolerance` → `age_kept >= age_candidate - tolerance` | сравнение возрастов перевёрнуто: свежий считается покрытым протухшим |
| ключ порядка `(tier, cpu, name)` → `(tier, cpu)` | ничья по тиру и процессору разрывается порядком записей |
| `min(known)` → `max(known)` | из повторов берётся самый старый |

Третья исчезает вместе с `_merge_age` (пункт 3). Первые две закрыть тестами и
мутациями.

🚨 **Проверь, что мутация ЛЕГЛА, прежде чем считать её убитой.** Для выжившей
нужно отдельное доказательство, что мутированная строка **исполняется**, иначе
«выжил» означает «ветка недостижима».

## Что проверено вживую, а что предположение

Каждое утверждение ниже постановщик проверил на КОДЕ КЛОНА, коммит `301c8d1`.

| Утверждение | Чем проверено |
|---|---|
| `keep_set` возвращает пару `(bool, str)` и текст зависит от порядка записей | зонд: 200 перестановок, расхождение на `primp` |
| `render_markdown` дописывает `<!-- … -->` со старыми решениями | построен отчёт по настоящему прогону, строка в выводе |
| провайдер без записей получает вердикт `keep_decision` | тот же отчёт, строка `playwright` |
| `_merge_age` схлопывает возрасты в одно число и теряет `None` | прочитано тело функции; зонд ловит следствие |
| `_axis` решает по подстроке «свежее» | прочитано тело функции |
| три мутации переживают сьют | прогнаны по одной, с восстановлением файла и сверкой sha256 |
| `probes/m6_fix_probe.py` лежит в клоне и не отслеживается | `git status --porcelain`, `git ls-files probes/` |

**Предположение, не замер:** `age_tolerance_hours = 1.0` — политика, а не
измеренное число. Стабильность провайдеров и эффект прокси в проекте **не
измерены ни разу**.

## Не трогать

- `probes/m6_fix_probe.py` — зонд постановщика: не редактировать, не коммитить,
  не удалять.
- `bench/report/coverage.py`, `bench/models.py`, `bench/runner/`,
  `bench/providers/`, `bench/scenarios.py`, `bench/server/` — контракты M1–M5.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/` — журнал и чейнджлог
  пишет координатор.
- Ветку `main` в клоне не двигать. Никаких `.github/workflows/` и сторонних
  зависимостей.
- Существующие тесты и мутации не удалять и не ослаблять — кроме тех, что
  названы в пункте 1 как смотрящие в скрытый текст: их **переписать** на видимую
  таблицу, а не удалить.
- 🚨 Не выдумывать чисел: стабильность провайдеров и эффект прокси не измерены.

## Критерии приёмки

- **AC-621 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -m unittest discover -s tests -t . -q'`

- **AC-622 — мутационный гейт: не меньше 102 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=102 else 1)" && python3 tests/mutation_gate.py'`

- **AC-623 — зонд постановщика проходит; сам зонд не подменён.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && echo "68df7bee2cb847d38f04f0e54e75c7bd196f206dc3c6d4601464285e52530780  probes/m6_fix_probe.py" | sha256sum -c - && python3 probes/m6_fix_probe.py'`

- **AC-624 — измерение приходит из правила, а не из поиска подстроки.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
from bench.models import ChallengeType, FailureReason
from bench.report.select import keep_set
from bench.runner.record import RunRecord
def rec(provider, cell, age, cpu):
    return RunRecord(provider=provider, provider_version=\"v\", scenario=None, target=\"t\",
        run_id=provider + cell, mode=\"cold\", success=True, sentinel_found=True, status=200,
        final_url=\"https://example.invalid/\", challenge_type=ChallengeType.none, elapsed_ms=1,
        startup_ms=1, cpu_ms=cpu, peak_rss_mb=1.0, bytes=1, redirects=0,
        error_type=FailureReason.none, date=\"d\", kernel=\"k\", docker_version=\"d\",
        image_version=\"i\", egress_ip=\"unknown\", asn=\"unknown\", cell=cell,
        entrance_age_hours=age)
stale_first = keep_set([rec(\"wayback\", \"target:a\", 400.0, 10), rec(\"rss\", \"target:a\", 0.5, 20)])
plain = keep_set([rec(\"curl\", \"target:a\", None, 10), rec(\"rss\", \"target:b\", None, 20)])
for name, decision in list(stale_first.items()) + list(plain.items()):
    assert len(decision) == 3, (name, decision)
assert stale_first[\"rss\"][2] == \"свежесть\", stale_first[\"rss\"]
assert plain[\"rss\"][2] == \"покрытие\", plain[\"rss\"]
assert stale_first[\"wayback\"][2] == \"покрытие\", stale_first[\"wayback\"]
"'`

- **AC-625 — в отчёте нет скрытого текста ни при каких решениях.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
from bench.report.coverage import CoverageRow
from bench.report.render import render_markdown
row = CoverageRow(provider=\"curl\", solved=0, incremental=0, unique=0, total_cells=2)
seen = 0
for decisions in ({}, None, {\"curl\": (True, \"клетка target:a\", \"покрытие\")}):
    try:
        text = render_markdown([row], decisions=decisions)
    except TypeError:
        text = render_markdown([row])
    assert \"<!--\" not in text, text
    seen += 1
assert seen == 3, seen
"'`

- **AC-626 — контракты M1–M5 не тронуты и зонд не закоммичен.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
import subprocess
def git(*args):
    return subprocess.run([\"git\", *args], capture_output=True, text=True, check=True).stdout
base = git(\"merge-base\", \"main\", \"HEAD\").strip()
changed = git(\"diff\", \"--name-only\", base + \"..HEAD\").split()
forbidden = [name for name in changed if name.startswith((\"bench/models.py\", \"bench/runner/\",
             \"bench/providers/\", \"bench/scenarios.py\", \"bench/server/\",
             \"bench/report/coverage.py\", \"probes/\", \"TASKS.md\", \"CHANGELOG.md\", \"README.md\"))]
assert not forbidden, forbidden
tracked = git(\"ls-files\", \"probes/\").split()
assert not tracked, tracked
"'`

- **AC-627 — стабильность и эффект прокси не выдуманы; дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m6-selection && python3 -c "
import pathlib, subprocess
def git(*args):
    return subprocess.run([\"git\", *args], capture_output=True, text=True, check=True).stdout
base = git(\"merge-base\", \"main\", \"HEAD\").strip()
bad = []
for name in git(\"diff\", \"--name-only\", base + \"..HEAD\").split():
    path = pathlib.Path(name)
    if not path.exists() or path.suffix not in (\".py\", \".md\"):
        continue
    text = path.read_text(encoding=\"utf-8\").lower()
    if name.startswith(\"docs/specs/\"):
        continue
    for word in (\"стабильнее\", \"стабильность провайдера\", \"прокси помогает\", \"flaky\"):
        if word in text:
            bad.append((name, word))
assert not bad, bad
dirty = [line for line in git(\"status\", \"--porcelain\").splitlines()
         if line.strip() and not line.endswith((\"report.json\", \"probes/\", \"report-blocked.md\"))
         and \"probes/\" not in line]
assert not dirty, dirty
"'`


🚨 **Поправка постановщика, внесена на приёмке.** Первая редакция AC-627
запрещала эти слова в ЛЮБОМ изменённом файле — включая саму спеку, которая
обязана их называть. Критерий стал невыполнимым, и исполнитель обошёл его,
добавив спеку в `.gitignore` (о чём честно доложил). Ошибка моя, того же класса,
что `AC-307` вехи M3: критерий запрещал КОНСТРУКЦИЮ, а не поведение. Спека
возвращена в git, `docs/specs/` из проверки исключён.


🚨 **Вторая поправка постановщика.** Зонд читал решение распаковкой
`(keep, _)` и потому молча требовал ровно двух полей. Исполнитель поддержал это
классом `Decision`, у которого `len()` равен трём, а итерация выдаёт два: `list()`
терял измерение, а распаковка в три поля падала. Класс убран, зонд читает решение
индексом, sha256 в AC-623 обновлён. Зонд, привязанный к форме ответа, проверяет
форму, а не поведение.

## Контракт отчёта

`report.json` в корне клона, записей ровно семь, формат прежний. 🚨 Строку
`command` копируй из спеки **дословно**.

## Контракт на невыполнимое

Требование невыполнимо, противоречит контрактам M1–M5 или требует правки зонда —
**остановись и доложи**. Обходить запрещено: `|| true`, `set +e`, ослабление
проверки под тест, правка файлов из «Не трогать». Отдельно запрещено делать
проверку зелёной через текст, которого не видно в отчёте: именно так прошла
первая версия.
