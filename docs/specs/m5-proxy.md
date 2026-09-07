# Веха M5 — прокси и отличие «сломались мы» от «не пустила цель»

| | |
|---|---|
| Репозиторий | `git@gitlab.example.org:9qw/ai-browser-gateway.git` |
| Дата | 07.09.2026 |
| База | клон снимается с `main`; критерии сравнивают `main..HEAD`, ветку `main` в клоне не двигать |
| Исполнитель | **Grok** |
| Почему он | M4 писал Codex; ревью и перекрёстные мутации по этой вехе пойдут к Codex. |

## Где работать

- Клон: `/home/user/exec-clones/abg-m5-proxy`, ветка `m5-proxy` от `main`.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Спека уже в дереве, редактировать её не нужно.
- Зависимостей нет: стандартная библиотека, `python3 -m unittest`.
- Ни сети, ни Docker у тебя нет. Всё проверяемое — на поддельных объектах.

## Задача и почему

`bench/escalate.py` умеет говорить `change_egress`, но выполнить этот шаг нечем.
При этом смена адреса — **главный неизмеренный вопрос фазы 1**: наш хост сидит на
хостинговом ASN без репутации (`AS206996 ZAP-Hosting`), и отличить «инструмент не
справился» от «адрес не пустили» без второго egress нельзя. У соседнего проекта
владельца это уже измерено: один образ, один отпечаток, разные адреса — 200 и 403.

Кредов прокси **ещё нет**. Веха готовит код и стенд, а строки без кредов остаются
`not_measured` — состояние, введённое в M4, а не пустота.

Вторая половина вехи — из живого прогона M4. Первый заход дал `provider_error` у
обоих обходных входов, и причина была не в цели, а в постановщике: образы
собраны с тегом `:m2`, а реестр называет `:m4`. По записи «образ не собран» и
«пробник упал» неотличимы, хотя первое чинится за минуту и не говорит о мире
ничего, а второе — результат замера. Это тот же класс, ради которого в M4 введён
`not_measured`.

## Что проверено вживую, а что предположение

Проверено постановщиком 07.09.2026:

1. **`docker run --env ИМЯ` (без `=значение`) подставляет значение из окружения
   вызывающего, и значение НЕ появляется в argv.** Проверено: `ps -o args=` по
   PID контейнера показывает только `sleep 5`.
2. **`docker inspect` значение показывает** (`.Config.Env`). То есть любой в
   группе `docker` его прочитает. На этом хосте группа `docker` и так
   равносильна root, так что новой дыры это не создаёт, **но креды не должны
   попадать ни в argv, ни в запись прогона, ни в отчёт, ни в git**.
3. **Параметры прокси у провайдеров** (проверено вызовом в самих образах):
   - `curl_cffi`: `Session.request` принимает `proxy` и `proxy_auth`;
   - `primp`: `primp.Client(impersonate=…, proxy=…)` — аргумент принимается;
   - `playwright` (и `patchright`, `camoufox` поверх него):
     `BrowserType.launch` имеет параметр `proxy`;
   - `curl` (CLI): ключ `--proxy`;
   - `pydoll`: флаг chromium `--proxy-server=…`, адаптер уже умеет
     `options.add_argument`.
4. **Коды возврата Docker.** `docker run` отдаёт `125`, когда не смог запустить
   контейнер (образа нет, неверный ключ), `126`/`127` — когда команда в
   контейнере не исполняема или не найдена. Всё это — наша сборка, а не цель.

Предположения, помеченные как предположения:

- Что прокси реально меняет вердикт Cloudflare, **не измерено и в этой вехе не
  меряется**. Никаких чисел про эффект прокси в код, тесты и документы не
  попадает.
- Формат кредов GoldProxy неизвестен. Поэтому конфиг описывает профиль
  универсально: `url` целиком, как его дают провайдеру.

## Что сделать

### 1. Профили прокси из файла вне репозитория

Файл `~/.config/abg/proxies.toml`, права `0600`, **в git не попадает никогда**:

```toml
[profile.gold]
url = "http://ЛОГИН:ПАРОЛЬ@host:port"
note = "GoldProxy, резидентный"

[profile.direct]
url = ""            # пустая строка = ходить напрямую
```

Модуль `bench/egress.py`:

```python
def load_profiles(path) -> dict[str, str]:
    """Имя профиля -> URL. Файла нет — пустой словарь, это не ошибка."""

def profile_url(profiles, name) -> str | None:
    """None означает «профиля нет или он пуст» — то есть НЕ ИЗМЕРЕНО."""
```

Требования:

- Файла нет, профиля нет, `url` пуст ⇒ `None`. Это `not_measured`, а не отказ.
- 🚨 **Модуль обязан отказаться читать файл с правами шире `0600`** — сообщением
  об ошибке, а не молча. Секрет, читаемый группой, уже не секрет.
- Ни одна функция модуля не печатает `url` и не кладёт его в исключение.

### 2. Прокси доезжает до контейнера через окружение, а не через argv

`bench/providers/registry.py`, `build_argv(...)` получает необязательный
`proxy_env: str | None` — **имя переменной**, не значение:

```python
if proxy_env is not None:
    argv.extend(['--env', proxy_env])     # именно так: без '=' и без значения
```

`bench/runner/execute.py` кладёт значение в окружение процесса-раннера под этим
именем (`ABG_PROXY`) и передаёт `launcher`. Значение в `argv` не появляется
никогда — на это есть критерий.

Пробник читает `ABG_PROXY` и настраивает клиент:

| Провайдер | Как |
|---|---|
| `curl` | `--proxy $ABG_PROXY` |
| `curl_cffi` | `requests.get(..., proxy=…)` |
| `primp` | `primp.Client(impersonate='chrome', proxy=…)` |
| `playwright`, `patchright`, `camoufox` | `launch(proxy={'server': …})` |
| `pydoll` | `options.add_argument('--proxy-server=…')` |
| `wayback`, `rss` | `ProxyHandler` из `urllib.request` |

Переменная пуста или не задана ⇒ ходим напрямую, как сейчас.

### 3. Запись знает, каким выходом ходили

`bench/runner/record.py` — **одно** новое поле `egress_profile: str`, по
умолчанию `"direct"`. В нём **имя профиля**, никогда не URL.

CLI: `python3 -m bench run --egress <имя профиля>`. Профиля нет или он пуст —
все клетки прогона получают `not_measured` с `egress_profile` = запрошенное имя;
контейнеры при этом **не запускаются**.

### 4. «Сломались мы» отделяется от «не пустила цель»

`bench/models.py` — **одно** новое значение `FailureReason.environment_error`:
наша сборка или окружение, а не поведение цели.

`bench/runner/execute.py`: код возврата `125`, `126` или `127` от запуска даёт
`environment_error`, а не `provider_error`. Остальные ненулевые коды и разбор
вывода — как сейчас.

`bench/escalate.py`: `environment_error` ⇒ `Step.investigate` (как и
`provider_error`; шаг тот же, но причина в записи теперь разная).

### 5. Тесты

- `bench/egress.py`: нет файла; нет профиля; пустой `url`; **права шире `0600`
  ⇒ отказ**; ни одно сообщение об ошибке не содержит подстроку из `url`.
- `build_argv`: с профилем в argv появляется `--env ABG_PROXY` и **не появляется
  само значение**; без профиля `--env` нет вовсе.
- `execute_plan`: запрошен профиль, которого нет ⇒ запись `not_measured`,
  `egress_profile` = запрошенное имя, поддельный `Launcher` **не вызван ни разу**.
- `execute_plan`: коды `125`, `126`, `127` дают `environment_error`; код `1`
  по-прежнему `provider_error`.
- `escalate`: `environment_error` ⇒ `investigate`.
- `record`: `egress_profile` проходит JSONL в обе стороны; запись с профилем
  `gold` **не содержит** URL ни в одном поле.
- Отчёт: в метаданных прогона видно имя профиля; URL не печатается никогда.

Мутации в `tests/mutation_gate.py` — **не меньше семи новых** поверх 72, минимум
по одной на: проверку прав файла; `None` вместо URL при пустом профиле; форму
`--env ИМЯ` без значения; отсутствие профиля даёт отказ вместо `not_measured`;
запуск контейнера при отсутствующем профиле; границу кодов `125…127`; строку
`environment_error` в `next_step`.

## Не трогать

- `bench/scenarios.py`, `bench/server/`, `bench/report/coverage.py`,
  детектор челленджа в `probe.py` (`detect_challenge`, `RULE_PROVENANCE`,
  `_decisive_title`, таблицы правил), адаптеры `wayback` и `rss` в части разбора
  снимка и дат — контракты вех M1–M4.
- `bench/models.py` — **ровно одно** изменение: `environment_error`.
- `bench/runner/record.py` — **ровно одно** изменение: `egress_profile`.
- Существующие 231 тест и 72 мутации — не удалять и не ослаблять.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/` — **не трогать
  вообще**: журнал и чейнджлог пишет координатор.
- Ветку `main` в клоне не двигать.
- 🚨 **Ни одного настоящего креда, адреса прокси или пароля** — ни в коде, ни в
  тестах, ни в примерах. Только очевидные заглушки вида
  `http://user:pass@proxy.invalid:8080`.
- Никаких `.github/workflows/`. Никаких сторонних зависимостей.

## Критерии приёмки

- **AC-501 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -m unittest discover -s tests -t . -q'`

- **AC-502 — мутационный гейт: не меньше 79 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=79 else 1)" && python3 tests/mutation_gate.py'`

- **AC-503 — значение прокси не попадает в argv.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
from bench.providers.registry import by_name, build_argv
argv = build_argv(by_name(\"curl\"), url=\"https://example.invalid/\", sentinel=\"S\", proxy_env=\"ABG_PROXY\")
assert \"--env\" in argv and \"ABG_PROXY\" in argv, argv
assert not any(\"@\" in part or \"proxy.invalid\" in part for part in argv), argv
assert not any(part.startswith(\"ABG_PROXY=\") for part in argv), argv
plain = build_argv(by_name(\"curl\"), url=\"https://example.invalid/\", sentinel=\"S\")
assert \"--env\" not in plain, plain
"'`

- **AC-504 — профиля нет ⇒ «не измерено», контейнер не запускается.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
from bench.models import FailureReason
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
from bench.runner.execute import execute_plan
class Dead:
    def __init__(self): self.calls = []
    def run(self, argv, timeout): self.calls.append(argv); raise AssertionError(\"must not launch\")
cells = {\"target:x\": {\"url\": \"https://example.invalid/\", \"sentinel\": \"S\"}}
plan = build_plan([by_name(\"curl\")], cells, cold=1, warm=0)
launcher = Dead()
records = execute_plan(plan, launcher=launcher, cells=cells, env={}, egress=(\"gold\", None))
assert launcher.calls == [], launcher.calls
assert records[0].error_type is FailureReason.not_measured, records[0].error_type
assert records[0].egress_profile == \"gold\", records[0].egress_profile
"'`

- **AC-505 — коды 125/126/127 это наше окружение, а не поведение цели.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
from bench.models import FailureReason
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
from bench.runner.execute import execute_plan
cells = {\"target:x\": {\"url\": \"https://example.invalid/\", \"sentinel\": \"S\"}}
class Fixed:
    def __init__(self, rc): self.rc = rc
    def run(self, argv, timeout): return (self.rc, \"\", \"boom\")
for rc, expected in ((125, FailureReason.environment_error), (126, FailureReason.environment_error),
                     (127, FailureReason.environment_error), (1, FailureReason.provider_error)):
    plan = build_plan([by_name(\"curl\")], cells, cold=1, warm=0)
    got = execute_plan(plan, launcher=Fixed(rc), cells=cells, env={})[0].error_type
    assert got is expected, (rc, got)
"'`

- **AC-506 — файл кредов с широкими правами не читается.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import os, tempfile, pathlib
from bench.egress import load_profiles
directory = pathlib.Path(tempfile.mkdtemp())
path = directory / \"proxies.toml\"
path.write_text(chr(91) + \"profile.gold\" + chr(93) + chr(10) + \"url = \\\"http://user:pass@proxy.invalid:8080\\\"\" + chr(10))
os.chmod(path, 0o644)
try:
    load_profiles(path)
except (PermissionError, ValueError) as exc:
    assert \"pass\" not in str(exc), str(exc)
else:
    raise SystemExit(\"файл с правами 0644 прочитан\")
os.chmod(path, 0o600)
assert load_profiles(path)[\"gold\"].endswith(\":8080\")
"'`

- **AC-507 — секрет не доезжает до записи прогона.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
from bench.runner.record import to_jsonl_line
from tests.m4_helpers import record
line = to_jsonl_line(record(\"curl\", \"target:a\", success=True, egress_profile=\"gold\"))
assert \"gold\" in line
for forbidden in (\"@\", \"proxy.invalid\", \"pass\"):
    assert forbidden not in line, (forbidden, line)
"'`

- **AC-508 — контракты вех M1–M4 тронуты только там, где разрешено.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && git diff --quiet main..HEAD -- bench/scenarios.py bench/server bench/report/coverage.py README.md TASKS.md CHANGELOG.md docs/research && python3 -c "
from bench.models import FailureReason
now = {member.value for member in FailureReason}
assert \"environment_error\" in now, now
assert \"not_measured\" in now and \"provider_error\" in now, now
assert len(now) == 16, len(now)
"'`

- **AC-509 — состав работы и чистое дерево.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && git ls-files --error-unmatch bench/egress.py tests/test_egress.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно девять, формат прежний. 🚨 Строку
`command` копируй из спеки **дословно**.

## Контракт на невыполнимое

Требование невыполнимо или противоречит контрактам M1–M4 — **остановись и
доложи**. Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест,
правка файлов из «Не трогать».

Отдельно: **не выдумывай чисел про эффект прокси**. Эффект не измерен и в этой
вехе не меряется; любая строка вида «прокси помогает в N% случаев» — выдумка,
даже если звучит правдоподобно.

## Стыки с соседними вехами

Веха обещает следующей: исполнимый шаг `change_egress` и запись, по которой видно,
каким выходом ходили. Следующая веха (M6) занимается правилом отбора: измерено,
что incremental coverage **зависит от порядка перебора** и не видит свежесть
контента (архив 431,86 ч против ленты 0,02 ч на одной цели). Прежде чем чинить
правило, надо перечислить все измерения, по которым провайдеры отличаются, и
решить, какое из них правило оптимизирует, а какие остаются ограничениями.
