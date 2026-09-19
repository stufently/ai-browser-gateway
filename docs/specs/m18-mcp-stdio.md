# M18 — свой MCP-сервер поверх лестницы (stdlib, stdio)

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `99d230923b0e81abae8339394231cdc2422f0ddd` — вершина main.
Клон /home/user/exec-clones/abg-m18-20260919, ветка m18-mcp-stdio,
origin push DISABLED. Исполнитель — cx (директива владельца: «доделывай всё
через кодекс»). Решение владельца 19.09.2026: делать MCP **на stdlib, без
сторонних зависимостей** — у проекта `dependencies = []`, и это свойство
сохраняется.

## Зачем

Шлюз умеет доставать страницы лестницей провайдеров, но агент (Claude Code,
Codex) не видит его в списке инструментов и сам не зовёт: сейчас в шлюз ходят
руками через CLI `scripts/abg-fetch` или HTTP API. MCP-сервер даёт агенту
инструмент `fetch_page`, за которым стоит ВСЯ лестница — обходные входы, HTTP,
смена egress, браузер, — а не один инструмент, как у чужих MCP поверх одного
движка.

Сервер — тонкий адаптер: JSON-RPC 2.0 по stdio → HTTP-вызов уже развёрнутого
API (`127.0.0.1:8765/v1/fetch`). Своего сетевого слушателя он не открывает,
боевой сервис не трогает, продуктовую логику не дублирует.

## Ресерч: что проверено по источнику, а не по памяти

Схема протокола взята из репозитория `modelcontextprotocol/modelcontextprotocol`
19.09.2026 (`schema/<ревизия>/schema.json` и `schema.ts`):

- Последняя ревизия — **`2026-07-28`** (`LATEST_PROTOCOL_VERSION` в `schema.ts`),
  предыдущая живая — `2025-06-18`. Версия протокола — строка-дата, не semver.
- **Формы результатов между ревизиями РАЗНЫЕ.** В `2026-07-28`
  `ListToolsResult` требует `tools`, `resultType`, `cacheScope`, `ttlMs`;
  `CallToolResult` требует `content` и `resultType`. В `2025-06-18`
  требуется только `tools` и только `content` соответственно.
- `resultType` — строка, канонические значения `"complete"` и
  `"input_required"`; клиент, получивший результат без этого поля от старого
  сервера, обязан считать его `"complete"`.
- `cacheScope` — `"private"` либо `"public"`; `ttlMs` — целое.
- `JSONRPC_VERSION` = `"2.0"`; коды ошибок стандартные
  (`-32700` parse, `-32600` invalid request, `-32601` method not found).

Контракт нашего API прочитан в коде (`gateway/api_http.py`,
`gateway/product.py`, `gateway/client.py`): `POST /v1/fetch`, заголовок `Authorization: Bearer <токен>`,
тело — `url` (обязательно), `format` из `text|html|markdown|links|meta`,
`expected_text`, `budget_ms` (по умолчанию 30000), `allow_browser` (по умолчанию
true), `max_age_hours` (по умолчанию 0.0). Ответ: `ok`, `url`, `final_url`,
`provider`, `age_hours`, `error_type`, `step`, `elapsed_ms`, `format`,
`content`, `attempts[]`.

В `gateway/client.py` (CLI `abg-fetch`) УЖЕ есть рабочий клиент этого API:
адрес из `ABG_URL` (по умолчанию `http://127.0.0.1:8765/v1/fetch`), токен из
`ABG_TOKEN` либо файла `ABG_TOKEN_FILE` (по умолчанию
`~/.config/abg/client-token`), бюджет 1…180000 мс, `ProxyHandler({})` (без
системного прокси), `NoRedirect`, разбор JSON через `unique`/`reject` и проверка
формы ответа `validate_response(value, mode)`. MCP-сервер обязан
переиспользовать эти топ-уровневые функции импортом, а не писать второй клиент
с другими правилами.

Предположение (проверить не на чем, помечено честно): конкретную ревизию,
которую пришлёт клиент, заранее не знаем — поэтому версия ДОГОВАРИВАЕТСЯ, см.
пункт 2.

## Задача

1. **Модуль `gateway/mcp_stdio.py`** — только stdlib. Читает из stdin строки
   JSON-RPC (по одному сообщению на строку), пишет ответы в stdout по одной
   строке. В stdout НЕ должно попадать ничего, кроме JSON-RPC сообщений
   (диагностика — только в stderr). Пустые строки пропускаются; битый JSON →
   ответ с кодом `-32700`; неизвестный метод → `-32601`; уведомление (запрос
   без `id`) ответа НЕ получает.
2. **Договор о версии.** Поддерживаются `2026-07-28` и `2025-06-18`. На
   `initialize` сервер отвечает ТОЙ версией, которую запросил клиент, если она
   поддержана; иначе — самой свежей поддержанной (`2026-07-28`). Ответ несёт
   `protocolVersion`, `capabilities` с непустым `tools` и `serverInfo`
   (`name`: `ai-browser-gateway`, `version` из `pyproject.toml`).
   Уведомление `notifications/initialized` принимается молча.
3. **`tools/list`** отдаёт ровно один инструмент `fetch_page` с `inputSchema`
   (JSON Schema, `type: object`), где `url` обязателен, а `format` —
   перечисление `text|html|markdown|links|meta` со значением по умолчанию
   `text`; остальные поля — `expected_text`, `budget_ms`, `allow_browser`,
   `max_age_hours`. Поля `resultType: "complete"`, `cacheScope: "private"` и
   `ttlMs` добавляются ТОЛЬКО когда договорились о `2026-07-28`; при
   `2025-06-18` их нет.
4. **`tools/call`** для `fetch_page`: собирает тело запроса, берёт токен и
   адрес по тем же правилам, что `gateway/client.py` (`ABG_TOKEN` /
   `ABG_TOKEN_FILE`, `ABG_URL`), шлёт `POST` без прокси и без редиректов,
   проверяет ответ `validate_response` и возвращает `CallToolResult`:
   - `content`: один блок `{"type": "text", "text": …}`; для `links` и
     `meta` содержимое — JSON-строка (как печатает `abg-fetch`);
   - `structuredContent`: `ok`, `provider`, `step`, `error_type`, `elapsed_ms`,
     `final_url` и `attempts` — чтобы агент видел, чем именно взята страница;
   - `resultType: "complete"` — только при `2026-07-28`;
   - при неуспехе шлюза (`ok=false`) — `isError: true`, текстовый блок с
     `error_type` и `step`, без секретов;
   - при сбое транспорта, не-200 или битом ответе — тоже `isError: true`
     (не JSON-RPC ошибка: это отказ инструмента, а не протокола);
   - неверные аргументы (нет `url`, `format` вне списка, бюджет вне границ) —
     JSON-RPC ошибка `-32602`.
   Токен, значение заголовка `Authorization` и URL с `user:pass@` НИКОГДА не
   попадают ни в stdout, ни в stderr, ни в текст ошибки.
5. **Точка входа** `scripts/abg-mcp` (исполняемый, `#!/usr/bin/env python3`),
   запускающая сервер; README — короткий раздел «MCP server» с примером
   подключения (команда, переменные `ABG_URL`, `ABG_TOKEN_FILE`).
6. **Тесты `tests/test_mcp_stdio.py`** — офлайн, без сети и без боевого
   сервиса: HTTP-вызов подменяется. Покрыть: договор о версии (три случая из
   пункта 2), формы `tools/list` для обеих ревизий, успешный и неуспешный
   `tools/call`, отсутствие токена в выводе, битый JSON, неизвестный метод,
   уведомление без ответа, отсутствие постороннего вывода в stdout.
7. **Закоммитить эту спеку** `docs/specs/m18-mcp-stdio.md` byte-identical
   вместе с работой.
8. **Мутанты** в `tests/mutation_gate_gateway.py` — три новых, каждый обязан
   убиваться своим тестом: (а) сервер всегда отвечает своей версией вместо
   запрошенной; (б) поля `resultType`/`cacheScope`/`ttlMs` добавляются всегда,
   независимо от ревизии; (в) при `ok=false` не выставляется `isError`.
   Итого в этих воротах 16.

## Разрешения

Создать `gateway/mcp_stdio.py`, `tests/test_mcp_stdio.py`, `scripts/abg-mcp`;
править `tests/mutation_gate_gateway.py` и `README.md`. Docker-прогоны
образом из критериев. Commit в клоне. Первым коммитом закоммитить эту спеку
`docs/specs/m18-mcp-stdio.md` byte-identical.

## Не трогать

`bench/**`, `gateway/**` кроме нового модуля (`gateway/client.py` только
импортировать, не править), `deploy/**`, `tests/**` кроме
нового файла и ворот, другие specs, TASKS.md, CHANGELOG.md, `secrets/**`,
`/home/user/services/**` (боевой сервис не трогается: ни выкладки, ни живых
запросов), `scripts/**` кроме новой точки входа. Сторонние зависимости
добавлять ЗАПРЕЩЕНО: `pyproject.toml` остаётся с `dependencies = []`. Сеть в
проверках не нужна. Push и merge запрещены.

## Критерии приёмки

- **AC-210.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-211.** Тесты MCP зелёные:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_mcp_stdio'`
- **AC-212.** Живой handshake через процесс: договор о версии и форма ответа для обеих ревизий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import json,subprocess,sys; run=lambda ver: json.loads(subprocess.run([sys.executable,\"-m\",\"gateway.mcp_stdio\"], input=json.dumps({\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":ver,\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}})+chr(10), capture_output=True, text=True, timeout=60).stdout.splitlines()[0]); a=run(\"2026-07-28\"); b=run(\"2025-06-18\"); c=run(\"1999-01-01\"); assert a[\"result\"][\"protocolVersion\"]==\"2026-07-28\", a; assert b[\"result\"][\"protocolVersion\"]==\"2025-06-18\", b; assert c[\"result\"][\"protocolVersion\"]==\"2026-07-28\", c; assert a[\"result\"][\"capabilities\"].get(\"tools\") is not None, a; assert a[\"result\"][\"serverInfo\"][\"name\"]==\"ai-browser-gateway\", a; print(\"ok\")"'`
- **AC-213.** Инструмент один, схема правильная, новые поля появляются только на свежей ревизии:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import json,subprocess,sys; msg=lambda *m: chr(10).join(json.dumps(x) for x in m)+chr(10); call=lambda ver: [json.loads(l) for l in subprocess.run([sys.executable,\"-m\",\"gateway.mcp_stdio\"], input=msg({\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":ver,\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}},{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"},{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\"}), capture_output=True, text=True, timeout=60).stdout.splitlines()]; new=[m for m in call(\"2026-07-28\") if m.get(\"id\")==2][0][\"result\"]; old=[m for m in call(\"2025-06-18\") if m.get(\"id\")==2][0][\"result\"]; names=[t[\"name\"] for t in new[\"tools\"]]; assert names==[\"fetch_page\"], names; schema=new[\"tools\"][0][\"inputSchema\"]; assert schema[\"type\"]==\"object\" and \"url\" in schema[\"required\"], schema; assert schema[\"properties\"][\"format\"][\"enum\"]==[\"text\",\"html\",\"markdown\",\"links\",\"meta\"], schema; assert new[\"resultType\"]==\"complete\" and new[\"cacheScope\"] in (\"private\",\"public\") and isinstance(new[\"ttlMs\"], int), new; assert not ({\"resultType\",\"cacheScope\",\"ttlMs\"} & set(old)), old; print(\"ok\")"'`
- **AC-214.** Мутационные ворота шлюза: три новых убиты, всего 16. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 16 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-215.** Зависимостей не прибавилось, документ на месте, вне разрешённых путей чисто:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && grep -q "MCP" README.md && test -x scripts/abg-mcp && git diff --exit-code 99d230923b0e81abae8339394231cdc2422f0ddd HEAD -- . ":(exclude)gateway/mcp_stdio.py" ":(exclude)tests/test_mcp_stdio.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)scripts/abg-mcp" ":(exclude)README.md" ":(exclude)docs/specs/m18-mcp-stdio.md" && git ls-files --error-unmatch docs/specs/m18-mcp-stdio.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m18-20260919 --base 99d230923b0e81abae8339394231cdc2422f0ddd --range 99d230923b0e81abae8339394231cdc2422f0ddd..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. ВАЖНО: у Grok 19.09.2026 кончился баланс
(HTTP 402). Если он снова вернёт quota error — повторов не делать, записать в
note и продолжать; это внешний сбой, а не блокер работы.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-210…AC-215,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"99d230923b0e81abae8339394231cdc2422f0ddd","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-210","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m18-20260919 --spec /home/user/exec-clones/abg-m18-20260919/docs/specs/m18-mcp-stdio.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
требуется сторонняя зависимость (обходить запрет нельзя — это суть решения
владельца); требуется боевой сервис, сеть или новый слушающий сокет; мутант не
убивается своим тестом; правка требует выхода за разрешённые файлы. Спеку, AC,
BASE и оснастку приёмки не менять, rc не выдумывать, чужое не трогать.
