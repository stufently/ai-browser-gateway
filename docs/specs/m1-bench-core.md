# Веха M1 — ядро benchmark-харнесса (чистый Python, без сети и Docker)

| | |
|---|---|
| Репозиторий | `git@gitlab.example.org:9qw/ai-browser-gateway.git` |
| Дата | 06.09.2026 |
| Базовый коммит | `f551e10` «Add phase 1 research, plan and targets» |
| Исполнитель | **Grok** |
| Почему он | Веха целиком про измерительный контур и краевые случаи HTTP; Codex сегодня отработал заметно больше, балансировка квоты — законная причина. Мутации по этому коду будет гонять Codex. |

## Где работать

- Клон: `/home/user/exec-clones/abg-m1-bench-core`
- Ветка: `m1-bench-core` (создать от `main`)
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Постановщик кладёт в клон ДО запуска: ничего. Зависимостей у вехи нет —
  см. следующий раздел.

## Задача и почему

Проект выбирает стек доступа к веб-страницам по измеренным числам. Меряет —
харнесс, которого ещё нет. Эта веха делает его **ядро**: всё, что не требует ни
сети, ни Docker, ни браузера, и потому проверяемо целиком.

Ядро — это пять вещей:

1. **Нормализованный результат** одного запроса и таксономия отказов. Без него
   провайдеры несравнимы: каждый отдаёт своё.
2. **Правило успеха.** `HTTP 200` успехом НЕ считается — страница-заглушка
   Cloudflare тоже приходит с 200 и длиннее настоящей. Успех — найденный
   **sentinel**. Это центральный инвариант всей вехи.
3. **Двенадцать сценариев** стенда A и **WSGI-приложение**, которое их отдаёт.
   Приложение — обычная WSGI-функция, поэтому тестируется прямым вызовом
   `app(environ, start_response)`, **без единого сокета**.
4. **Счётчик incremental coverage** — главный выход всего замера: не «у кого
   success rate выше», а что этот провайдер добавляет к уже выбранным.
5. **Рендер отчёта** в Markdown и **запись прогонов** в JSONL.

Ломаться нечему: репозиторий содержит только документы, кода в нём нет.

## Что проверено вживую, а что предположение

Проверено на хосте 06.09.2026:

- `python3 -V` → `Python 3.14.4`. Критерии гоняются этим интерпретатором.
- `bash -c "false; echo EXIT:\$?"` → `rc=0` — поэтому ни одна команда критерия
  не заканчивается `echo`.
- `readlink -f /bin/sh` → `/usr/bin/dash` — поэтому все критерии в `bash -c`.
- `curl -fsS https://pypi.org/pypi/pytest/json` → `9.1.1`. **pytest в этой вехе
  НЕ используется:** у исполнителя нет сети, поставить его нечем. Тесты пишутся
  на стандартном `unittest` и запускаются `python3 -m unittest`. Классы
  `unittest.TestCase` позже подхватит и pytest, если он появится.

Предположение (проверить нечем, у исполнителя нет сети): что sentinel-подход
переживёт встречу с реальным Cloudflare. Это и есть предмет фазы 1, а не вехи M1.

## Что сделать

Всё — **только стандартная библиотека**. Никаких сторонних импортов.

### `pyproject.toml`
Метаданные пакета `ai-browser-gateway`, `requires-python = ">=3.12"`,
`dependencies = []`. Секции сборки достаточно `hatchling`-независимой: указать
`[build-system]` с `setuptools`. Точек входа в этой вехе не заводить.

### `bench/models.py`
- `FailureReason` — `enum.StrEnum` с членами: `none`, `dns_error`, `timeout`,
  `connection_error`, `tls_error`, `http_403`, `http_429`, `http_5xx`,
  `javascript_required`, `challenge_suspected`, `interactive_challenge`,
  `content_missing`, `content_mismatch`, `provider_error`.
- `ChallengeType` — `enum.StrEnum`: `none`, `suspected`, `javascript_required`,
  `interactive`, `captcha`, `rate_limited`, `access_denied`.
- `FetchResult` — `@dataclass(frozen=True, slots=True)`: `provider`,
  `provider_version`, `requested_url`, `final_url`, `status` (`int | None`),
  `html` (`str`), `text` (`str`), `elapsed_ms`, `startup_ms`, `cpu_ms`,
  `peak_rss_mb`, `bytes_received`, `redirects`, `error_type` (`FailureReason`),
  `challenge` (`ChallengeType`).
- `def evaluate(result: FetchResult, sentinel: str) -> tuple[bool, FailureReason]`
  — **правило успеха**, единственное место, где оно живёт:
  - `result.error_type is not FailureReason.none` → `(False, тот же error_type)`;
  - sentinel найден в `html` ИЛИ в `text` → `(True, FailureReason.none)`;
  - `status == 200`, sentinel не найден → `(False, FailureReason.content_missing)`;
  - `status == 403` → `(False, FailureReason.http_403)`; `429` → `http_429`;
    `5xx` → `http_5xx`; прочее → `content_mismatch`.
  Пустой sentinel — `ValueError`: «проверка без ожидания» это не успех, а дефект
  вызова.

### `bench/scenarios.py`
- `@dataclass(frozen=True, slots=True) Scenario`: `id`, `path`, `sentinel`,
  `requires_js: bool`, `expected_status: int`, `description`.
- `SCENARIOS: tuple[Scenario, ...]` — **ровно 12 штук**, по таблице
  `docs/BENCHMARK_PLAN.md` (статика, редиректы, компрессия, JS, SPA, iframe,
  закрытый Shadow DOM, сессия, отказы 403/429/503, медленный ответ, битый JS,
  большой DOM). Sentinel каждого — вида `ABG_TEST_<ИМЯ>_OK`, **все различны**.
- `def by_id(scenario_id: str) -> Scenario` — `KeyError` на неизвестном.
- Сценарий отказов (`403/429/503`) — `expected_status` берётся из под-пути;
  у него sentinel есть, но отдаётся ТОЛЬКО на сопутствующей странице-объяснении,
  чтобы «успех» на нём был невозможен по построению.

### `bench/server/app.py`
- `def build_app(*, session_store: dict | None = None) -> WSGIApp` — фабрика,
  чтобы тест мог подсунуть своё хранилище сессий и не зависеть от глобалей.
- Приложение маршрутизирует пути сценариев и отдаёт для каждого детерминированный
  байт-в-байт ответ. Обязательные свойства, каждое проверяется тестом:
  - **JS-сценарий**: sentinel **отсутствует** в первичном HTML и появляется
    только из `<script>`. То же для SPA, iframe, Shadow DOM (закрытого — через
    `attachShadow({mode: "closed"})`), битого JS.
  - **Редиректы**: цепочка из трёх `302` и только затем страница с sentinel.
  - **Компрессия**: `gzip` и `br` по `Accept-Encoding`; при отсутствии
    поддержки — идентичное тело без сжатия. Brotli в стандартной библиотеке
    НЕТ — если модуля нет, `br` не анонсируется и не отдаётся, а сценарий
    честно помечает это в описании. Выдумывать сжатие нельзя.
  - **Сессия**: `/session/start` ставит `Set-Cookie`, `/session/check` отдаёт
    sentinel только при валидной куке, иначе `401`.
  - **Медленный ответ**: задержка берётся из query-параметра и по умолчанию `0`,
    чтобы тесты не спали.
  - **Большой DOM**: размер узлов — из query-параметра, дефолт маленький.
- Никаких сокетов, `socket`, `http.server`, `requests`, `urllib.request` в
  `bench/` быть не должно.

### `bench/server/__main__.py`
Запуск через `wsgiref.simple_server` для ручного прогона стенда. Тестами не
покрывается — это единственный файл вехи, который открывает сокет.

### `bench/runner/record.py`
- `@dataclass(frozen=True, slots=True) RunRecord` со всеми полями из раздела
  «Что записывается» в `docs/BENCHMARK_PLAN.md`, плюс `run_id`, `mode`
  (`"cold" | "warm"`), `cell` (строка `"<scenario|target>:<id>"`).
- `def to_jsonl_line(record) -> str` и `def from_jsonl_line(line) -> RunRecord`.
- `def validate(record) -> None` — `ValueError` с внятным текстом, если поле
  отсутствует, `mode` не из двух допустимых, `elapsed_ms` отрицателен или
  `success=True` при `error_type != none`.

### `bench/report/coverage.py`
- `def solved_cells(records) -> dict[str, set[str]]` — провайдер → множество
  взятых ячеек.
- `def incremental(records, order: list[str]) -> list[CoverageRow]`, где
  `CoverageRow` — `provider`, `solved`, `incremental`, `unique`, `total_cells`.
  `incremental` — ячейки, которых не взял НИКТО из провайдеров, стоящих раньше
  в `order`. `unique` — ячейки, которые взял ТОЛЬКО этот провайдер, независимо
  от порядка.
- `def keep_decision(row, threshold: float = 0.05) -> tuple[bool, str]` —
  оставлять ли провайдера: `True` при `incremental / total_cells >= threshold`
  ЛИБО при `unique > 0`; во втором элементе — причина словами. Порог параметр,
  а не константа в коде.
- Провайдер, отсутствующий в `order`, — `ValueError`.

### `bench/report/render.py`
- `def render_markdown(rows, *, unmeasured: list[str] = []) -> str` — таблица с
  колонками `Провайдер | Взял | Incremental | Unique | Решение`.
- Провайдеры из `unmeasured` (платные API) идут отдельной секцией, и в колонке
  результата у них стоит буквально `не измерено`. **Подставлять туда число
  запрещено** — это требование владельца и оно проверяется тестом.

### Тесты (`tests/`, `unittest`)
`test_models.py`, `test_scenarios.py`, `test_server_app.py`, `test_record.py`,
`test_coverage.py`, `test_render.py`. Проверяют минимум:
успех только по sentinel и никогда по `200`; уникальность двенадцати sentinel;
отсутствие sentinel в первичном HTML у JS/SPA/iframe/ShadowDOM-сценариев;
цепочку редиректов; сессию с кукой и без; `401`/`403`/`429`/`503`;
round-trip JSONL; отказ `validate` на каждом описанном случае; арифметику
incremental и unique на фикстуре, посчитанной руками; отказ `render_markdown`
подставлять число в строку «не измерено».

### `tests/mutation_gate.py`
Скрипт-обвязка, доказывающая, что тесты выше **действительно ловят поломку**.
Порядок шагов внутри обязателен:

1. сохранить исходные байты файла и его `sha256`;
2. прогнать целевой тест на ЧИСТОМ дереве и убедиться, что он ЗЕЛЁНЫЙ;
3. проверить, что заменяемый фрагмент встречается в файле РОВНО ОДИН раз;
4. наложить мутацию и прогнать ИМЕННО целевой тест;
5. откатить файл из сохранённых байтов в `finally` и сверить `sha256`;
6. вернуть 0, только если КАЖДЫЙ мутант убит: тест был зелёным до, упал после,
   и упал на СВОЕЙ строке ассерта (сверять дословно).

Печатать по каждой мутации «убит/выжил» и первую упавшую строку. Обязательный
набор мутаций — шесть:

| # | Файл | Мутация | Кто обязан убить |
|---|---|---|---|
| 1 | `models.py` | успех при `status == 200` без sentinel | тест правила успеха |
| 2 | `coverage.py` | `incremental` перестаёт вычитать уже взятые ячейки | тест арифметики incremental |
| 3 | `coverage.py` | `unique` считает ячейки с числом решателей `>= 1` | тест unique |
| 4 | `scenarios.py` | два sentinel сделаны одинаковыми | тест уникальности sentinel |
| 5 | `server/app.py` | sentinel JS-сценария попадает в первичный HTML | тест «в сыром HTML sentinel нет» |
| 6 | `render.py` | вместо `не измерено` подставляется число | тест платной строки |

Все переменные окружения, влияющие на прогон, обвязка задаёт ЯВНО.

## Не трогать

- `docs/` — кроме единственного исключения ниже.
- **Исключение:** `docs/specs/m1-bench-core.md` приезжает в клон untracked и
  **коммитится вместе с работой**. Без этого критерий чистоты дерева недостижим.
- `README.md`, `TASKS.md`, `bench/targets/targets.toml` — не редактировать.
- Никаких `.github/workflows/` — у проекта их нет намеренно.
- Не добавлять сторонние зависимости. Ни одной.

## Критерии приёмки

- **AC-001 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -m unittest discover -s tests -t . -q'`

- **AC-002 — ни одной сторонней зависимости.** Каждый модуль импортируется голым
  системным интерпретатором.
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -c "import bench.models, bench.scenarios, bench.server.app, bench.runner.record, bench.report.coverage, bench.report.render"'`

- **AC-003 — состав работы.** Все ожидаемые файлы под контролем git.
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && git ls-files --error-unmatch pyproject.toml bench/models.py bench/scenarios.py bench/server/app.py bench/server/__main__.py bench/runner/record.py bench/report/coverage.py bench/report/render.py tests/test_models.py tests/test_scenarios.py tests/test_server_app.py tests/test_record.py tests/test_coverage.py tests/test_render.py tests/mutation_gate.py docs/specs/m1-bench-core.md >/dev/null'`

- **AC-004 — ровно двенадцать сценариев с различными sentinel.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 -c "from bench.scenarios import SCENARIOS as S; assert len(S)==12, len(S); assert len({x.sentinel for x in S})==12"'`

- **AC-005 — ядро не открывает сокетов.** В `bench/` нет ни одного импорта
  сетевого модуля, кроме единственного разрешённого файла запуска стенда.
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && ! grep -rnE "^[[:space:]]*(import|from)[[:space:]]+(socket|http\.client|urllib\.request|requests|httpx)" bench/ --include=*.py | grep -v "^bench/server/__main__.py:"'`

- **AC-006 — мутационный гейт: все шесть мутантов убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && python3 tests/mutation_gate.py'`

- **AC-007 — дерево чистое после прогона гейта.**
  `bash -c 'cd /home/user/exec-clones/abg-m1-bench-core && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

Положить в корень клона `report.json`:

```json
{"criteria": [{"id": "AC-001", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

Записей ровно семь — по одной на каждый критерий. `blocked` — штатный исход,
когда среда не даёт выполнить критерий: тогда `"rc": null`, в `command` —
команда-улика, в `note` — дословная ошибка.

## Контракт на невыполнимое

Если требование вехи невыполнимо или противоречиво — **остановись и доложи**.
Обходить несовместимость запрещено: `|| true`, `set +e`, `--no-deps`,
`--break-system-packages`, подмена интерпретатора, ослабление проверки под тест.
Честная остановка с объяснением дороже зелёного отчёта.

Отдельно: если окажется, что brotli недоступен в стандартной библиотеке этого
интерпретатора — это не повод ставить пакет. Не анонсировать `br`, записать
ограничение в описание сценария и сказать об этом в отчёте.

## Стыки с соседними вехами

Следующая веха берёт контракт провайдера в контейнере и первые HTTP-образы
(`curl`, `httpx`, `curl_cffi`) и прогоняет ими весь стенд A. Эта веха обещает ей:
стабильный `FetchResult`, единственное место с правилом успеха (`evaluate`),
двенадцать сценариев с уникальными sentinel, WSGI-приложение, поднимаемое
`python3 -m bench.server`, и формат JSONL, в который следующая веха только пишет.
