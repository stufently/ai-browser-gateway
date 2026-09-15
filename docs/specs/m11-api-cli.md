# M11 — HTTP API и CLI: execution-спека

DRAFT: НЕ ЗАПУСКАТЬ реализацию до принятого независимого probe и замены
всех placeholders координатором. Контракт уже окончательный.

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 15.09.2026.
BASE_SHA `f336f266e22b5b5c6a31b3c30806c617f6fd3276` (Preserve M11 API contract and probe preparation).
Клон /home/user/exec-clones/abg-m11-api-cli-20260915, ветка m11-api-cli.
Исполнитель явный cx по разрешению постановщика; Spark исчерпан до
20.09.2026 15:59, timezone неизвестен; Spark/auto запрещены. Последний факт
Grok weekly2%, 5h/reset неизвестны; окна обычного cx неизвестны.
Исправления остаются cx. Независимый probe/эталоны/мутации — Grok.
Координатор пишет спецификацию и принимает; реализацию/тесты/фиксы пишет cx.
Только свой клон, push в origin/merge/deploy запрещены. Работу заберёт
координатор через fetch. Origin push отключён. Без sudo, host installs,
боевых .env/кредов, чужих деревьев/сервисов/процессов. Docker UID1002:1002
для продукта, тестов и assertions; host Python только orchestration subprocess,
без импорта продукта. Процессные/tmux опыты только Docker с фейками.

## Задача и почему

Принятая M10 реально получает страницу; агентам нужен один HTTP-запрос и
CLI с привычными режимами. Добавить transport API, форматирование и клиент,
сохранив продуктовую политику. Полный обязательный контракт прочитать целиком:
`docs/specs/m11-api-cli-contract.md`, SHA256
`80248e5768bd165f0e8ea4e0686e704f0c381b74030e4008b87569e3ec2a59ce`.
Он неизменен. Настоящий service/pool/monitoring/deployed benchmark — M12.

## Что проверено вживую, а что предположение

M10 FINAL ebb852410c3c218b41acae068b11bda653ee0dc4 принят, merge
69b6911a428c3655069359e3e2a15b86a8fd7a98. Старые bench/gateway/tests в BASE
идентичны принятому FINAL. Собственный гейт M10:398 unittest,76 frozen tests,
живой curl→patchright→Scrapling и105 исторических мутаций, rc0.
Принятая разведка Grok: /home/user/.cache/abg-coord-20260914/m10-recon-result.md,
SHA0dca8623a2aaa13e3b2f8f7478d4540184738b3bb62842cd3b78987e429b48fc;
24 Docker наблюдения, исправленный пакет. Повторять полную разведку не нужно.
Сигнатуры ProductRequest/run_product/ProductFetcher, GatewayOutcome/Attempt,
PlanStep/ProviderReply и enumvalues проверены чтением исходников координатором.
Новые make_server/limit_fetcher/render_content/client — требуемое поведение,
на BASE их нет. API не дублирует лестницу, только вызывает run_product.

cf-fetch fetch.sh и docker/fetch.js прочитаны; SHA guard ниже. Семантика пяти
режимов подтверждена исходниками; byte-exact HTML DOM formatting не обещано.
Default CLI image RepoDigest подтверждён локальным docker image inspect,
Python3.14.7 исполнялся в принятых проверках M10. Новую registry freshness
здесь не утверждаем: это имеющийся проверенный runtime; registry/deploy в M12.
Локальный живой API/CLI stand должен быть создан автором. Будущее качество
на внешних сайтах не обещается, deployed измерение отдельно в M12.

## Что сделать и что кладёт постановщик

Новые gateway/httpapi.py, gateway/format.py, gateway/client.py,
scripts/abg-fetch (executable), tests/test_gateway_api.py,
tests/test_gateway_format.py, tests/test_gateway_client.py,
tests/live_m11_api.py. Допустим новый tests/m11_helpers.py для общего stand.
Если модуль >200 строк — разнести по НОВЫМ gateway/api_*.py,
gateway/format_*.py или gateway/client_*.py без внешних dependencies;
самостоятельный client всё равно работает от одного client.py bind-mount,
поэтому его split не должен требовать соседних файлов в runtime.
README: HTTP/CLI вызов в Docker, env/file token без значений, пять режимов,
200 okfalse vs transport error, trace, общий budget и browser limit.
Не объявлять deployed service готовым раньше M12.

Выполнить все разделы контракта, включая malformed HTTP framing/body timeout,
валидацию до factory, общий semaphore, redirect refusal клиента, symlink wrapper,
успешные/неуспешные CLI stdout и отсутствие секретов в argv/логах.
Live: CLI→реальный HTTP API→реальный ProductFetcher→JS browser на своём stand.
Маркер HTML/text создаётся JS, отсутствует целиком в сыром HTML. Проверить
токен, выбранный content, wrong token и okfalse. Assertion/продукт в Docker;
host только orchestration. Run-scoped ресурсы/cleanup, loopback publication.
Нельзя заменять ProductFetcher фиктивным в live; network factory разрешена.

До запуска координатор доставляет точные файлы:
- эту окончательную execution-спеку: закоммитить docs/specs/m11-api-cli.md
  без изменений; docs/specs/m11-api-cli-contract.md уже закоммичен в BASE;
- tests/probe_m11_api_cli.py, SHA256 PROBE_PENDING, размер SIZE_PENDING;
  коммитить byte-identical, не исправлять;
- контракт уже в BASE; старые frozen probes уже там и неизменны.
Probe preparation: /home/user/.cache/abg-coord-20260914/m11/probe/preparation-result.md.
Эталоны/обходы не переносить в продукт. Зависимости только уже доступные Docker
images; новых установок нет. Если чего-то нет — безопасный blocked report.

## Не трогать

TASKS.md, CHANGELOG.md, bench/**, существующие gateway/**, tests/**,
docs/research/** и другие спеки/probes; исключение только явно перечисленные
новые файлы. Старые версии/теги/UA/stealth/raw HTTP headers не менять.
cf-fetch/skill/потребители/конфиги/профили/сервисы/креды не трогать. MCP нет.
Не исправлять старое ядро ради API и не ослаблять frozen probes/контракт.

## Критерии приёмки

- **AC-201.** Полный unittest:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-202.** Контракт и независимые probes:
  `bash -c 'echo "80248e5768bd165f0e8ea4e0686e704f0c381b74030e4008b87569e3ec2a59ce  docs/specs/m11-api-cli-contract.md" | sha256sum -c - && echo "PROBE_PENDING  tests/probe_m11_api_cli.py" | sha256sum -c - && echo "699d66eb29233728518d176c3dcc01bd1fb5c6fc29cc4860e80f56fdbf7fc013  tests/probe_m10_product.py" | sha256sum -c - && echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli'`
- **AC-203.** Живой сквозной API/CLI:
  `bash -c 'python3 tests/live_m11_api.py'`
- **AC-204.** Принятое ядро и прежние проверки неизменны:
  `bash -c 'git diff --exit-code f336f266e22b5b5c6a31b3c30806c617f6fd3276 HEAD -- bench gateway tests docs/research TASKS.md CHANGELOG.md ":(exclude)gateway/httpapi.py" ":(exclude)gateway/format.py" ":(exclude)gateway/client.py" ":(exclude)gateway/api_*.py" ":(exclude)gateway/format_*.py" ":(exclude)gateway/client_*.py" ":(exclude)tests/test_gateway_api.py" ":(exclude)tests/test_gateway_format.py" ":(exclude)tests/test_gateway_client.py" ":(exclude)tests/live_m11_api.py" ":(exclude)tests/m11_helpers.py" ":(exclude)tests/probe_m11_api_cli.py"'`
- **AC-205.** Состав и чистота:
  `bash -c 'git ls-files --error-unmatch gateway/httpapi.py gateway/format.py gateway/client.py scripts/abg-fetch tests/test_gateway_api.py tests/test_gateway_format.py tests/test_gateway_client.py tests/live_m11_api.py tests/probe_m11_api_cli.py docs/specs/m11-api-cli.md docs/specs/m11-api-cli-contract.md >/dev/null && test -x scripts/abg-fetch && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`
- **AC-206.** Существующий cf-fetch неизменен:
  `bash -c 'echo "7de3f29111b1caf5ee260ef10449983a6048692200f7f5f942ead52ff54d1b9d  /home/user/.claude/skills/cf-fetch/fetch.sh" | sha256sum -c - && echo "cc160725c815915169969b8099882ddbed18cad91ceb9f8d96835e9e034ae2a8  /home/user/.claude/skills/cf-fetch/docker/fetch.js" | sha256sum -c -'`

Новый probe/состав/live на BASE красны из-за отсутствия API, не среды.
Baseline подготовка приложена. Исторические мутации M10 повторены при её
приёмке на byte-identical ядре; новый gate проверяет его неизменность,
полный unit и frozen M9/M10. Независимые мутации НОВЫХ tests обязательны.

## Авторевью

cross-review-v1. Автор сам коммитит REVIEW_SHA до ревью, полный BASE..REVIEW.
Параллельно read-only Grok+agy через абсолютный
/home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh initial,
backend grok/agy, --clone свой клон --base BASE_SHA --range BASE_SHA..REVIEW_SHA.
В одинаковый context включить ПОЛНЫЙ неизменный контракт M11, он уже в BASE.
ASK_MAX_FINDINGS=12; AGY_MODEL=gemini-3.8-flash-high; AGY_TIMEOUT=900.
Дополнительно обязательный проектный read-only Codex result:
`bash ~/.claude/skills/ask-codex/scripts/run.sh result '<тот же контекст>' --file REVIEW_DIR/full.diff`.
Оба обязательных проектных ревью Codex+Gemini запускаются параллельно.
Ревьюеры только читают; не исполняют мутации/тесты, меняющие shared tree.
Каждый фактический review input <100000 байт. Нельзя обрезать/делить неполно;
если initial слишком велик — остановиться ДО ревью. Полный initial и полный
verify delta могут суммарно превышать лимит, если оба приняты без truncation.
Один технический повтор незавершённого вызова, quotaerror без retry.
Требуется полный вердикт и findings; «Находок нет.» с точкой. Ceiling/truncation
или отсутствие итогового вердикта — incomplete независимо от rc.
Сохранить raw/rc/SHA; квитанции создаёт только review_run.sh, не руками.
После всех initial результатов единый список fixed/disproved с уликами либо
needs_owner; один заход fixes, те же ревьюеры один verify на REVIEW..FINAL.
Не повторять валидное ревью неизменного кода. Новая находка/спор verify —
needs_owner; известных дефектов не переносить в backlog вместо исправления.

## Контракт отчёта и приёмка

report.json v2 untracked в корне, ровно6 критериев AC-201…AC-206,
command посимвольно из спеки; blocked rc=null с безопасной уликой.
```json
{"schema_version":2,"policy_id":"cross-review-v1",
 "spec_sha256":"<SHA256 этой окончательной execution-спеки>",
 "base_sha":"f336f266e22b5b5c6a31b3c30806c617f6fd3276","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<точная модель и reasoning в улике>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready",
 "criteria":[{"id":"AC-201","status":"pass|fail|blocked","command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Автор запускает ПОЛНЫЙ gate, не только dry-run:
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m11-api-cli-20260915 --spec /home/user/exec-clones/abg-m11-api-cli-20260915/docs/specs/m11-api-cli.md --timeout 3600`.
Пакет /home/user/.cache/abg-coord-20260914/m11/author/: full.diff, BASE/REVIEW/FINAL,
commands/cwd/rc/logs Docker/live, receipts/raw/resolutions/SHA256SUMS.
После пакета противоположный Grok получает отдельное задание на FINAL_SHA:
мутации новых tests, baseline green, доказанная активация, assertion kills,
0 survived/invalid, finally restore/SHA. Автор cx их не подменяет.
Grok собирает итоговый пакет. Координатор сам читает полный diff, проверяет
SHA/логи/ревью и один полный accept_run; тот же suite второй раз не повторяет.
Зелёный gate не разрешает push и не заменяет разбор известных дефектов.

## Контракт на невыполнимое и стык

При противоречии/блокере остановиться, report-blocked.md с command/cwd/rc,
безопасным дословным выводом. Не менять frozen probe/contract/AC, не обходить
launcher/среду, не выдумывать факты/квоты. Дефекты приёмки возвращаются cx.
M12 получает работающие HTTP/CLI interfaces и browser limiter; service config,
proxy pool rotation, production token/compose/healthchecks/benchmark — следующая
веха, не скрытая часть этого кода. cf-fetch переключает только владелец.
