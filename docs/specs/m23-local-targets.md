# M23 — цели замера вне гита и публичная сводка по классам

## Шапка и где работать

Репозиторий ~/github/ai-browser-gateway, 22.09.2026.
BASE_SHA `013431853f942356bd5c4c346c54864f2fabb2d5` — вершина `main`,
коммит «Close M22 in project journal».
Клон ~/exec-clones/abg-m23-local-targets-20260922, ветка m23-local-targets,
origin push DISABLED. Исполнитель — gk (Grok): у Codex исчерпан лимит
аккаунта до 24.09.2026, реализация по директиве владельца идёт через
исполнителя в панели.

**push в origin запрещён**, в том числе `git push` ветки: работу заберёт
постановщик через `git fetch` из клона.

Спека и чекер приезжают в клон untracked. **Их нужно закоммитить вместе с
работой** — именно `docs/specs/m23-local-targets.md` и
`docs/specs/checks/m23_local_targets.py`. Править их содержимое запрещено:
критерий сверяет sha256.

## Зачем

Репозиторий публичный. Владелец решил 22.09.2026 расширять замер боевыми
целями из рабочих проектов — сайты мониторинга за Cloudflare, свои магазины
и соседи, соцсети за стеной логина, — но **список этих сайтов в публичный
репозиторий попасть не должен**. В гите остаются семь уже согласованных
целей `bench/targets/targets.toml`; новые живут в файле под `.gitignore`, а
наружу выходят только классы целей и агрегированные цифры.

Сейчас это невозможно сделать безопасно, и вот почему (проверено чтением
кода):

- `python3 -m bench report` печатает каждую ячейку `target:<id>` отдельным
  столбцом, а таблица «Окружение» содержит `egress_ip` и `asn`. Опубликовать
  такой отчёт по локальным целям — значит опубликовать их id (в id обычно
  зашито имя сайта) и адрес выхода.
- Сырые записи JSONL содержат `final_url` (домен цели), `target`, `cell`,
  `egress_ip`. Их коммитить нельзя вообще.
- `--targets` принимает один файл, поэтому публичные и локальные цели нельзя
  прогнать одним запуском с общей паузой между запросами к хостам.

Веха добавляет недостающее: несколько файлов целей в одном запуске, команду
`aggregate`, которая физически не умеет печатать ничего, кроме классов и
цифр, и места под локальные файлы, которые git игнорирует.

## Что проверено вживую, а что предположение

Проверено постановщиком на BASE:

- `bench/cli.py`: подкоманды `providers`, `plan`, `run`, `report`;
  `--targets` объявлен как `type=Path` без `nargs` и открывается одним
  `args.targets.open('rb')`; цели с `valid = false` пропускаются; дубль id
  внутри файла даёт `ValueError('duplicate target: …')`, а `main` превращает
  `OSError, ValueError, KeyError, TypeError` в `parser.error` — rc=2.
- `report --output` открывает файл режимом `'x'` — существующий не
  перезаписывается. Для `aggregate` нужно то же.
- `bench/report/build.py` выводит `egress_ip`/`asn` в таблицу окружения и id
  ячеек заголовками столбцов (строки 81–95).
- `RunRecord` (`bench/runner/record.py`) содержит поля `provider`, `target`
  (None у сценариев стенда), `cell`, `success`, `error_type`, `final_url`,
  `egress_ip`, `asn`. `FailureReason.not_measured` означает «попытки не было».
- Порядок провайдеров в `report` по умолчанию —
  `sorted(PROVIDERS, key=lambda p: p.tier)`; имена в реестре: `curl`,
  `curl_cffi`, `primp`, `playwright`, `patchright`, `scrapling`, `camoufox`,
  `pydoll`, `wayback`, `rss` (`python3 -m bench providers`).
- Классы в публичном `targets.toml`: `none`, `cloudflare`,
  `cloudflare+spa`, `login-wall`, `cloudflare-managed-challenge` — все
  подходят под шаблон из пункта 3 ниже. В тестовых целях `tests/test_cli.py`
  поля `class` нет — для `plan`/`run` оно обязано остаться необязательным.
- `.gitignore` на BASE не игнорирует ни `bench/targets/local.toml`, ни
  каталог прогонов.
- **Чекер `docs/specs/checks/m23_local_targets.py` достижим.** Постановщик
  написал в черновой копии эталонную реализацию пунктов 1–3 (около 60 строк)
  и прогнал чекер: `ok`. На BASE чекер падает по делу —
  `invalid choice: 'aggregate'`.
- Полный набор тестов на BASE: 658 unit-тестов и 125 замороженных проб
  зелёные на публичном образе Python из критерия AC-304.

Предположений о коде в спеке нет. **Предположение о данных:** классы новых
целей будут взяты из того же словаря, что в публичном файле; если понадобится
новый класс, он подчиняется тому же шаблону.

## Что сделать

### 1. Несколько файлов целей в `plan` и `run`

`--targets` принимает один или несколько путей (`nargs='+'`). Цели всех
файлов объединяются в порядке файлов; дубль id — и внутри файла, и между
файлами — прежняя ошибка `duplicate target`, rc=2. Всё остальное поведение
`plan`/`run` (пропуск `valid = false`, одна попытка на пару, пауза не меньше
30 с для целей) не меняется. Поле `class` для `plan`/`run` остаётся
необязательным.

### 2. Подкоманда `aggregate`

`python3 -m bench aggregate <jsonl> --targets <toml> [<toml> ...] [--order P ...] [--output PATH]`

- `--targets` обязателен, один или несколько файлов.
- `--order` — как у `report`, по умолчанию порядок по tier из реестра. В
  таблицу попадают только провайдеры, у которых в JSONL есть хотя бы одна
  запись о цели, в порядке `--order`.
- `--output` открывается режимом `'x'`, как у `report`; без него — stdout.
- Записи сценариев стенда (`target` равен null) игнорируются.

Счёт — по **целям**, а не по попыткам:

- цель считается *измеренной* провайдером P, если у пары (P, цель) есть
  хотя бы одна запись с `error_type` не `not_measured`;
- цель считается *взятой* провайдером P, если у этой пары есть хотя бы одна
  запись с `success = true`;
- ячейка «класс × провайдер» — `взято/измерено` по целям этого класса; если
  ни одна цель класса провайдером не измерена — текст `not measured`;
- `Targets` — число различных целей класса, встретившихся в JSONL;
- `Any provider` — число целей класса, взятых хотя бы одним провайдером,
  через дробь число целей класса, измеренных хотя бы одним провайдером.

Строки таблицы — классы по алфавиту. Заголовок и разделитель ровно такие:

```
| Class | Targets | <провайдер> | ... | Any provider |
|---|---|---|...|---|
```

Над таблицей допустимы заголовок и короткое пояснение на английском.
Никаких других таблиц, id целей, `target:`, адресов, доменов, IP и ASN в
выводе быть не может — ни при каком входе.

### 3. Класс цели и ошибки без эха

Для `aggregate` каждая цель в переданных файлах обязана иметь поле `class`,
подходящее под шаблон `^[a-z0-9]+(?:[+-][a-z0-9]+)*$` (строчные буквы и
цифры, части через `+` или `-`; точки запрещены — так класс не может нести
домен). Нарушение — rc=2.

Ошибки `aggregate` **не повторяют** значений из файлов и JSONL: ни id, ни
класса, ни адреса. Можно назвать имя файла и порядковый номер цели в нём
(«local.toml: target #2: class must match …»). Если в JSONL есть записи о
целях, которых нет в переданных файлах, — rc=2 с числом таких записей, без
их id.

### 4. Места под локальные файлы

- `.gitignore`: добавить `bench/targets/local.toml` и `bench/local-runs/`.
- `bench/targets/local.example.toml` — отслеживаемый образец формата:
  две-три цели с адресами только в зарезервированном домене `.example`
  (например `https://cloudflare-protected.example/`), комментарий со
  словарём классов и правилом из шапки `targets.toml`: строка `expect`
  берётся с настоящей страницы и не должна встречаться на
  странице-заглушке.

### 5. Документация

`bench/targets/README.md` на английском, коротко: публичные цели против
локальных; как прогнать обе вместе в каталог прогонов, например
`python3 -m bench run --targets bench/targets/targets.toml bench/targets/local.toml --output bench/local-runs/<date>.jsonl`;
как получить публикуемую сводку `python3 -m bench aggregate …`; прямое
предупреждение, что сырые JSONL и `report` по локальным целям не
коммитятся, а наружу идёт только вывод `aggregate`.

### 6. Тесты

Новый файл `tests/test_aggregate.py` (стиль — как `tests/test_cli.py`,
`unittest`, без сети):

- счёт на наборе, где есть `not_measured`, провал с измерением, успех
  только одного провайдера, сценарий стенда и два класса; сверка точных
  строк таблицы;
- `Any provider` отличается от любого отдельного провайдера хотя бы в одной
  строке теста — иначе мутация объединения не ловится;
- приватность: в выводе и в сообщениях об ошибках нет id, `target:`,
  доменов из `final_url`, `egress_ip`, `asn`;
- отказ по классу: точка, заглавные буквы, пустая строка, отсутствие поля,
  не строка; все пять классов публичного файла проходят;
- отказ по записям о неизвестных целях без эха id;
- `plan` с двумя файлами склеивает цели; дубль id между файлами — rc=2;
- `aggregate --output` не перезаписывает существующий файл.

### 7. Коммит

Всё закоммитить в ветке `m23-local-targets` вместе со спекой
`docs/specs/m23-local-targets.md` и чекером
`docs/specs/checks/m23_local_targets.py`. Сообщения короткие, в
повелительном наклонении.

## Не трогать

- `bench/targets/targets.toml` — публичный список целей не меняется.
- `bench/report/build.py` и поведение `report` — сводка живёт отдельно.
- `gateway/`, `scripts/`, `deploy/`, `README.md`, `docs/` (кроме файлов этой
  вехи), `TASKS.md`, `CHANGELOG.md`, `pyproject.toml`.
- Существующие тесты не ослаблять и не удалять.
- Ничего не публиковать наружу, не звать `gh`, не ходить в сеть: тесты и
  чекер работают на фикстурах.

🚨 **Новых доменов, IP-адресов и путей `/home/...` в отслеживаемых файлах
появиться не должно** — это проверяет гейт утечек M22. Для примеров
адресов — только `.example` и `.invalid` (оба зарезервированы и гейтом не
считаются доменами). Фикстуры тестов — те же зоны. **Литералов IPv4 в
тестах тоже не писать**: гейт сочтёт `a.b.c.d` в новом файле утечкой. Для
`egress_ip` в фикстурах бери не-IP метку (`egress-fixture`) или собирай адрес
из частей, как это сделано в чекере вехи.

## Критерии приёмки

- **AC-304.** Полный набор тестов и замороженные пробы зелёные на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-305.** Чекер вехи не изменён и печатает ok на публичном образе Python:
  `bash -c 'printf "%s\n" "5d53802ef094793ee6d572f1dbe9b679cbe8333aaadbbc1906f21f2a55b50ef0  docs/specs/checks/m23_local_targets.py" | sha256sum -c --quiet && test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/m23_local_targets.py)" = ok'`
- **AC-306.** Локальные файлы игнорируются, публичные — нет:
  `bash -c 'git check-ignore -q bench/targets/local.toml && git check-ignore -q bench/local-runs/run.jsonl && ! git check-ignore -q bench/targets/targets.toml && ! git check-ignore -q bench/targets/local.example.toml && git ls-files --error-unmatch bench/targets/local.example.toml bench/targets/README.md tests/test_aggregate.py >/dev/null'`
- **AC-307.** Гейт утечек M22 не изменён и зелёный:
  `bash -c 'printf "%s\n" "883cb84b6cc5fef8c47e207ba48572c21a177b5eb95687a26756020abeb746f2  docs/specs/checks/m22_no_new_domains.py" | sha256sum -c --quiet && test "$(python3 docs/specs/checks/m22_no_new_domains.py)" = ok'`
- **AC-308.** Изменения только в разрешённых путях, спека и чекер в истории, дерево чистое:
  `bash -c 'git diff --exit-code 013431853f942356bd5c4c346c54864f2fabb2d5 HEAD -- . ":(exclude)bench/cli.py" ":(exclude)bench/report/aggregate.py" ":(exclude)bench/targets/local.example.toml" ":(exclude)bench/targets/README.md" ":(exclude).gitignore" ":(exclude)tests/test_aggregate.py" ":(exclude)docs/specs/m23-local-targets.md" ":(exclude)docs/specs/checks/m23_local_targets.py" && git ls-files --error-unmatch docs/specs/m23-local-targets.md docs/specs/checks/m23_local_targets.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)tmp")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash ~/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone ~/exec-clones/abg-m23-local-targets-20260922 --base 013431853f942356bd5c4c346c54864f2fabb2d5 --range 013431853f942356bd5c4c346c54864f2fabb2d5..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial codex`. 22.09.2026 у Codex исчерпан лимит до
24.09, agy в тот же день шесть раз ответил 503 — при таких ошибках повторов
не делать, записать в note и продолжать. Если `accept_run.py` вернёт
`blocked` только из-за отсутствия ревью — это известное ограничение
оснастки, координатор принимает вручную: `report-blocked.md` не нужен,
достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-304…AC-308,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"013431853f942356bd5c4c346c54864f2fabb2d5","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"grok","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-304","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 ~/.claude/skills/executor-milestone/scripts/accept_run.py ~/exec-clones/abg-m23-local-targets-20260922 --spec ~/exec-clones/abg-m23-local-targets-20260922/docs/specs/m23-local-targets.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер требует поведения, противоречащего этой спеке; существующий тест
падает из-за требования спеки; нужна правка вне разрешённых файлов; для
примера нужен реальный домен. Спеку, чекеры, AC, BASE и оснастку приёмки не
менять, rc не выдумывать, наружу ничего не публиковать.

## Стыки с соседними вехами

Следом постановщик сам наполнит `bench/targets/local.toml` целями владельца
(сайты мониторинга за Cloudflare, магазины, соцсети), проверит строки
`expect` на живых страницах, прогонит замер и опубликует в README только
вывод `aggregate`. Эта веха обещает ему, что сводка не протечёт id и
адресами при любом содержимом локального файла.
