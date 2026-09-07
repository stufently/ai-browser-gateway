# Веха M4 — заход исправлений

| | |
|---|---|
| Клон | `/home/user/exec-clones/abg-m4-entrances`, ветка `m4-entrances` |
| Базовый коммит | `34cebee` «Give entrances a browser user agent» |
| Исполнитель | **Codex** (тот же, кто писал веху) |
| Основание | живой прогон постановщика + перекрёстный мутационный прогон |

Заход **один**. Всё, что ниже, закрывается в нём; новых улучшений не добавлять.

## Что уже сделано постановщиком, трогать не нужно

Коммит `34cebee` уже в ветке: обходные входы получили явный `User-Agent`.

Причина — дефект, который виден только на живой цели. Лента LowEndTalk из
контейнера отдавала `403`, хотя тот же адрес из `curl` отдавал `200`. Разница
оказалась в одном заголовке; измерено на одной цели тремя значениями:

| User-Agent | Ответ |
|---|---|
| `curl/7.88.1` | 200 |
| `Python-urllib/3.14` (умолчание стандартной библиотеки) | **403** |
| строка Chrome | 200 |

После правки лента отдаёт `200`, 777 448 байт, sentinel найден, возраст контента
52 секунды — то есть вход **выигрывает клетку, которую голый `curl` теряет на
403**. Это и есть измеримая победа, ради которой веха писалась.

Дефект родом из спеки, а не из твоей работы: замер под спеку снят `curl`, а
реализация ходит стандартной библиотекой, и следствие этого различия в спеке
названо не было.

## Что закрывать: четыре дыры в ТЕСТАХ

Ни одна из них не является дефектом кода — код в каждом случае прав. Проверены
постановщиком на 227 зелёных тестах: мутация ложится, сьют остаётся зелёным.

1. **`bench/providers/docker/probe.py`, адаптер `rss`** — снятие проверки
   `published.tzinfo is not None` (то есть приём дат без часового пояса)
   переживает весь сьют. Нужен тест: лента, где `pubDate` без зоны, не даёт
   возраста (`None`), а не считает дату как UTC.
2. **`parse_wayback`** — снятие `or not closest[key]` (то есть приём **пустой
   строки** в `url`/`timestamp`) переживает сьют. Нужен тест: `closest` с
   пустыми строками — это `ValueError`, а не «снимок найден».
3. **`WaybackAdapter.navigate`** — замена `discovery["status"] >= 400` на
   `> 400` переживает сьют. Граница ровно `400` не покрыта: с мутацией код
   попытается разобрать тело ошибки как JSON. Нужен тест на статус `400`.
4. **`_age_hours`** — снятие `max(0.0, …)` переживает сьют. Дата снимка из
   будущего (расхождение часов) даст **отрицательный возраст**. Нужен тест:
   дата в будущем даёт `0.0`, а не число меньше нуля.

Плюс мутации в `tests/mutation_gate.py` — **по одной на каждую из четырёх**,
поверх имеющихся 68.

🚨 **Проверь, что мутация ЛЕГЛА, прежде чем считать её убитой**, и что тест
падает на СВОЕЙ строке проверки, а не на постороннем `AttributeError`. Гейт это
и требует, но убедись сам.

## Не трогать

- Всё из раздела «Не трогать» основной спеки `docs/specs/m4-entrances.md`
  остаётся в силе, включая `README.md`, `TASKS.md`, `CHANGELOG.md` и
  `docs/research/` — журнал и чейнджлог пишет координатор.
- Боевой код в этом заходе меняться **не должен**: все четыре находки — дыры в
  тестах. Если тебе кажется, что нужен код, — остановись и доложи.
- Коммит `34cebee` не переписывать и не откатывать.
- Ветку `main` в клоне не двигать: от неё считают критерии.

## Критерии приёмки

🚨 AC-414, AC-415, AC-416 и AC-417 проходят **уже сейчас**: боевой код прав,
дыра именно в тестах. Они стоят регрессионными замками. Работу заставляют
сделать AC-412 (гейт: не меньше 72 мутаций, все убиты) и AC-413 (тесты с
заданными именами обязаны существовать).


- **AC-411 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -m unittest discover -s tests -t . -q'`

- **AC-412 — мутационный гейт: не меньше 72 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=72 else 1)" && python3 tests/mutation_gate.py'`

- **AC-413 — тесты на все четыре дыры существуют под этими именами.**
  Имена заданы спекой, чтобы критерий не проходил за счёт постороннего теста.
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -m unittest -q tests.test_entrances.EntranceProbeTests.test_naive_pubdate_gives_no_age tests.test_entrances.EntranceProbeTests.test_status_400_is_a_measured_refusal tests.test_entrances.EntranceProbeTests.test_future_snapshot_age_is_clamped tests.test_entrances.EntranceProbeTests.test_empty_snapshot_fields_are_rejected'`

- **AC-414 — пустая строка в снимке Wayback это отказ, а не снимок.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
for closest in ({\"url\": \"\", \"timestamp\": \"20260906171542\"},
                {\"url\": \"http://web.archive.org/x\", \"timestamp\": \"\"}):
    try:
        probe.parse_wayback({\"archived_snapshots\": {\"closest\": closest}})
    except ValueError:
        continue
    raise SystemExit(\"пустая строка принята как снимок\")
"'`

- **AC-415 — возраст из будущего не отрицательный.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && python3 -c "
import importlib.util
from datetime import datetime, timedelta, timezone
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
now = datetime(2026, 9, 7, tzinfo=timezone.utc)
assert probe._age_hours(now + timedelta(hours=5), now) == 0.0
assert probe._age_hours(now - timedelta(hours=5), now) == 5.0
"'`

- **AC-416 — боевой код в заходе не менялся.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && git diff --quiet 34cebee..HEAD -- bench/'`

- **AC-417 — дерево чистое, спека захода закоммичена.**
  `bash -c 'cd /home/user/exec-clones/abg-m4-entrances && git ls-files --error-unmatch docs/specs/m4-entrances-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно семь, формат прежний. 🚨 Строку
`command` копируй из спеки **дословно**.

## Контракт на невыполнимое

Требование невыполнимо или требует правки боевого кода — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест.
