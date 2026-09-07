# Веха M5 — заход исправлений

| | |
|---|---|
| Клон | `/home/user/exec-clones/abg-m5-proxy`, ветка `m5-proxy` |
| Базовый коммит | `2dbd08e` «Add proxy profiles and environment_error» |
| Исполнитель | **Grok** (тот же, кто писал веху) |
| Основание | независимое ревью Codex + перекрёстный мутационный прогон Codex + живые замеры постановщика |

Заход **один**. Всё, что ниже, закрывается в нём; новых улучшений не добавлять.

## Главное: веха сейчас НЕ делает того, ради чего написана

Аутентифицированный прокси не применяется у двух провайдеров из семи, а пароль
утекает двумя путями. Это не придирки ревью — постановщик поднял локальный
прокси, требующий `Proxy-Authorization`, и посмотрел, что до него доходит.

### Замер 1 — кто из провайдеров вообще аутентифицируется

Стенд: питоновский прокси на `127.0.0.1:8888`, отвечает `407 Proxy
Authentication Required` и печатает, был ли в запросе заголовок
`Proxy-Authorization`. Внешняя цель не запрашивалась ни разу — прокси отвечал
сам, наружу не ходил никто.

| Провайдер | Как сейчас передаётся прокси | `Proxy-Authorization` дошёл |
|---|---|---|
| `curl` | `--proxy <url c кредами>` | **да** |
| `curl_cffi` | `proxy=<url c кредами>` | **да** |
| `primp` | `proxy=<url c кредами>` | **да** |
| вход `wayback`/`rss` (urllib `ProxyHandler`) | url c кредами | **да** |
| `camoufox` (Firefox) | `proxy={"server": <url c кредами>}` | **да** (после 407 повторяет с заголовком) |
| `pydoll` | `--proxy-server=<url c кредами>` | **да** (см. замер 3) |
| **`playwright`** | `proxy={"server": <url c кредами>}` | **НЕТ** |
| **`patchright`** | наследует `start()` у `playwright` | **НЕТ** |

Тот же запуск playwright с раздельными полями:

```python
proxy={"server": "http://127.0.0.1:8888", "username": "user", "password": "…"}
```

→ первый запрос без заголовка, ответ `407`, **повтор с
`Proxy-Authorization`** — то есть путь рабочий.

Причина: `ProxySettings` у playwright — это `TypedDict` с полями `server`,
`bypass`, `username`, `password`; `server` уезжает в chromium как
`--proxy-server=…`, а chromium **userinfo из URL игнорирует**. Firefox
(camoufox) userinfo разбирает сам, поэтому там всё работает.

🚨 Спека вехи (`docs/specs/m5-proxy.md`) утверждала, что
`launch(proxy={"server": …})` проверен. Проверен он был **без пароля**;
следствие для аутентифицированного прокси в спеке названо не было. Дефект родом
из спеки, а не из твоей работы — как в M4 с `User-Agent`.

### Замер 2 — пароль в argv и в тексте ошибки

**argv контейнера.** Пока `curl` работает, его командная строка видна целиком:

```
$ tr "\0" " " < /proc/<pid>/cmdline
curl --proxy http://user:SECRETPW@10.255.255.1:9/ --max-time 5 https://example.com
```

То есть пароль читается из `/proc/<pid>/cmdline` внутри контейнера и из
`docker top` снаружи. Проверено, что `curl` берёт прокси **из окружения** и
результат тот же:

```
$ docker run -e ALL_PROXY='http://user:SECRETPW@nonexistent.invalid:8080/' … curl https://example.com
curl: (5) Could not resolve proxy: nonexistent.invalid
```

**stderr curl.** Три класса ошибок из четырёх печатают URL прокси целиком:

| Ошибка | Текст |
|---|---|
| не резолвится хост | `curl: (5) Could not resolve proxy: nonexistent.invalid` — без пароля |
| битый синтаксис | `curl: (5) Unsupported proxy syntax in 'http://user:SECRETPW@h:1/'` |
| неизвестная схема | `curl: (7) Unsupported proxy scheme for 'socks9://user:SECRETPW@127.0.0.1:9/'` |
| битый порт | `curl: (5) Unsupported proxy syntax in 'http://user:SECRETPW@127.0.0.1:99999/'` |

Этот текст `CurlAdapter.navigate` кладёт в `RuntimeError`, а обработчик
исключений — дословно в поле `err` результата. Оттуда пароль попадает в JSONL
прогона и в любой отчёт, построенный по нему.

### Замер 3 — `pydoll` трогать НЕ НАДО

У pydoll есть `ProxyManager`: он находит `--proxy-server=` с кредами,
**вырезает креды из аргумента** до запуска браузера и отдаёт их через
`Fetch.continueRequestWithAuth`. Проверено на живом запуске: после старта
браузера строка `SECRETPW` не встречается ни в одном `/proc/*/cmdline`
контейнера, а в аргументах chromium остался очищенный флаг.

Поэтому `PydollAdapter` в этом заходе **менять запрещено**: любая «унификация»
сломает работающий путь.

## Что делать

### 1. Playwright-семейство: креды отдельным полем

Завести в `probe.py` чистую функцию (имя обязательное, на неё смотрит критерий):

```python
def playwright_proxy(url: str) -> dict[str, str]:
    """ProxySettings для playwright/patchright/camoufox: креды отдельно от server."""
```

Правила:

- `http://user:pass@host:3128` → `{"server": "http://host:3128",
  "username": "user", "password": "pass"}`.
- Прокси без кредов → `{"server": "http://host:3128"}` и **ничего больше**:
  ключей `username`/`password` в словаре быть не должно (пустая строка вместо
  пароля — не то же самое, что его отсутствие).
- Проценты декодировать: `p%40ss` в URL — это пароль `p@ss`. Иначе символы,
  которые в URL обязаны экранироваться, доедут искажёнными.
- Порт, схему и путь `server` сохраняет как есть.
- Разбор — стандартным разбором URL, не поиском символов руками. Пароль с
  неэкранированным `@` в файле кредов разобрать нельзя ни при каком разборе;
  это обязанность владельца файла, и придумывать эвристику под этот случай
  **не надо**.

Использовать её в `PlaywrightAdapter.start` и `CamoufoxAdapter.start`
(`PatchrightAdapter` наследует). Camoufox сейчас работает и так — переводим его
на общую функцию, чтобы форма была одна и следующий адаптер не скопировал
сломанную; раздельные поля у Firefox тоже проверены (замер 1).

Для pydoll — вторая функция, тоже с обязательным именем, фиксирующая, что там
формат ДРУГОЙ и намеренно:

```python
def pydoll_proxy_flag(url: str) -> str:
    """--proxy-server= с кредами внутри: их вырезает и применяет сам pydoll."""
```

и `PydollAdapter.start` вызывает её вместо ручной склейки строки.

### 2. `curl` берёт прокси из окружения, а не из argv

В `CurlAdapter.navigate` убрать `--proxy` совсем и передать прокси через
окружение дочернего процесса (`ALL_PROXY`), явным `env=` у `subprocess.run`.
Остальные аргументы не менять.

Это не «спрятало секрет» — он остаётся в окружении процесса, в
`/proc/<pid>/environ` и в `docker inspect`. Это убирает **одну** конкретную
дыру: командную строку, которую видно из `docker top` и из любого процесса в
контейнере, включая ту, что печатает `ps` в чужом отчёте.

### 3. Текст ошибки не должен содержать пароль

Завести в `probe.py`:

```python
def redact(text: str) -> str:
    """Убирает userinfo из любых URL в тексте: http://u:p@h → http://***@h."""
```

Применить её в ЕДИНСТВЕННОМ месте — там, где собирается поле `err` обработчиком
исключений в `run_probe`, — чтобы ни один путь не мог её обойти.

Требования:

- `http://user:pass@host:3128` внутри произвольного текста → `http://***@host:3128`.
- Текст без URL не меняется вообще.
- Работает и когда URL в кавычках (`'…'`), и когда в конце строки, и когда их
  два в одном сообщении.

### 4. Старый JSONL читается: необязательные поля берут значение по умолчанию

`from_jsonl_line` требует в строке **все** поля датакласса, поэтому отчёт по
сохранённым прогонам падает. Проверено на живых файлах:

| Файл прогона | Ошибка |
|---|---|
| прогон M4 | `missing field: egress_profile` |
| прогон M2 | `missing field: entrance_age_hours, egress_profile` |

То есть дыра шире, чем одно поле: каждая веха, добавившая поле с умолчанием,
ломает чтение всех прошлых прогонов, и M6 сломает эти же файлы снова.

Правило: обязательны поля **без значения по умолчанию**. Поле с умолчанием,
отсутствующее в строке, берёт своё умолчание (`egress_profile` → `"direct"`,
`entrance_age_hours` → `None`) — ровно то, чем такие прогоны и были. Отсутствие
поля БЕЗ умолчания остаётся ошибкой с прежним текстом.

Список полей не перечислять в коде руками: он должен получаться из самого
датакласса, иначе следующее поле опять придётся вписывать вручную.

### 5. Широкие права — это `environment_error` записями, а не пустой файл

Сейчас: файл кредов с правами шире `0600` роняет CLI с `rc=2` **после** того,
как выходной JSONL уже создан через `open('x')`. Остаётся пустой файл, и
следующий запуск в тот же путь отказывается работать с `File exists`. Названного
типа ошибки при этом нет ни у одной записи.

Должно быть три состояния, каждое — **поимённо**:

| Ситуация | `error_type` каждой записи |
|---|---|
| файла кредов нет, или в нём нет такого профиля, или URL пуст | `not_measured` |
| файл есть, но права шире `0600` | `environment_error` |
| профиль применён, цель не пустила | обычный отказ цели, как без прокси |

То есть широкие права дают **полный набор записей** с `environment_error`
(контейнер не запускается, как и в случае `not_measured`), прогон завершается
`rc=0`, а на stderr идёт строка с именем файла. Содержимое файла с широкими
правами при этом **не читается**: право доступа проверяется до чтения.

Пустого выходного файла не остаётся ни при одном исходе: либо в нём записи, либо
он не создан.

### 6. Права `0400` строже, чем `0600`, и должны приниматься

Проверка `mode != 0o600` отвергает `0400` — файл, доступный только на чтение
владельцу, то есть более строгий. Правило должно запрещать доступ **чужим**:
ненулевые биты в `st_mode & 0o077`. `0600` и `0400` проходят, `0640` и `0604`
отвергаются.

### 7. Четыре дыры в тестах (перекрёстный прогон Codex)

Ни одна не является дефектом кода — код в этих местах прав. Все четыре мутации
постановщик воспроизвёл: ложатся, сьют остаётся зелёным.

1. Прокси перестаёт применяться **только у `patchright`** (у `playwright`
   остаётся) — сьют зелёный. Нужен тест, который требует настройки прокси у
   ОБОИХ пакетов семейства.
2. `ABG_PROXY` в `execute_plan` по завершении **удаляется**, вместо того чтобы
   вернуться к прежнему значению, — сьют зелёный. Нужен тест: переменная,
   стоявшая до запуска, после запуска имеет то же значение.
3. `rc in (125, 126, 127)` заменяется на `rc >= 125` — сьют зелёный. Нужен тест:
   `rc=137` (убит по OOM) это **не** `environment_error`, а обычный отказ.
4. `body.get("url", "")` заменяется на `body["url"]` — сьют зелёный. Нужен тест
   на ответ без ключа `url`.

Плюс мутации в `tests/mutation_gate.py` — **на каждую из четырёх** и **на каждый
пункт 1–6** (сломанная форма из замеров: креды внутри `server` у playwright;
`--proxy` в argv у curl; `redact` возвращает аргумент как есть; обязательный
`egress_profile`; `not_measured` вместо `environment_error` при широких правах;
`mode != 0o600`).

🚨 **Проверь, что мутация ЛЕГЛА, прежде чем считать её убитой**, и что тест
падает на СВОЕЙ строке проверки, а не на постороннем `AttributeError`. Правя
боевую строку, ищи её текст в `tests/mutation_gate.py`: правка осиротит мутанта,
который её цитирует, и гейт покажет `fragment occurs 0 times`.

## Не трогать

- Весь раздел «Не трогать» основной спеки `docs/specs/m5-proxy.md` остаётся в
  силе, включая `README.md`, `TASKS.md`, `CHANGELOG.md` и `docs/research/`.
- **`PydollAdapter`** — только замена ручной склейки строки на
  `pydoll_proxy_flag()`; формат аргумента (креды внутри `--proxy-server=`) не
  менять. Обоснование — замер 3.
- `CurlCffiAdapter`, `PrimpAdapter`, `_fetch_entrance` — не трогать: у всех трёх
  аутентификация измерена рабочей.
- Детектор челленджа, `wayback`/`rss` в части разбора снимка и дат, `bench/scenarios.py`,
  `bench/server/`, `bench/report/coverage.py` — контракты M1–M4.
- Существующие 260 тестов и 79 мутаций — не удалять и не ослаблять.
- Коммит `2dbd08e` не переписывать и не откатывать. Ветку `main` в клоне не двигать.
- 🚨 Ни одного настоящего креда, адреса прокси или пароля — только заглушки вида
  `http://user:pass@proxy.invalid:8080`.

## Критерии приёмки

- **AC-511 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -m unittest discover -s tests -t . -q'`

- **AC-512 — мутационный гейт: не меньше 89 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=89 else 1)" && python3 tests/mutation_gate.py'`

- **AC-513 — тесты на четыре дыры перекрёстного прогона существуют под этими именами.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -m unittest -q tests.test_probe.ProxyWiringTests.test_both_playwright_packages_get_proxy tests.test_execute.EgressTests.test_existing_proxy_env_is_restored tests.test_execute.EgressTests.test_killed_container_is_not_environment_error tests.test_probe.ProxyWiringTests.test_result_without_url_key'`

- **AC-514 — playwright-семейство отдаёт креды отдельными полями.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
got = probe.playwright_proxy(\"http://user:p%40ss@proxy.invalid:8080\")
assert got == {\"server\": \"http://proxy.invalid:8080\", \"username\": \"user\", \"password\": \"p@ss\"}, got
plain = probe.playwright_proxy(\"http://proxy.invalid:8080\")
assert plain == {\"server\": \"http://proxy.invalid:8080\"}, plain
"'`

- **AC-515 — pydoll получает креды внутри флага (регрессионный замок).**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
got = probe.pydoll_proxy_flag(\"http://user:pass@proxy.invalid:8080\")
assert got == \"--proxy-server=http://user:pass@proxy.invalid:8080\", got
"'`

- **AC-516 — curl не кладёт прокси в argv и всё-таки ходит через него.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import importlib.util, os, subprocess, sys
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
seen = {}
def fake_run(command, **kwargs):
    seen[\"command\"] = command; seen[\"env\"] = kwargs.get(\"env\") or {}
    raise SystemExit(0)
probe.subprocess.run = fake_run
os.environ[\"ABG_PROXY\"] = \"http://user:pass@proxy.invalid:8080\"
adapter = probe.CurlAdapter()
try:
    adapter.navigate(\"https://example.invalid/\")
except SystemExit:
    pass
assert not any(\"pass@\" in part or \"--proxy\" == part for part in seen[\"command\"]), seen[\"command\"]
assert \"http://user:pass@proxy.invalid:8080\" in seen[\"env\"].values(), sorted(seen[\"env\"])
"'`

- **AC-517 — пароль не доезжает до поля `err`.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
text = probe.redact(\"curl: (5) Unsupported proxy syntax in \x27http://user:pass@proxy.invalid:8080/\x27\")
assert \"pass\" not in text, text
assert \"proxy.invalid:8080\" in text, text
assert probe.redact(\"curl: (7) connection refused\") == \"curl: (7) connection refused\"
"'`

- **AC-518 — прогон прошлых вех читается: поля с умолчанием необязательны.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import json
from tests.m2_helpers import observed_record
from bench.runner.record import from_jsonl_line, to_jsonl_line
raw = json.loads(to_jsonl_line(observed_record()))
for name, default in ((\"egress_profile\", \"direct\"), (\"entrance_age_hours\", None)):
    trimmed = {key: value for key, value in raw.items() if key != name}
    assert getattr(from_jsonl_line(json.dumps(trimmed)), name) == default, name
both = {key: value for key, value in raw.items()
        if key not in (\"egress_profile\", \"entrance_age_hours\")}
assert from_jsonl_line(json.dumps(both)).egress_profile == \"direct\"
missing = {key: value for key, value in raw.items() if key != \"provider\"}
try:
    from_jsonl_line(json.dumps(missing))
except ValueError as exc:
    assert \"provider\" in str(exc), exc
else:
    raise SystemExit(\"пропущенный provider принят\")
"'`

- **AC-519 — широкие права дают записи `environment_error`, а не пустой файл.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && rm -rf /tmp/abg-ac519 && python3 -c "
import json, os, pathlib, subprocess, sys
home = pathlib.Path(\"/tmp/abg-ac519/home\"); (home / \".config\" / \"abg\").mkdir(parents=True)
creds = home / \".config\" / \"abg\" / \"proxies.toml\"
line = \"url = \" + chr(34) + \"http://user:pass@proxy.invalid:8080\" + chr(34)
creds.write_text(chr(10).join([\"[profile.gold]\", line, \"\"]), encoding=\"utf-8\")
creds.chmod(0o644)
out = pathlib.Path(\"/tmp/abg-ac519/run.jsonl\")
done = subprocess.run([sys.executable, \"-m\", \"bench.cli\", \"run\", \"--providers\", \"curl\",
                       \"--cells\", \"scenario:static\", \"--egress\", \"gold\", \"--output\", str(out)],
                      env={**os.environ, \"HOME\": str(home)}, capture_output=True, text=True)
assert done.returncode == 0, (done.returncode, done.stderr[-400:])
assert str(creds) in done.stderr, done.stderr[-400:]
rows = [json.loads(line) for line in out.read_text(encoding=\"utf-8\").splitlines() if line.strip()]
assert rows, \"пустой файл прогона\"
assert {row[\"error_type\"] for row in rows} == {\"environment_error\"}, {row[\"error_type\"] for row in rows}
assert {row[\"egress_profile\"] for row in rows} == {\"gold\"}, {row[\"egress_profile\"] for row in rows}
assert \"pass@\" not in out.read_text(encoding=\"utf-8\"), \"пароль в записи прогона\"
"'`

- **AC-520 — `0400` принимается, `0640` и `0604` отвергаются.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -c "
import pathlib, tempfile
from bench.egress import load_profiles
with tempfile.TemporaryDirectory() as box:
    path = pathlib.Path(box) / \"proxies.toml\"
    line = \"url = \" + chr(34) + \"http://user:pass@proxy.invalid:8080\" + chr(34)
    path.write_text(chr(10).join([\"[profile.gold]\", line, \"\"]), encoding=\"utf-8\")
    for mode in (0o600, 0o400):
        path.chmod(mode)
        assert load_profiles(path)[\"gold\"], mode
    for mode in (0o640, 0o604, 0o660):
        path.chmod(mode)
        try:
            load_profiles(path)
        except PermissionError:
            continue
        raise SystemExit(\"права %o приняты\" % mode)
"'`

- **AC-521 — окружение возвращается, коды возврата различаются.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && python3 -m unittest -q tests.test_execute.EgressTests && python3 -c "
import os
assert \"ABG_PROXY\" not in os.environ
"'`

- **AC-522 — состав работы и чистое дерево.**
  `bash -c 'cd /home/user/exec-clones/abg-m5-proxy && git ls-files --error-unmatch docs/specs/m5-proxy-fix.md >/dev/null && python3 -c "
import subprocess
def git(*args):
    return subprocess.run([\"git\", *args], capture_output=True, text=True, check=True).stdout
changed = git(\"diff\", \"--name-only\", \"2dbd08e..HEAD\").split()
stray = [name for name in changed
         if not (name.startswith(\"bench/\") or name.startswith(\"tests/\")
                 or name == \"docs/specs/m5-proxy-fix.md\")]
assert not stray, stray
dirty = [line for line in git(\"status\", \"--porcelain\").splitlines()
         if line.strip() and \"report.json\" not in line and \"report-blocked.md\" not in line]
assert not dirty, dirty
"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно двенадцать, формат прежний. 🚨 Строку
`command` копируй из спеки **дословно**.

## Контракт на невыполнимое

Требование невыполнимо, противоречит контрактам M1–M4 или требует правки
`PydollAdapter`/`CurlCffiAdapter`/`PrimpAdapter` — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест, правка
файлов из «Не трогать».

Отдельно: **не выдумывай чисел про эффект прокси**. Ни одного замера с настоящим
прокси в проекте нет и в этом заходе не появится.
