# Веха M1, заход исправлений — по двум независимым ревью

| | |
|---|---|
| Репозиторий | `ai-browser-gateway`, клон `/home/user/exec-clones/abg-m1-bench-core` |
| Ветка | `m1-bench-core` (уже создана, работа в коммите `6e3e539`) |
| Дата | 06.09.2026 |
| Исполнитель | **Grok** — автор этой вехи, чинит свою работу |
| Основание | ревью и мутационный прогон противоположного исполнителя (Codex) |

Машинный гейт вехи прошёл 7/7, живой стенд поднят и все 12 сценариев отдаются.
Дальше два независимых прохода Codex нашли **пять дефектов кода** и **шесть дыр в
тестах**. Это единственный заход исправлений: после него веха принимается или
снимается.

## Где работать

- Клон: `/home/user/exec-clones/abg-m1-bench-core` — тот же, что и в первый
  заход, работа уже там, ветка `m1-bench-core` уже создана.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Постановщик кладёт в клон до запуска только эту спеку
  (`docs/specs/m1-bench-core-fix.md`, untracked). Зависимостей нет: всё на
  стандартной библиотеке, тесты гоняются системным `python3` (на хосте 3.14.4).
- Исправления кладутся НОВЫМ коммитом поверх `6e3e539`. Прежний коммит не
  переписывать: `git commit --amend` запрещён.

## Что чинить в коде

### 1. `bench/models.py`, `evaluate` — отказ по статусу обязан побеждать sentinel

Сейчас sentinel сверяется РАНЬШЕ статуса, поэтому `403` со строкой ожидания в теле
возвращает `success=True`.

**Это не теория, это уже произошло на боевой цели.** Заглушка Cloudflare называет
заблокированный хост, у цели `bizprofile.net` строка ожидания содержала слово
«bizprofile» — и провальный запрос засчитывался успехом. Правило, которое считает
страницу отказа успехом, портит весь замер, ради которого веха и делается.

Новый порядок в `evaluate`: сначала `error_type`, затем **статус `4xx`/`5xx` →
отказ независимо от sentinel** (`403 → http_403`, `429 → http_429`,
`500…599 → http_5xx`, прочие `4xx` → `content_mismatch`), и только потом поиск
sentinel. Обнови докстроку: правило теперь «успех — это найденный sentinel на
ответе, который не является отказом».

### 2. `bench/report/coverage.py` — `records` расходуется дважды

`incremental()` проходит по `records` в `solved_cells()`, а потом ещё раз сам.
Генератор после первого прохода пуст, и получается `total_cells=0`, `unique=0`
при живых успехах. Читать журнал JSONL потоком — штатный сценарий следующей вехи.

Материализуй вход один раз в начале `incremental()` и работай со списком.

### 3. `bench/report/coverage.py` — провайдер без успехов исчезает молча

`unknown = set(by_provider) - set(order)` видит только провайдеров, у которых есть
хоть один успех. Провайдер, проваливший ВСЁ и не указанный в `order`, обязан
давать `ValueError`, а сейчас просто пропадает из отчёта. Считай множество
провайдеров по всем записям, а не по успешным.

### 4. `bench/report/render.py` — порог не пробрасывается

`render_markdown` зовёт `keep_decision(row)` с дефолтом `0.05`. По спеке порог
настраиваемый. Добавь `threshold: float = 0.05` в сигнатуру и передай дальше.

### 5. `bench/server/app.py`, `_header_codings` — `q=0` читается как разрешение

`part.split(";", 1)[0]` выбрасывает параметр качества, поэтому
`Accept-Encoding: gzip;q=0, identity` получает сжатое тело вопреки прямому запрету
клиента. Разбирай `q`: `q=0` означает, что кодировка запрещена.

## Что чинить в тестах

Шесть мутаций Codex ВЫЖИЛИ во всех 53 тестах. Каждая — непокрытое место; напиши
тест, который её убивает, и добавь саму мутацию в `tests/mutation_gate.py`.

| Файл | Что выжило | Какого теста нет |
|---|---|---|
| `coverage.py` | из `total_cells` исключены ячейки, которые не взял никто | знаменатель на смешанном входе: часть ячеек взята, часть провалена всеми |
| `coverage.py` | `records[0]`, `get`→индексирование, снятая защита деления | пустой вход, провайдер без успехов, `total_cells=0` |
| `record.py` | убран завершающий `\n` в `to_jsonl_line` | две записи подряд обязаны читаться как две строки |
| `record.py` | снят вызов `validate` в сериализаторе и в десериализаторе по отдельности | негативный тест на ОБА конца: неизвестный `mode`, отрицательный `elapsed_ms`, `success=True` при `error_type != none` |
| `record.py` | `target=None` и `error_type=none` при чтении | round-trip заполненной боевой цели и неуспешной записи с причиной отказа |
| `models.py` | границы `500` и `599` исключены из `5xx` по отдельности | обе границы диапазона проверяются явно |

Плюс новые тесты на пять правок кода выше — в первую очередь на то, что `403` с
sentinel в теле даёт `(False, http_403)`, а не успех.

`tests/mutation_gate.py` после захода содержит **не меньше двенадцати** мутаций:
шесть прежних и шесть новых. Порядок шагов внутри обвязки не меняй — он
правильный.

## Не трогать

- `docs/`, кроме `docs/specs/m1-bench-core-fix.md`: он приезжает untracked и
  **коммитится вместе с исправлениями**.
- `docs/specs/m1-bench-core.md` — спека вехи, уже закоммичена, не редактировать.
- `README.md`, `TASKS.md`, `bench/targets/targets.toml`.
- Сторонних зависимостей по-прежнему ноль.
- Существующие 53 теста не удалять и не ослаблять. Если тест приходится менять
  из-за нового правила `evaluate` — меняй ожидание, а не строгость.

## Критерии приёмки

- **AC-101 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -m unittest discover -s tests -t . -q'`

- **AC-102 — мутационный гейт: не меньше двенадцати мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=12 else 1)" && python3 tests/mutation_gate.py'`

- **AC-103 — отказ по статусу побеждает sentinel.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -c "
from bench.models import FetchResult, FailureReason, ChallengeType, evaluate
r = FetchResult(provider=\"p\", provider_version=\"1\", requested_url=\"u\", final_url=\"u\", status=403, html=\"<p>SENT</p>\", text=\"SENT\", elapsed_ms=1, startup_ms=1, cpu_ms=1, peak_rss_mb=1.0, bytes_received=1, redirects=0, error_type=FailureReason.none, challenge=ChallengeType.none)
ok, why = evaluate(r, \"SENT\")
assert ok is False, ok
assert why is FailureReason.http_403, why
"'`

- **AC-104 — состав работы.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && git ls-files --error-unmatch docs/specs/m1-bench-core-fix.md tests/mutation_gate.py bench/models.py bench/report/coverage.py bench/report/render.py bench/runner/record.py bench/server/app.py >/dev/null'`

- **AC-105 — дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

Перезапиши `report.json` в корне клона — записей ровно пять, по одной на критерий:

```json
{"criteria": [{"id": "AC-101", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

## Контракт на невыполнимое

Требование невыполнимо или противоречит уже принятому — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, `--no-deps`, ослабление проверки под тест,
удаление неудобного теста.

Отдельно: если сочтёшь, что какая-то из шести мутаций Codex **эквивалентна** —
то есть по наблюдаемому поведению неотличима от исходного кода, — не выдумывай под
неё тест. Исключи её с ПИСЬМЕННЫМ обоснованием, почему поведение не меняется.
«Не смог убить» обоснованием не является.
