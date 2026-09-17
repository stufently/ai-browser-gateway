# M12a-fix — исправление сервиса после verify

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `62de539f586b95e6aeb971c3ab1f51e6f7080260` — FINAL непринятой M12a.
Клон /home/user/exec-clones/abg-m12a-fix-20260917, ветка m12a-fix,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026:
оставшиеся задачи M12 через Codex). Frozen regression probe и мутации готовила
ДРУГАЯ cx-панель; её эталоны, обходы и пакет не читать и в клон не переносить.

Только этот клон. Push/merge/production deploy запрещены, работу заберёт
координатор через fetch. Без sudo, host installs, production .env/кредов,
чужих деревьев/сервисов. Продукт, import и assertions — только в Docker
1002:1002; host — orchestration/git/files. Эксперименты с сигналами и
процессами — только внутри Docker и только в своих процессах; host tmux socket,
`tmux kill-server`, сигналы в чужие процессы запрещены. Секреты не попадают
в stdout/argv/git/образы.

## Задача

Закрыть единый список дефектов `docs/specs/m12a-return-findings.md` (прочитать
целиком) без изменения контракта `docs/specs/m12a-service-contract.md`
(SHA256 9231045abeef2a7eef8722ac655f4121d824bdec883d50f421654917b88b58df,
прочитать целиком, byte-identical):

1. **Shutdown race (verify-codex-1:F001).** Сейчас `gateway/service.py:main`
   зовёт `server.shutdown` в helper thread, потом `server_close`, два
   `sweep_providers` и `sleep(0.2)`. Handler threads daemon, ожидание browser
   semaphore (`limit_fetcher` из `gateway/api_limit.py`) не отменяется —
   ожидающий обработчик запускает provider после последней уборки. Нужно:
   после начала shutdown этой установки новый provider launch не начинается
   (в том числе у запроса, уже ждущего слот, и у уже допущенного, но
   задержанного запуска); уже идущие запуски завершаются или убираются;
   shutdown ограничен по времени; финальная уборка идёт ПОСЛЕ того, как
   запуск стал невозможен. Scope уборки owner+instance+role не ослаблять,
   default `make_server` из M11 без service-wiring ведёт себя как раньше.
   Способ выбираешь сам; ядро (`gateway/api_limit.py`, transport) не менять —
   шов на стороне `gateway/service.py` / `LabeledLauncher` / `api_http`.
2. **Sidecar-цикл не доказан (Codex F006).** Live должен доказать
   АВТОМАТИЧЕСКИЕ ping success и ping/fail от настоящего Compose-сервиса
   `monitor` из собранного release, на своём receiver, без ручного
   `check_once` и без второго monitor из checkout. Пассивная Cmd у sidecar
   обязана валить live (на BASE live с `sleep 3600` вместо monitor прошёл
   rc=0 — подтверждённая дыра).
3. **Proxy whitespace/control.** `_proxy` принимает U+00A0 и U+0085. Контракт
   запрещает whitespace/control: отказ fail-closed в `make_service` до bind;
   допустимые HTTP(S), userinfo, порт сохраняются.
4. **Symlink manifest.** `scripts/abg-release` `manifest()` принимает symlink
   `manifests/<sha>.sha256` как файл. Отказ без изменения внешнего target;
   обычный manifest и повтор работают.
5. **Авторские unit-tests.** Сейчас 6 методов. Добавить содержательные
   проверки: service config fail-closed (token/profiles/permissions/instance/
   port/limit), opt-in rotation и конкурентность/копии profiles, labels/argv
   launcher, scoped sweep, health result/redirect refusal/timeout/ping-failure/
   redaction, provision (encoding, ровно 15, no-overwrite, атомарность, отказ
   источника), release (режимы файлов и каталогов, symlink, mismatch), и
   shutdown из п.1. Тесты проверяют ПРИЧИНУ отказа, а не только факт отказа.
   Независимая мутация 24 вариантов на BASE дала 8 kills и 15 survivors;
   непокрыты: `make_service` целиком (методы его не вызывают), таймаут
   cleanup-команды, `check_once` целиком (health test зовёт только `_url`),
   пароль/ровно 15 (ms16 не исключён)/атомарность/duplicate source в
   provision, mode 0644 обычных release-файлов. Новые тесты обязаны убивать
   именно эти изменения поведения. После сдачи их снова мутирует независимая
   cx-панель; выжившие мутанты — дыры.
6. **Live-доказательства контракта.** Дополнить `tests/live_m12_service.py`:
   фактические user/group/read-only/loopback-публикация/mounts у api, monitor
   и providers по `docker inspect`; занятость browser-slot наблюдаемым
   барьером, а не `sleep 0.5`; отдельный фактический egress КАЖДОГО из двух
   rotation-запросов (свой счётчик на профиль), а не «был любой hit».
   Старые M9–M11 suites не дублировать.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением FINAL: тела `service.py`
(`LabeledLauncher`, `sweep_providers`, `_proxy`, `make_service`, `main`),
`health_monitor.py`, `deploy/Dockerfile`, `deploy/compose.yaml`, дифф
`httpapi.py`/`api_http.py` (rotation под `rotate_lock`). 6 авторских tests
green в Docker 1002:1002 на `python@sha256:cad9a2c…` (Ran 6, OK).
cf-fetch SHA ниже совпали 17.09. Образы python/docker из Dockerfile есть локально.
Проверено 17.09 независимой панелью: frozen probe на BASE assertion-red
(5 failures, 0 errors); два разных эталона, меняющих только
`gateway/service.py` и `scripts/abg-release`, — green, то есть гонка
закрывается без правки `gateway/api_limit.py`. Эталоны тебе не передаются.

Швы, на которые опирается probe (существующие, не новые): browser semaphore
доступен как `server.slots` у объекта из `make_service`, и обработчик
захватывает именно его через `limit_fetcher`; `service.main()` после SIGTERM
возвращает 0; `abg-release` сообщает отказ строкой
`{"error":"invalid_configuration"}` в stderr. Ожидающий обработчик после
shutdown может как ответить, так и закрыть соединение.

## Что лежит в клоне до запуска

- `docs/specs/m12a-fix.md` (эта спека), `m12a-return-findings.md` — коммитить
  byte-identical;
- `tests/probe_m12_service_regressions.py`, SHA256 f7ab236f81fccdddf5fd9df9611b9a2f3f3f33dd3162865c083a22a8d569ecad — frozen, не менять;
- краткая базовая линия пробника `docs/specs/m12a-fix-probe-baseline.md`.

## Разрешения

Код/тесты в клоне, docker build и свои локальные Compose-стенды со своими
label, синтетические secrets/proxy/health receiver, read-only reviews, commit.

## Не трогать

bench/**, gateway/{models,engine,plan,product,fetch,format*,client*,api_limit}.py,
`gateway/httpapi.py` вне service-wiring, старые tests и все frozen probes,
контракт, docs/research/**, другие specs, TASKS.md, CHANGELOG.md, cf-fetch,
.github/workflows, production services/config/секреты. Не менять transport
bind, provider versions/images/fingerprints, challenge/expected_text и budget.

## Критерии приёмки

- **AC-401.** Полный unittest:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-402.** Контракт и все frozen probes неизменны и green:
  `bash -c 'echo "9231045abeef2a7eef8722ac655f4121d824bdec883d50f421654917b88b58df  docs/specs/m12a-service-contract.md" | sha256sum -c - && echo "f7ab236f81fccdddf5fd9df9611b9a2f3f3f33dd3162865c083a22a8d569ecad  tests/probe_m12_service_regressions.py" | sha256sum -c - && echo "2b5713ea3d3b743a6c469bd26bd893cb343f132b83deb7eadc6182e007ad71e0  tests/probe_m12_service.py" | sha256sum -c - && echo "509d765167bd322d0b2f5c40127a95ed977760af8bd4a35c03a830267dc10997  tests/probe_m11_api_cli.py" | sha256sum -c - && echo "699d66eb29233728518d176c3dcc01bd1fb5c6fc29cc4860e80f56fdbf7fc013  tests/probe_m10_product.py" | sha256sum -c - && echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-403.** Live: build, release, Compose, CLI/API, browser slot, egress по профилям, автоматический sidecar-цикл, restart, cleanup:
  `bash -c 'python3 tests/live_m12_service.py'`
- **AC-404.** Вне разрешённых путей ничего не изменено (всё дерево, whitelist):
  `bash -c 'git diff --exit-code 62de539f586b95e6aeb971c3ab1f51e6f7080260 HEAD -- . ":(exclude)gateway/service*.py" ":(exclude)gateway/health_monitor*.py" ":(exclude)gateway/api_http.py" ":(exclude)gateway/httpapi.py" ":(exclude)tests/test_service*.py" ":(exclude)tests/test_health_monitor*.py" ":(exclude)tests/test_provision*.py" ":(exclude)tests/test_release*.py" ":(exclude)tests/live_m12_service.py" ":(exclude)tests/m12_*.py" ":(exclude)tests/probe_m12_service_regressions.py" ":(exclude)docs/specs/m12a-fix.md" ":(exclude)docs/specs/m12a-fix-probe-baseline.md" ":(exclude)docs/specs/m12a-return-findings.md" ":(exclude)deploy" ":(exclude)scripts/abg-release" ":(exclude)scripts/abg-provision" ":(exclude)README.md"'`
- **AC-405.** Состав, executable и чистое дерево:
  `bash -c 'git ls-files --error-unmatch gateway/service.py gateway/health_monitor.py deploy/Dockerfile deploy/compose.yaml scripts/abg-release scripts/abg-provision tests/live_m12_service.py tests/probe_m12_service_regressions.py docs/specs/m12a-fix.md >/dev/null && test -x scripts/abg-release && test -x scripts/abg-provision && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`
- **AC-406.** cf-fetch неизменен:
  `bash -c 'echo "7de3f29111b1caf5ee260ef10449983a6048692200f7f5f942ead52ff54d1b9d  /home/user/.claude/skills/cf-fetch/fetch.sh" | sha256sum -c - && echo "cc160725c815915169969b8099882ddbed18cad91ceb9f8d96835e9e034ae2a8  /home/user/.claude/skills/cf-fetch/docker/fetch.js" | sha256sum -c -'`

deploy/**, scripts/abg-release, scripts/abg-provision, README.md и
service-wiring в gateway/httpapi.py меняются по необходимости; AC-404 их
исключает намеренно, их проверяют live и координатор по диффу. Любой другой
путь (.gitignore, pyproject.toml, scripts/abg-fetch, .github/**, bench, ядро)
AC-404 ловит.

## Авторевью

Политика cross-review-v1. После commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial codex --clone <клон> --base <BASE_SHA> --range <BASE_SHA>..<REVIEW_SHA> --context "<return-findings + контракт; только чтение>"`
и тот же wrapper `initial agy` с теми же BASE/range/context. Оба reviewers
только читают. Разобрать ВСЕ finding_id обоих: fixed с proof/commit,
disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verification теми
же reviewers на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Новые дефекты после verify
не чинить: needs_owner, FINAL сохранить.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-401…AC-406,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"62de539f586b95e6aeb971c3ab1f51e6f7080260","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-401","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m12a-fix-20260917 --spec /home/user/exec-clones/abg-m12a-fix-20260917/docs/specs/m12a-fix.md --timeout 3600`.
Пакет в /home/user/.cache/abg-coord-20260917/m12a-fix/author/: BASE/REVIEW/FINAL,
full.diff, report, логи команд с rc, receipts/resolutions, SHA256SUMS без
самоссылок.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
закрыть гонку нельзя без правки запрещённых файлов; frozen probe требует
поведения, противоречащего контракту; нужен реальный секрет или внешняя цель.
Спеку, probe, AC, BASE и оснастку не менять, quota/rc не выдумывать,
несовместимость не обходить.
