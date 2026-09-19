# M18-fix1 — MCP-сервер говорит на ревизиях эпохи initialize

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `55be93c612bf3c55a69e10d30dcceef49ec4f8ed` — вершина ветки
`m18-mcp-stdio` (результат вехи M18, в main не влита).
Клон /home/user/exec-clones/abg-m18-fix1-20260919, ветка m18-fix1,
origin push DISABLED. Исполнитель — cx.

## Зачем: что сломалось

M18 прошла все шесть своих критериев, но **настоящий клиент к серверу не
подключается**. Живой прогон 19.09.2026: Claude Code 2.1.278 прислал

```
{"method":"initialize","params":{"protocolVersion":"2025-11-25",...},"jsonrpc":"2.0","id":0}
```

сервер ответил `"protocolVersion": "2026-07-28"`, клиент разорвал соединение с
ошибкой «Server's protocol version is not supported: 2026-07-28», и инструмент
`fetch_page` в сессии не появился.

Причина — дефект СПЕКИ M18, а не исполнения: спека считала `2026-07-28` просто
новой ревизией с другими формами ответов. На деле в `2026-07-28` запроса
`initialize` НЕТ вовсе (`ClientRequest` начинается с `server/discover`, версия
передаётся в `_meta` каждого запроса). Ответить на `initialize` этой ревизией
значит назвать версию, в которой такого рукопожатия не существует.

Второй дефект найден тем же живым стендом уже на ручной правке версии:
клиент подключился, вызвал `fetch_page`, шлюз отдал страницу
(`provider=curl_cffi`, в `content` 152 символа текста), но модель ответила,
что текста нет, «только метаданные». Claude Code, получив `structuredContent`,
показывает модели именно его, а блоки `content` не показывает. Опыт: тот же
вызов с текстом страницы, продублированным в `structuredContent`, — модель
процитировала первые 60 символов. Схема 2025-11-25 не запрещает ни то, ни
другое (оба поля описаны как равноправные представления результата), поэтому
сервер обязан класть текст в оба.

Решение владельца 19.09.2026: **поддерживать только эпоху initialize**;
ревизию `2026-07-28` убрать и добавить отдельной вехой, когда её заговорит
реальный клиент.

## Ресерч: проверено по схеме, а не по памяти

Схемы `schema/2025-11-25/schema.json` и `schema/2025-06-18/schema.json` из
репозитория `modelcontextprotocol/modelcontextprotocol`, снятые 19.09.2026:

- в обеих есть `InitializeRequest` и `PingRequest`;
- обязательные поля у обеих одинаковые: `InitializeResult` —
  `capabilities`, `protocolVersion`, `serverInfo`; `ListToolsResult` —
  `tools`; `CallToolResult` — `content`;
- полей `resultType`, `cacheScope`, `ttlMs` ни в одной из них нет;
- `2025-11-25` добавляет задачи (`tasks/*`) — это опциональная возможность,
  сервер её не объявляет и не реализует.

Правило договора о версии в эпохе initialize: если клиент запросил
поддержанную версию — сервер отвечает ею же; иначе — самой свежей своей.
`ping` — запрос, на который получатель обязан ответить пустым результатом `{}`.

## Что проверено вживую, а что предположение

Прочитано в `gateway/mcp_stdio.py` на BASE: константы `LATEST_VERSION`
(`'2026-07-28'`) и `SUPPORTED_VERSIONS`; метод `Server.result_fields`,
который и добавляет три поля новой ревизии; `Server.dispatch` обрабатывает
`initialize`, `tools/list`, `tools/call`, на всё прочее `LookupError` →
`-32601`, то есть `ping` сейчас получает «Method not found». В
`tests/mutation_gate_gateway.py` три MCP-мутанта с `old`:
`self.version = requested if requested in SUPPORTED_VERSIONS else LATEST_VERSION`,
`if self.version == LATEST_VERSION:`, `result['isError'] = True`.
Живой кадр Claude Code и отказ клиента сняты прогоном `claude -p` с
`--mcp-config` через логирующую прослойку. Координатор до запуска прогнал
AC-222 и AC-223 на BASE (оба падают) и на своей ручной правке (оба проходят).
Там же прочитано: `fetch_page` собирает `structuredContent` из ключей `ok`,
`provider`, `step`, `error_type`, `elapsed_ms`, `final_url`, `attempts` —
текста страницы в нём нет. Предположений о коде нет.

## Задача

1. В `gateway/mcp_stdio.py`: поддерживаемые версии — `2025-11-25` (самая
   свежая) и `2025-06-18`. Строки `2026-07-28` в модуле быть не должно.
   Любая неподдержанная версия, включая `2026-07-28`, получает ответ
   `2025-11-25`.
2. Убрать добавление полей `resultType`, `cacheScope`, `ttlMs` из всех
   ответов: ни одна поддержанная ревизия их не знает.
3. Добавить метод `ping`, возвращающий `{}`.
3а. В ответе `tools/call` поле `structuredContent` обязано содержать ключ
   `content` — ровно ту же строку, что `text` единственного блока в
   `content` (текст страницы; JSON-строку для `links`/`meta`; текст ошибки при
   `isError`). Метаданные лестницы остаются рядом, как есть. Тест —
   `MCPTests.test_structured_content_carries_page_text`.
4. Тесты `tests/test_mcp_stdio.py` привести к новой модели: договор о версии
   (обе поддержанные эхом, `2026-07-28` и неизвестная → `2025-11-25`),
   `ping`, отсутствие полей новой ревизии; ДОБАВИТЬ тест на дословный кадр
   Claude Code из раздела «Зачем» (полный текст — в AC-222).
5. Мутационные ворота `tests/mutation_gate_gateway.py`: мутант «MCP
   revision-specific result fields» больше не к чему применять — заменить его
   мутантом «ping не обрабатывается» (метод `ping` удалён из диспетчера),
   который убивается тестом на `ping`. Мутанты «honors requested protocol
   version» и «gateway failure as tool error» сохранить, поправив `old`/`test`
   под новый код. Добавить мутант «structured content carries page text»
   (ключ `content` в `structuredContent` не выставляется), убиваемый тестом
   `test_structured_content_carries_page_text`. Итого в воротах 17.
6. README, раздел «MCP server»: перечислить поддержанные версии
   `2025-11-25` и `2025-06-18`, упоминание `2026-07-28` убрать.
7. Закоммитить эту спеку `docs/specs/m18-fix1-initialize-era.md`
   byte-identical первым коммитом.

## Разрешения

Правка `gateway/mcp_stdio.py`, `tests/test_mcp_stdio.py`,
`tests/mutation_gate_gateway.py`, `README.md`. Docker-прогоны образом из
критериев. Commit в клоне.

## Не трогать

Всё прочее: `bench/**`, остальные модули `gateway/**` (включая
`gateway/client.py`), `deploy/**`, `scripts/**`, другие тесты и specs,
TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`. Сторонних
зависимостей не добавлять: `dependencies = []`. Живой сервис и сеть не нужны.
Push и merge запрещены. Реализацию `2026-07-28` (`server/discover`, `_meta`)
НЕ писать — это отдельная будущая веха.

## Критерии приёмки

- **AC-220.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-221.** Тесты MCP зелёные, тест на текст в структурированном результате существует:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_mcp_stdio tests.test_mcp_stdio.MCPTests.test_structured_content_carries_page_text'`
- **AC-222.** Дословный кадр Claude Code 2.1.278 получает поддержанную им версию; договор о версии для остальных случаев:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import json,subprocess,sys; cc=json.dumps({\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{\"roots\":{\"listChanged\":True},\"elicitation\":{}},\"clientInfo\":{\"name\":\"claude-code\",\"title\":\"Claude Code\",\"version\":\"2.1.278\",\"description\":\"Anthropic agentic coding tool\",\"websiteUrl\":\"https://claude.com/claude-code\"}},\"jsonrpc\":\"2.0\",\"id\":0}); first=lambda line: json.loads(subprocess.run([sys.executable,\"-m\",\"gateway.mcp_stdio\"], input=line+chr(10), capture_output=True, text=True, timeout=60).stdout.splitlines()[0]); init=lambda ver: first(json.dumps({\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":ver,\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}}))[\"result\"][\"protocolVersion\"]; r=first(cc); assert r[\"id\"]==0 and r[\"result\"][\"protocolVersion\"]==\"2025-11-25\", r; got=[init(v) for v in (\"2025-06-18\",\"2025-11-25\",\"2026-07-28\",\"1999-01-01\")]; assert got==[\"2025-06-18\",\"2025-11-25\",\"2025-11-25\",\"2025-11-25\"], got; print(\"ok\")"'`
- **AC-223.** Полная сессия через процесс: рукопожатие, уведомление без ответа, список инструментов без полей чужой ревизии, ping с пустым результатом:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import json,subprocess,sys; msgs=[{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}},{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"},{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\"},{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"ping\"}]; out=[json.loads(l) for l in subprocess.run([sys.executable,\"-m\",\"gateway.mcp_stdio\"], input=chr(10).join(json.dumps(m) for m in msgs)+chr(10), capture_output=True, text=True, timeout=60).stdout.splitlines()]; assert [m[\"id\"] for m in out]==[1,2,3], out; tools=out[1][\"result\"]; assert [t[\"name\"] for t in tools[\"tools\"]]==[\"fetch_page\"], tools; assert not ({\"resultType\",\"cacheScope\",\"ttlMs\"} & set(tools)), tools; assert out[2]==({\"jsonrpc\":\"2.0\",\"id\":3,\"result\":{}}), out[2]; print(\"ok\")"'`
- **AC-224.** Мутационные ворота шлюза: 17 мутантов, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 17 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-225.** Новой ревизии в коде и README нет, зависимостей не прибавилось, вне разрешённых путей чисто:
  `bash -c '! grep -q "2026-07-28" gateway/mcp_stdio.py && ! grep -q "2026-07-28" README.md && grep -q "2025-11-25" README.md && grep -q "dependencies = \[\]" pyproject.toml && git diff --exit-code 55be93c612bf3c55a69e10d30dcceef49ec4f8ed HEAD -- . ":(exclude)gateway/mcp_stdio.py" ":(exclude)tests/test_mcp_stdio.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)README.md" ":(exclude)docs/specs/m18-fix1-initialize-era.md" && git ls-files --error-unmatch docs/specs/m18-fix1-initialize-era.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m18-fix1-20260919 --base 55be93c612bf3c55a69e10d30dcceef49ec4f8ed --range 55be93c612bf3c55a69e10d30dcceef49ec4f8ed..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. У Grok 19.09.2026 кончился баланс (HTTP 402):
при quota error повторов не делать, записать в note и продолжать — это внешний
сбой, а не блокер работы.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-220…AC-225,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"55be93c612bf3c55a69e10d30dcceef49ec4f8ed","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-220","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m18-fix1-20260919 --spec /home/user/exec-clones/abg-m18-fix1-20260919/docs/specs/m18-fix1-initialize-era.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется сторонняя зависимость; требуется живой сервис или сеть; мутант не
убивается своим тестом; правка требует выхода за разрешённые файлы. Спеку, AC,
BASE и оснастку приёмки не менять, rc не выдумывать, чужое не трогать.
