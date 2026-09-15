# M12a — Docker-сервис, пул и локальная поставка

Окончательная execution-спека после принятого frozen probe.
Обновлённая директива владельца15.09 снимает прежний HOLD и разрешает продолжение.

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 15.09.2026.
BASE_SHA `7ca38c1aa62174a0a1de1a7685fee268c2ba2042` (Resume milestones under updated owner directive).
Клон /home/user/exec-clones/abg-m12a-service-20260915, ветка m12a-service.
Новая продуктовая спека идёт явному Grok: Spark исчерпан до20.09 15:59,
timezone неизвестен; auto/Spark/cx для реализации не запускать. Grok reset
подтверждён15.09, разведка выполнена без quota error; окна5h/weekly неизвестны.
Исправления до verify остаются Grok, монетка не повторяется. После verify
новый дефект → новая веха от прежнего FINAL, не второй FIX_ONCE на этом BASE.

Только этот клон, origin push DISABLED. Push/merge/production deploy запрещены.
Работу заберёт координатор через fetch. Координатор пишет только спеки и
принимает; реализация/tests/фиксы — исполнители. Противоположный cx подготовил
frozen probe и отдельно выполнит мутации новых авторских tests на FINAL.
Без sudo, host installs, production .env/кредов, чужих деревьев/сервисов.
Продукт/import/assertions в Docker1002:1002; host только orchestration/git/files.
Процессы/tmux эксперименты исключительно Docker с фейками, host tmux socket
и чужие процессы запрещены. No secrets в stdout/argv/git/образах.

## Задача и что проверено вживую

M11 принята владельцем на e6f7f0c и опубликована merge e5fd997.
M12a создаёт локально проверяемую поставку; M12b потом разворачивает принятый
код на stand-host и делает уже разрешённые15proxy/all-valid-target замеры.
Весь обязательный контракт: docs/specs/m12a-service-contract.md,
SHA256 9231045abeef2a7eef8722ac655f4121d824bdec883d50f421654917b88b58df. Прочитать целиком; byte-identical, не менять.

Принятая Grok-разведка /home/user/.cache/abg-coord-20260915/m12/recon-result.md,
SHA ceaf2f6efcad8cb8027fef695bd5903de2ad3140e3e3cc21491eb408ac9543e7;
78hashes проверены, unknown historical rc сохранены, host-import не было.
Тела make_server/Handler/ProductFetcher/DockerLauncher/load_profiles/build_argv
и PROBE_FILE дополнительно прочитаны координатором. Имена НОВЫХ модулей и
функций контракта — требования, а не утверждение, что они уже существуют.
Ротация opt-in, defaultmake_server и API M11 остаются прежними.

Registry15.09: Python3.14.7-slim index cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6;
Docker29.8.0-cli index eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66.
Оба присутствуют локально, host Docker29.8.0, group983, compose5.5.1.
COPY docker binary в Python образ — гипотеза до build/run, не обещание успеха.
Service-dir отсутствовал, host8765свободен при разведке; tests используют свой
временный root и свободный loopback-port, не production path.

## Что сделать и что кладёт постановщик

Новые gateway/service*.py, gateway/health_monitor*.py,
deploy/Dockerfile, deploy/compose.yaml, scripts/abg-release,
scripts/abg-provision, tests/test_service*.py, tests/test_health_monitor*.py,
tests/test_provision*.py, tests/test_release*.py, tests/live_m12_service.py,
при необходимости новые tests/m12_*.py helpers. README — краткое использование.
Менять gateway/httpapi.py и gateway/api_http.py ТОЛЬКО для opt-in rotation
и минимального нового service wiring; остальное существующее ядро неизменно.
Не прятать production code в tests. Модули разделять по смыслу; полный initial
review input<100000bytes. При угрозе лимита сначала убирать дублирование,
не ослаблять критерии и не обрезать reviewers input.

Выполнить весь контракт: make_service/fail-closed файловая конфигурация,
конкурентная ротация и стабильные копии, thin labeled launcher и только scoped
cleanup, health loop/redirect refusal/redaction, pinned runtime/Compose,
prepare release из commit, atomic15profile provisioning на FAKE source.
Production management API/3proxy.env не читать и не вызывать до M12b.

До запуска положены:
- execution-спека docs/specs/m12a-service.md: коммитить byte-identical;
- contract уже в BASE, SHA выше;
- tests/probe_m12_service.py, SHA 2b5713ea3d3b743a6c469bd26bd893cb343f132b83deb7eadc6182e007ad71e0,
  размер 36067, коммитить byte-identical;
- baseline summary /home/user/.cache/abg-coord-20260915/m12/probe/probe-baseline.md.
Эталоны/обходы/контекст независимого автора не читать и в clone не переносить.
Старые frozen probes доступны в BASE. Новых host dependencies нет.

## Разрешения

Разрешены код/тесты в клоне, Dockerbuild и свои локальные Compose-стенды,
синтетические secrets/proxy/healthreceiver, read-only reviews и commit.
Production deploy, чтение реальныхcredentials и внешние целевые замеры —
M12b после приёмки этого кода. Никаких изменений внешней оснастки.

## Не трогать

bench/**, gateway/{models,engine,plan,product,fetch,format*,client*,api_limit}.py,
старыеtests иfrozenprobes, docs/research/**, другиеspecs, TASKS.md, CHANGELOG.md,
cf-fetch/потребителей, .github/workflows, production services/config/секреты.
Из existing допускаются только README/httpapi/api_http как указано выше.
Не менять transport bind, provider versions/images/fingerprints, challenge/
expected_text и общий budget. Новую execution-спеку/probe коммитить без правок.

## Критерии приёмки

- **AC-301.** Полный unittest один раз:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-302.** Frozen contract/probes:
  `bash -c 'echo "9231045abeef2a7eef8722ac655f4121d824bdec883d50f421654917b88b58df  docs/specs/m12a-service-contract.md" | sha256sum -c - && echo "2b5713ea3d3b743a6c469bd26bd893cb343f132b83deb7eadc6182e007ad71e0  tests/probe_m12_service.py" | sha256sum -c - && echo "509d765167bd322d0b2f5c40127a95ed977760af8bd4a35c03a830267dc10997  tests/probe_m11_api_cli.py" | sha256sum -c - && echo "699d66eb29233728518d176c3dcc01bd1fb5c6fc29cc4860e80f56fdbf7fc013  tests/probe_m10_product.py" | sha256sum -c - && echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service'`
- **AC-303.** Live runtime/build/release/Compose/CLI/API/browser/egress/monitor/restart и cleanup:
  `bash -c 'python3 tests/live_m12_service.py'`
- **AC-304.** Принятый код, старыеtests и данные неизменны:
  `bash -c 'git diff --exit-code 7ca38c1aa62174a0a1de1a7685fee268c2ba2042 HEAD -- bench gateway tests docs/research TASKS.md CHANGELOG.md ":(exclude)gateway/httpapi.py" ":(exclude)gateway/api_http.py" ":(exclude)gateway/service*.py" ":(exclude)gateway/health_monitor*.py" ":(exclude)tests/test_service*.py" ":(exclude)tests/test_health_monitor*.py" ":(exclude)tests/test_provision*.py" ":(exclude)tests/test_release*.py" ":(exclude)tests/live_m12_service.py" ":(exclude)tests/m12_*.py" ":(exclude)tests/probe_m12_service.py"'`
- **AC-305.** Состав, executable и чистота:
  `bash -c 'git ls-files --error-unmatch gateway/service.py gateway/health_monitor.py deploy/Dockerfile deploy/compose.yaml scripts/abg-release scripts/abg-provision tests/live_m12_service.py tests/probe_m12_service.py docs/specs/m12a-service.md docs/specs/m12a-service-contract.md >/dev/null && test -x scripts/abg-release && test -x scripts/abg-provision && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`
- **AC-306.** Прежнийcf-fetch неизменен:
  `bash -c 'echo "7de3f29111b1caf5ee260ef10449983a6048692200f7f5f942ead52ff54d1b9d  /home/user/.claude/skills/cf-fetch/fetch.sh" | sha256sum -c - && echo "cc160725c815915169969b8099882ddbed18cad91ceb9f8d96835e9e034ae2a8  /home/user/.claude/skills/cf-fetch/docker/fetch.js" | sha256sum -c -'`

Предпусковой Grok выполняет шесть команд без реализации; результат
/home/user/.cache/abg-coord-20260915/m12/preflight/result.md. Ожидание:
existing fullunit/invariants/cf-fetch green; новыйprobe/live/состав red
по отсутствию M12service, не среды. Реализация только после принятия этой
проверки координатором. Принятые обаэталона20/20 и36мутационных отказов
новогоprobe повторять не нужно: он и контракт неизменны. Полные suites
M9–M11 отдельно не повторять: frozen + unit покрывают затронутые interfaces.
Live проверяет наблюдаемое поведение на свежесобранном image/committed release;
локальный root, synthetic secrets/proxy/receiver, assertions в Docker.

## Авторевью

Политика cross-review-v1. Автор Grok запускает read-only Codex+agy Gemini
параллельно на BASE..REVIEW после commit; оба нужны, не обрезать input.
AGY_MODEL=gemini-3.8-flash-high, AGY_TIMEOUT=900. Квитанции только штатным
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial codex --clone <клон> --base <BASE_SHA> --range <BASE_SHA>..<REVIEW_SHA> --context "<полный контракт; только чтение>"`
и тем же wrapper initial agy с теми же BASE/range/context в отдельном контексте.
Wrapper использует ask-codex result и ask-agy result; не ручные receipts.
Оба reviewers не правят дерево. Дождаться обоих, triage всехfindings:
fixed сproof/commit, disproved сproof, иначе needs_owner. ОДИН FIX_ONCE;
те же два reviewers verification на REVIEW..FINAL. Без изменений и споров
verify пропускается. Неполный ответ/таймаут без вердикта не принятие.
Один технический повтор незавершённого вызова; quotaerror без повторов.
Валидные ревью неизменного кода не повторять. После VERIFY_ONLY новые дефекты
не исправлять в этой вехе — needs_owner, сохранитьFINAL для новойвехи.

## Контракт отчёта

report.json v2 untracked, ровно 6 записей AC-301…AC-306. command изспеки
посимвольно; blocked rc=null, безопасный текстошибки. Поля:
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA execution>",
 "base_sha":"7ca38c1aa62174a0a1de1a7685fee268c2ba2042","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"grok","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-301","status":"pass|fail|blocked",
 "command":"<изспеки>","rc":0,"note":"<улика>"}]}
```
Автор выполняет полный gate:
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m12a-service-20260915 --spec /home/user/exec-clones/abg-m12a-service-20260915/docs/specs/m12a-service.md --timeout 3600`.
Пакет /home/user/.cache/abg-coord-20260915/m12/author/: BASE/REVIEW/FINAL,
full.diff,report,commands/cwd/rc/logs,receipts/raw/resolutions,manifestSHA256.
После пакета противоположный исполнитель проверяет НОВЫЕ авторскиеtests
мутациями: baselinegreen, активация, assertionkills, restores/sourceSHA,
0survived/invalid, эквивалентные отдельно. Grok собирает итоговый пакет,
автора мутаций не подменяет. Координатор читает полныйdiff и проверяетSHA/
всеreviews/логи, один полный gate и live; тотжеsuite второйраз не нужен.

## Контракт на невыполнимое и стык

Остановиться с одним списком blocker и evidence; не менятьspec/probe/AC/
оснастку/BASE, не выдумыватьquota/rc. Подтверждённые дефекты не откладывать.
M12b начинает deploy после принятогоM12a: он исполнит приватное provisioning,
healthchecks create/history, реальные15echo и6целейAPI. Локальный стендM12a
этим замером не является. DNS/public443/WAF и чужие сервисы за владельцем.
