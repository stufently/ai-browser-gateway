# Веха M2 — воспроизводимый раннер и контракт провайдера в контейнере

| | |
|---|---|
| Репозиторий | `git@gitlab.example.org:9qw/ai-browser-gateway.git` |
| Дата | 06.09.2026 |
| Базовый коммит | `fe37d7c` «Mark M1 accepted in work log» |
| Исполнитель | **Codex** |
| Почему он | Веха M1 написана Grok'ом и опирается на его контракты; свежий взгляд на них полезнее авторского. Мутации по коду этой вехи будет гонять Grok. |

## Где работать

- Клон: `/home/user/exec-clones/abg-m2-runner`, ветка `m2-runner` от `main`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Постановщик кладёт в клон до запуска только эту спеку
  (`docs/specs/m2-runner.md`, untracked). Зависимостей нет: стандартная библиотека,
  тесты `python3 -m unittest` (на хосте Python 3.14.4).

## Задача и почему

Фаза 1 уже дала числа, но получены они **черновыми одноразовыми скриптами вне
репозитория**. Такие числа невоспроизводимы: их нельзя перепрогнать после смены
egress, после появления прокси, через месяц. Веха превращает эти черновики в
раснер, который живёт в репозитории.

Что ломается: ничего. Код M1 не переписывается, только используется.

## Что проверено вживую, а что предположение

Проверено 06.09.2026 постановщиком, руками:

- Все четыре браузерных образа собраны и работают под `--user 1002:1002`:
  ванильный Playwright, patchright с настоящим Google Chrome headful под Xvfb,
  camoufox, pydoll.
- 🚨 **`xvfb-run` в роли ENTRYPOINT зависает молча.** Это shell-скрипт, ждущий
  SIGUSR1 от X-сервера, и под PID 1 handshake не завершается: контейнер висит без
  единой строки вывода. Лечится `ENTRYPOINT ["/usr/bin/tini","-g","--","xvfb-run",…]`.
  Рядом: `xauth` — только Recommends пакета `xvfb`, а `xvfb-run` зовёт его
  безусловно; `/tmp/.X11-unix` нужно создать самому с правами 1777.
- Стенд A поднимается `python3 -m bench.server` и отдаёт все 12 сценариев;
  `curl` берёт 5 из 12, браузеры больше.
- Формат `RunRecord` и `to_jsonl_line`/`from_jsonl_line` из M1 уже проверены на
  реальных 30 записях: `incremental()` читает их генератором и считает покрытие.

Предположение (у исполнителя нет ни Docker, ни сети, проверить нечем): что
контейнеры действительно запустятся из написанных им дескрипторов. **Сборку
образов и живой прогон проверяет постановщик**, критериями вехи это не покрыто —
и это осознанно, а не забыто.

## Что сделать

Только стандартная библиотека. Сторонних зависимостей по-прежнему ноль.

### `bench/providers/registry.py`
- `@dataclass(frozen=True, slots=True) Provider`: `name`, `image`, `tier` (int,
  0 = дешевле всего), `kind` (`"http" | "browser" | "entrance"`), `needs_network`
  (bool), `argv_extra` (tuple[str, ...]).
- `def build_argv(provider, *, url, sentinel, network=None) -> list[str]` — строит
  полную командную строку `docker run`. Обязательно: `--rm`, `--user 1002:1002`,
  `--shm-size=1g` для браузерных, `--network host` **только** когда `network`
  задан (прогон против локального стенда), образ, затем `url` и `sentinel`.
  Никаких `-v` на дерево репозитория.
- `def parse_output(provider, stdout: str) -> dict` — берёт **последнюю** строку,
  начинающуюся с `{`, и разбирает её как JSON. Пусто или не JSON — `ValueError` с
  первыми 200 символами вывода в тексте ошибки, а не голый трейсбек.
- `PROVIDERS: tuple[Provider, ...]` — реестр: `curl`, `curl_cffi`, `primp`
  (kind `http`, tier 0–1); `playwright`, `patchright`, `camoufox`, `pydoll`
  (kind `browser`, tier 2–3); `wayback` (kind `entrance`, tier 0).
- `def by_name(name) -> Provider` — `KeyError` на неизвестном.

### `bench/runner/matrix.py`
- `def build_plan(providers, cells, *, cold: int, warm: int) -> list[PlanItem]`,
  где `PlanItem` — `provider`, `cell`, `mode`, `index`.
- HTTP-провайдеры холодного и тёплого режима не различают: для `kind == "http"`
  выдавать только `cold`, иначе получится `warm`, которого в реальности нет.
  Для `kind == "browser"` — `cold` штук в режиме `cold` и `warm` в режиме `warm`.

**Что такое `warm` — определение, а не вкус.** Контракт «один `docker run` на
элемент плана» сохраняется; режим передаётся пробнику флагом.

- `cold` — таймер включает **запуск процесса браузера**. Это цена первого запроса
  после подъёма пода.
- `warm` — браузер уже поднят, открыт `about:blank`, таймер включается **после**
  старта, и цель грузится ОДИН раз. Кэш и сессия самой цели при этом холодные.

Именно так выглядит прод: в шлюзе живёт пул браузеров, процесс переиспользуется, а
URL у каждого запроса свой. Вариант «загрузить цель дважды и померить вторую
загрузку» меряет кэш ЦЕЛИ, которого в проде не будет, и потому запрещён. Общая
сессия между элементами плана тоже не годится: она ломает контракт запуска и
переносит состояние между замерами.
- `run_id` формируется как `f"{provider}:{cell}:{mode}:{index}"` и обязан быть
  уникальным в пределах плана.

### `bench/runner/execute.py`
- `class Launcher(Protocol)`: `def run(self, argv: list[str], timeout: int) -> tuple[int, str, str]`.
- `class DockerLauncher` — реализация через `subprocess.run`. Единственное место
  вехи, которое трогает внешний мир; тестами не покрывается.
- `def execute_plan(plan, *, launcher, cells, env, timeout=180, pause_s=0.0, sleep=None) -> list[RunRecord]`
  — гоняет план и собирает `RunRecord` из M1. `sleep` инъектируется, чтобы тесты
  не спали. `cells` — отображение имени ячейки в `{url, sentinel}`.
- Отказ провайдера (ненулевой код, пустой вывод, таймаут) обязан стать записью с
  `success=False` и осмысленным `error_type`, а НЕ исключением: провалившийся
  провайдер — это данные, ради которых замер и делается.
- **Пауза между запросами к одной и той же цели — не меньше `pause_s`.** Значение
  по умолчанию 0 в тестах и 20 в CLI: чужие сайты долбить нельзя.

### `bench/runner/environment.py`
- `def collect(*, reader) -> dict` — метаданные воспроизводимости: `date`,
  `kernel`, `docker_version`, `egress_ip`, `asn`. `reader` инъектируется, чтобы
  тесты не ходили ни в сеть, ни в `docker`.
- Значение, которое собрать не удалось, кладётся как строка `"unknown"`. **Ни
  одно поле нельзя выдумать**: неизвестный egress должен быть виден как
  неизвестный, потому что от него зависит трактовка всей таблицы.

### `bench/report/build.py`
- `def build_report(jsonl_path, *, order, threshold=0.05, unmeasured=()) -> str` —
  читает JSONL **потоком** (генератором, не списком), считает покрытие кодом M1 и
  возвращает Markdown: блок метаданных окружения, матрица «провайдер × ячейка»,
  медиана и p95 задержки, пиковый RSS, затем таблица incremental coverage.
- Провайдер, встреченный в журнале, но не указанный в `order`, обязан привести к
  `ValueError` — это уже поведение `incremental()` из M1, не ослаблять его.

### `bench/cli.py` и `bench/__main__.py`
Подкоманды: `providers` (список реестра), `plan` (печать плана без запуска),
`run` (прогон, пишет JSONL), `report` (JSONL → Markdown). Парсинг аргументов —
`argparse`, отдельной функцией `build_parser()`, чтобы он тестировался без запуска.

### `bench/providers/docker/`
Dockerfile'ы для семи провайдеров и общий `probe.py` с единым контрактом:
`probe.py <url> <sentinel> [--mode cold|warm]` печатает ОДНУ строку JSON с полями
`ok`, `status`,
`final_url`, `bytes`, `sentinel`, `challenge`, `title`, `startup_ms`,
`elapsed_ms`, `peak_rss_mb`, `cpu_ms`, `err`. В режиме `warm` пробник поднимает
браузер, открывает `about:blank`, и только потом включает таймер — `startup_ms` в
`elapsed_ms` не входит.

Обязательные факты, добытые постановщиком, — соблюсти дословно:
- браузерные образы с Xvfb: `ENTRYPOINT ["/usr/bin/tini","-g","--","xvfb-run","-a",…]`,
  пакеты `xvfb xauth tini`, `mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix`;
- Playwright: `ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` и `chmod -R a+rX`,
  иначе браузер невидим не-root пользователю;
- pydoll: `binary_location`, `headless=True`, `start_timeout=60`; его
  `execute_script` возвращает **конверт CDP**, значение лежит в
  `["result"]["result"]["value"]`;
- primp: единственный валидный профиль — голый `chrome`; любое `chrome_NNN`
  **молча** подменяется на `random` (проверено на 133/136/137/139/140).
  Профиль пинить и при неизвестном имени падать, а не продолжать.

### Тесты
`tests/test_registry.py`, `tests/test_matrix.py`, `tests/test_execute.py`
(с поддельным `Launcher`), `tests/test_environment.py` (с поддельным `reader`),
`tests/test_report_build.py` (на фикстуре JSONL), `tests/test_cli.py`.
Плюс мутации в `tests/mutation_gate.py` — **не меньше шести новых**, поверх
семнадцати имеющихся, минимум по одной на: `build_argv` (пропал `--user`),
`build_plan` (warm выдан HTTP-провайдеру), `execute_plan` (отказ поднят
исключением вместо записи), `parse_output` (взята первая строка вместо
последней), `collect` (пропущенное поле подставлено правдоподобным вместо
`unknown`), `build_report` (журнал прочитан списком, а не потоком).

## Не трогать

- `bench/models.py`, `bench/scenarios.py`, `bench/server/`, `bench/report/coverage.py`,
  `bench/report/render.py`, `bench/runner/record.py` — контракты вехи M1. Нужна
  правка — **остановись и доложи**, не меняй молча.
- Существующие 75 тестов и 17 мутаций — не удалять и не ослаблять.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/`, `bench/targets/targets.toml`.
- `docs/specs/m2-runner.md` — исключение: приезжает untracked и **коммитится
  вместе с работой**.
- Никаких `.github/workflows/`. Никаких сторонних зависимостей.
- **Никаких выдуманных чисел.** В коде и тестах не должно появиться ни одного
  «примерного» замера: числа в этот проект попадают только из прогона.

## Критерии приёмки

- **AC-201 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -m unittest discover -s tests -t . -q'`

- **AC-202 — мутационный гейт: не меньше 23 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=23 else 1)" && python3 tests/mutation_gate.py'`

- **AC-203 — ни одной сторонней зависимости.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "import bench.providers.registry, bench.runner.matrix, bench.runner.execute, bench.runner.environment, bench.report.build, bench.cli"'`

- **AC-204 — контракты M1 не тронуты.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && git diff --quiet fe37d7c..HEAD -- bench/models.py bench/scenarios.py bench/server bench/report/coverage.py bench/report/render.py bench/runner/record.py'`

- **AC-205 — HTTP-провайдер не получает режим warm.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
plan = build_plan([by_name(\"curl\"), by_name(\"playwright\")], [\"target:x\"], cold=2, warm=3)
modes = {(i.provider, i.mode) for i in plan}
assert (\"curl\", \"warm\") not in modes, modes
assert (\"playwright\", \"warm\") in modes, modes
assert len({i.run_id for i in plan}) == len(plan)
"'`

- **AC-206 — отказ провайдера становится записью, а не исключением.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
from bench.runner.execute import execute_plan
class Dead:
    def run(self, argv, timeout): return (1, \"\", \"boom\")
cells = {\"target:x\": {\"url\": \"https://example.invalid/\", \"sentinel\": \"S\"}}
plan = build_plan([by_name(\"curl\")], [\"target:x\"], cold=1, warm=0)
records = execute_plan(plan, launcher=Dead(), cells=cells, env={}, sleep=lambda s: None)
assert len(records) == 1, records
assert records[0].success is False
"'`

- **AC-207 — состав работы.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && git ls-files --error-unmatch docs/specs/m2-runner.md bench/providers/registry.py bench/runner/matrix.py bench/runner/execute.py bench/runner/environment.py bench/report/build.py bench/cli.py bench/__main__.py bench/providers/docker/probe.py >/dev/null'`

- **AC-208 — дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно восемь — по одной на критерий:

```json
{"criteria": [{"id": "AC-201", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

🚨 Строку `command` копируй из спеки **дословно**. В прошлой вехе исполнитель
перекавычил её при переносе в отчёт, и критерий упал с `rc=127` на пустом месте
при полностью исправной работе.

## Контракт на невыполнимое

Требование невыполнимо или противоречит контрактам M1 — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, `--no-deps`, ослабление проверки под
тест, правка файлов из «Не трогать».

Отдельно: Docker и сети у тебя нет. **Не пытайся собрать образы и не выдумывай
результаты их запуска.** Dockerfile'ы пишутся по фактам из раздела «Что проверено
вживую»; их сборку и живой прогон делает постановщик.

## Стыки с соседними вехами

Веха обещает следующей: реестр провайдеров, план прогона, исполнение через
инъектируемый `Launcher`, метаданные окружения и сборку отчёта из JSONL. Следующая
веха берёт обходные входы (архив с возрастом снимка, RSS, sitemap, JSON-эндпоинты)
как полноценный класс провайдеров и добавляет поддержку прокси в `build_argv`.
