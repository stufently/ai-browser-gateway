# M19-fix1 — прокси из окружения не доходят до провайдеров, сигнал убивает probe

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `1bf5099c2392556762549d907b0f234f5bf91886` — вершина ветки
`m19-oneshot-image` (результат M19, в main не влит).
Клон /home/user/exec-clones/abg-m19-fix1-20260919, ветка m19-fix1,
origin push DISABLED. Исполнитель — cx.

## Зачем

M19 принята по существу: образ собирается, чекер проходит от root и 1002, на
живом `https://www.bizprofile.net/` образ от root с дефолтным `/dev/shm` дал
`ok=true`, `scrapling`, 14 с. Ревью Codex нашло два расхождения, координатор
воспроизвёл оба внутри образа `abg-oneshot:m19`:

1. **Прокси из окружения уходят в probe.** `LocalLauncher` копирует окружение
   вызывающего целиком, а `curl_cffi` сам берёт `https_proxy`/`HTTPS_PROXY`.
   Опыт: `-e https_proxy=http://127.0.0.1:9` → `https://example.com/
   --no-browser` даёт `ok=false`, `provider_error`, при этом попытка подписана
   `egress_profile=direct`; без переменной — `ok=true`. В боевом шлюзе такого
   нет: `docker run` окружение хоста не наследует. В поде CI прокси-переменные
   вполне могут быть заданы раннером.
2. **Сигнал CLI не доходит до probe.** Probe запущен в своей сессии
   (`start_new_session=True`), обработчиков сигналов у CLI нет. Опыт под
   `tini -s` (зомби не считаются): SIGTERM CLI во время шага браузера → CLI
   умирает (`-15`), а 15 живых процессов (`xvfb-run`, `Xvfb`, `probe.py`,
   `chrome`) остаются и через 12 с. Джоба, проверяющая сайты по очереди с
   `timeout` на каждый, оставит браузер прошлого сайта работать параллельно
   со следующим.

Для протокола: «утечка» осиротевших процессов после обычного прогона, которую
координатор сначала заподозрил, оказалась зомби — под настоящим PID 1 образа
(`tini`) живых остатков 0, и после таймаута тоже 0. Это НЕ входит в веху.

## Что проверено вживую, а что предположение

Прочитано в `gateway/oneshot.py` на BASE: `LocalLauncher.run` строит
`child_env = dict(os.environ if env is None else env)`, добавляет
`ABG_PROVIDER`, запускает `Popen(..., start_new_session=True)`, на
`TimeoutExpired` делает `os.killpg(proc.pid, SIGKILL)`; `main` обработчиков
сигналов не ставит. `bench.runner.fetch._fetch` передаёт в launcher окружение
без `ABG_PROXY` для direct (прокси шлюза ходит только через `ABG_PROXY`).
Чекер `docs/specs/checks/m19_fix1_process.py` (пишет и владеет координатор)
прогнан: на BASE падает на шаге прокси (`provider_error`); на ручной правке
координатора (фильтр переменных прокси по имени без учёта регистра + обработчик
SIGTERM/SIGINT/SIGHUP, убивающий группы активных probe и выходящий с кодом 4)
печатает `ok` от root и от 1002, и чекер M19 на той же правке — `ok`.
Предположений о коде нет.

## Задача

1. В `LocalLauncher`: из окружения probe убираются переменные с именами
   `http_proxy`, `https_proxy`, `all_proxy`, `ftp_proxy`, `no_proxy` в любом
   регистре. `ABG_PROXY` (механизм egress шлюза) не трогать.
2. CLI на SIGTERM, SIGINT и SIGHUP: убивает группы процессов всех активных
   probe (SIGKILL), пишет в stderr одну строку `{"error": "interrupted"}`,
   stdout пуст, выходит с кодом **4**. Обработчики ставятся в `main` только на
   время прогона лестницы (юнит-тесты, вызывающие `LocalLauncher` напрямую, не
   должны получать глобальные обработчики).
3. README, раздел «One-shot image»: код 4 — прерван сигналом; переменные прокси
   окружения игнорируются, образ всегда ходит direct.
4. Тесты в `tests/test_oneshot.py`, класс `OneshotTests`, ровно с именами
   `test_proxy_environment_not_forwarded` и
   `test_signal_kills_active_probe_groups`.
5. Мутанты в `tests/mutation_gate_gateway.py` — два новых, каждый убивается
   своим тестом из пункта 4: (а) фильтр переменных прокси отключён;
   (б) обработчик сигнала не убивает группы. Итого 27.
6. Закоммитить эту спеку `docs/specs/m19-fix1-env-signals.md` и чекер
   `docs/specs/checks/m19_fix1_process.py` byte-identical первым коммитом.

## Разрешения

Правка `gateway/oneshot.py`, `tests/test_oneshot.py`,
`tests/mutation_gate_gateway.py`, `README.md`. Сборка образа (сеть только на
сборку) и прогоны образом из критериев. Commit в клоне.

## Не трогать

Чекеры `docs/specs/checks/*.py` — только закоммитить новый, не править ни
один. `deploy/Dockerfile.oneshot`, `bench/**`, прочие модули `gateway/**`,
`deploy/Dockerfile`, `deploy/compose.yaml`, `scripts/**`, другие тесты и specs,
TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`, registry
(ничего не push'ить). `pyproject.toml`: `dependencies = []`. Push и merge
запрещены.

## Критерии приёмки

- **AC-260.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-261.** Тесты one-shot зелёные, два новых теста существуют:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_oneshot tests.test_oneshot.OneshotTests.test_proxy_environment_not_forwarded tests.test_oneshot.OneshotTests.test_signal_kills_active_probe_groups'`
- **AC-262.** Образ пересобирается из текущего дерева:
  `bash -c 'docker build -q -f deploy/Dockerfile.oneshot -t abg-oneshot:m19 . >/dev/null'`
- **AC-263.** Чекер fix1 внутри образа под tini, от 1002 и от root; чекер не изменён:
  `bash -c 'echo "72ae5dfb854470b159bc9511d3e83ea819f820d09b41f3836dc3ef75d6f0dddb  docs/specs/checks/m19_fix1_process.py" | sha256sum -c --quiet && for u in 1002:1002 0:0; do test "$(timeout 900 docker run --rm --network none --user $u --entrypoint /usr/bin/tini -v "$PWD/docs/specs/checks/m19_fix1_process.py:/check.py:ro" abg-oneshot:m19 -s -- python3 /check.py)" = ok || exit 1; done'`
- **AC-264.** Чекер M19 по-прежнему проходит, не изменён:
  `bash -c 'echo "ba67a2a044f8acde01c3195643b932a514dc4a1af642622d9b21251c74526aec  docs/specs/checks/m19_oneshot_image.py" | sha256sum -c --quiet && test "$(timeout 900 docker run --rm --network none --user 0:0 --entrypoint python3 -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m19 /check.py)" = ok'`
- **AC-265.** Мутационные ворота шлюза: 27 мутантов, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 27 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-266.** Вне разрешённых путей чисто, спека и чекер в истории:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && git diff --exit-code 1bf5099c2392556762549d907b0f234f5bf91886 HEAD -- . ":(exclude)gateway/oneshot.py" ":(exclude)tests/test_oneshot.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)README.md" ":(exclude)docs/specs/m19-fix1-env-signals.md" ":(exclude)docs/specs/checks/m19_fix1_process.py" && git ls-files --error-unmatch docs/specs/m19-fix1-env-signals.md docs/specs/checks/m19_fix1_process.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m19-fix1-20260919 --base 1bf5099c2392556762549d907b0f234f5bf91886 --range 1bf5099c2392556762549d907b0f234f5bf91886..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 — при quota error повторов не делать, записать в note и
продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-260…AC-266,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"1bf5099c2392556762549d907b0f234f5bf91886","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-260","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m19-fix1-20260919 --spec /home/user/exec-clones/abg-m19-fix1-20260919/docs/specs/m19-fix1-env-signals.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер координатора требует поведения, противоречащего этой спеке; мутант не
убивается своим тестом; требуется правка вне разрешённых файлов. Спеку,
чекеры, AC, BASE и оснастку приёмки не менять, rc не выдумывать, чужое не
трогать, ничего не публиковать в registry.
