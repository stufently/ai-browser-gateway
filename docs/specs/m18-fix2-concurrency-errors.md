# M18-fix2 — ping во время загрузки, ошибки по MCP 2025-11-25, вычистка апострофа

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `8b6ff7f2602d1c24cbbb5c8cc31693dbf6405bc3` — вершина ветки `m18-fix1`
(M18 + fix1, в main не влиты).
Клон /home/user/exec-clones/abg-m18-fix2-20260919, ветка m18-fix2,
origin push DISABLED. Исполнитель — cx.

## Зачем

fix1 принят по живому стенду: Claude Code 2.1.278 подключается, получает текст
страницы. Ревью Codex диапазона M18+fix1 нашло четыре расхождения со
спецификацией MCP 2025-11-25; каждое координатор подтвердил по первоисточнику:

1. **ping ждёт окончания загрузки.** `serve` обрабатывает строки по одной, и
   `tools/call` (бюджет до 180 с) блокирует чтение следующих запросов.
   `basic/utilities/ping.mdx`: «The receiver **MUST** respond promptly with an
   empty response»; отправитель при таймауте «MAY» считать соединение мёртвым.
   Побочно — два вызова инструмента выполняются строго друг за другом.
2. **Ошибки аргументов уходят JSON-RPC ошибкой `-32602`.**
   `server/tools.mdx` 2025-11-25, раздел Error Handling: к протокольным ошибкам
   относятся неизвестный инструмент и запрос, не соответствующий схеме
   `CallToolRequest`; «Input validation errors (e.g., date in wrong format,
   value out of range)» — это Tool Execution Errors, «reported in tool results
   with `isError: true`». Модель видит такой результат и может исправить
   аргументы; протокольную ошибку клиент ей может не показать.
3. **`"id": null` в ответах-ошибках.** Схема 2025-11-25:
   `JSONRPCErrorResponse.required = [error, jsonrpc]`, `id` — `RequestId`,
   тип `string|integer`. `null` не допускается, поле без известного id
   опускается. Сейчас ошибка разбора и некорректный запрос отдают `id: null`,
   а запрос с `id: null` считается нормальным запросом.
4. **Апостроф в пароле обходит вычистку.** `_CREDENTIAL_URL` исключает `'` из
   userinfo, и `https://user:pa'ss@example.org/x` проходит в результат как есть.
   RFC 3986 разрешает `'` в userinfo (sub-delims).

## Что проверено вживую, а что предположение

Прочитано в `gateway/mcp_stdio.py` на BASE: `serve` читает stdin построчно и
синхронно зовёт `server.handle`; `Server.handle` пропускает `id` типов
`str`, `int`, `NoneType`; `rpc_error` всегда пишет ключ `id`; `dispatch` для
`tools/call` вызывает `arguments()`, чьи `ValueError`/`TypeError` в `handle`
превращаются в `-32602`; регулярка `_CREDENTIAL_URL` на строке 29.
Воспроизведено: `redact("https://user:pa'ss@example.org/x", None)` возвращает
строку без изменений.
Процессный чекер `docs/specs/checks/m18_fix2_process.py` (пишет и владеет
координатор) прогнан на BASE — падает на первом шаге (ответ `id=2` пришёл
раньше `ping`), и на ручной правке координатора — печатает `ok`. Заглушка API в
чекере отдаёт ответ, проходящий `validate_response`. Предположений о коде нет.

## Задача

1. **Конкурентность.** Вызовы `tools/call` выполняются в рабочих потоках
   (stdlib `threading`), чтение stdin продолжается; все прочие методы
   отвечаются сразу из цикла чтения. Одновременно выполняется не больше
   8 вызовов инструмента; лишние ждут свободного места, при этом `ping` и
   остальные методы отвечаются без ожидания. Запись в stdout — под одной
   блокировкой, по одной целой строке на сообщение. На EOF stdin сервер
   дожидается всех начатых вызовов, выводит их ответы и выходит с кодом 0.
2. **Ошибки аргументов инструмента** (нет `url`, недопустимый `url`, `format`
   вне списка, бюджет вне 1…180000, лишний ключ, неверный тип значения) —
   результат `tools/call` с `isError: true`, одним текстовым блоком
   `invalid_arguments` и тем же текстом в `structuredContent.content`
   (правило fix1). HTTP-запрос при этом не делается. Протокольной ошибкой
   `-32602` остаются: неизвестное имя инструмента, `params` не объект,
   `arguments` присутствует, но не объект.
3. **id в ошибках.** Если id запроса неизвестен (ошибка разбора JSON,
   некорректный конверт), ключ `id` в ответе ОТСУТСТВУЕТ. Запрос с
   `"id": null` — некорректный конверт: ответ `-32600` без `id`.
4. **Вычистка.** `https://user:pa'ss@example.org/x` превращается в
   `[redacted-url]`; поведение на существующих тестах вычистки не меняется.
5. **Тесты** в `tests/test_mcp_stdio.py`, ровно с такими именами в
   `MCPTests`: `test_ping_answered_during_slow_call`,
   `test_tool_calls_run_concurrently_and_bounded`,
   `test_eof_waits_for_inflight_calls`,
   `test_argument_errors_are_tool_errors`,
   `test_errors_without_id_omit_id`,
   `test_redacts_apostrophe_in_password`. Существующие тесты, которые
   закрепляли старое поведение (`-32602` на плохие аргументы, `id: null`),
   переписать под новое, а не удалить.
6. **Мутанты** в `tests/mutation_gate_gateway.py` — четыре новых, каждый
   убивается своим тестом из пункта 5: (а) `tools/call` снова выполняется
   синхронно в цикле чтения; (б) ошибка аргументов снова даёт `-32602`;
   (в) `rpc_error` снова пишет `id: None`; (г) апостроф возвращён в
   исключения регулярки. Итого в воротах 21.
7. README, раздел «MCP server»: одна-две фразы — вызовы выполняются
   параллельно (до 8), ping отвечается сразу, ошибки аргументов — ошибки
   инструмента.
8. Закоммитить эту спеку `docs/specs/m18-fix2-concurrency-errors.md` и чекер
   `docs/specs/checks/m18_fix2_process.py` byte-identical первым коммитом.

## Разрешения

Правка `gateway/mcp_stdio.py`, `tests/test_mcp_stdio.py`,
`tests/mutation_gate_gateway.py`, `README.md`. Docker-прогоны образом из
критериев (внутри контейнера сеть отключена, loopback доступен — чекер
поднимает заглушку на 127.0.0.1). Commit в клоне.

## Не трогать

Чекер `docs/specs/checks/m18_fix2_process.py` — только закоммитить, не
править. Всё прочее: `bench/**`, остальные модули `gateway/**` (включая
`gateway/client.py`), `deploy/**`, `scripts/**`, другие тесты и specs,
TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`. Сторонних
зависимостей не добавлять: `dependencies = []`; `asyncio` не вводить, хватает
`threading`. Push и merge запрещены. Ревизию `2026-07-28` не возвращать.

## Критерии приёмки

- **AC-230.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-231.** Тесты MCP зелёные, шесть новых тестов существуют, регрессия кадра Claude Code из fix1 цела:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_mcp_stdio tests.test_mcp_stdio.MCPTests.test_ping_answered_during_slow_call tests.test_mcp_stdio.MCPTests.test_tool_calls_run_concurrently_and_bounded tests.test_mcp_stdio.MCPTests.test_eof_waits_for_inflight_calls tests.test_mcp_stdio.MCPTests.test_argument_errors_are_tool_errors tests.test_mcp_stdio.MCPTests.test_errors_without_id_omit_id tests.test_mcp_stdio.MCPTests.test_redacts_apostrophe_in_password tests.test_mcp_stdio.MCPTests.test_claude_code_initialize_frame tests.test_mcp_stdio.MCPTests.test_structured_content_carries_page_text'`
- **AC-232.** Процессный чекер координатора против медленной заглушки API проходит, чекер не изменён:
  `bash -c 'echo "0181aa99b9e93f9689d4ba3442bacd66709a1c45a2b02e67c43668c60971156d  docs/specs/checks/m18_fix2_process.py" | sha256sum -c --quiet && test "$(timeout 120 docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 docs/specs/checks/m18_fix2_process.py)" = ok'`
- **AC-233.** Апостроф в пароле вычищается, прежние формы вычистки целы:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "from gateway.mcp_stdio import redact; cases={\"https://user:pa\x27ss@example.org/x\":\"[redacted-url]\",\"see https://u:p@h.example/a b\":\"see [redacted-url] b\",\"https://example.org/@user\":\"https://example.org/@user\"}; got={k: redact(k, None) for k in cases}; assert got==cases, got; assert redact(\"x tok y\", \"tok\")==\"x [redacted] y\"; print(\"ok\")"'`
- **AC-234.** Мутационные ворота шлюза: 21 мутант, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 21 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-235.** Зависимостей не прибавилось, вне разрешённых путей чисто, спека и чекер в истории:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && ! grep -q "2026-07-28" gateway/mcp_stdio.py && git diff --exit-code 8b6ff7f2602d1c24cbbb5c8cc31693dbf6405bc3 HEAD -- . ":(exclude)gateway/mcp_stdio.py" ":(exclude)tests/test_mcp_stdio.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)README.md" ":(exclude)docs/specs/m18-fix2-concurrency-errors.md" ":(exclude)docs/specs/checks/m18_fix2_process.py" && git ls-files --error-unmatch docs/specs/m18-fix2-concurrency-errors.md docs/specs/checks/m18_fix2_process.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m18-fix2-20260919 --base 8b6ff7f2602d1c24cbbb5c8cc31693dbf6405bc3 --range 8b6ff7f2602d1c24cbbb5c8cc31693dbf6405bc3..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. У Grok 19.09.2026 кончился баланс (HTTP 402):
при quota error повторов не делать, записать в note и продолжать. Если
`accept_run.py` после этого вернёт `blocked` только из-за отсутствия второго
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` в этом случае не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-230…AC-235,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"8b6ff7f2602d1c24cbbb5c8cc31693dbf6405bc3","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-230","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m18-fix2-20260919 --spec /home/user/exec-clones/abg-m18-fix2-20260919/docs/specs/m18-fix2-concurrency-errors.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер координатора требует поведения, противоречащего этой спеке; мутант не
убивается своим тестом; требуется сторонняя зависимость или правка вне
разрешённых файлов. Спеку, чекер, AC, BASE и оснастку приёмки не менять, rc не
выдумывать, чужое не трогать.
