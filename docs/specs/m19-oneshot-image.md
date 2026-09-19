# M19 — самодостаточный образ с лестницей и CLI для чужого CI

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `fc5e9cff194132827c354c808712c0914408e52f` — вершина main.
Клон /home/user/exec-clones/abg-m19-20260919, ветка m19-oneshot-image,
origin push DISABLED. Исполнитель — cx.

## Зачем

Владелец 19.09.2026: check-sites (мониторинг сайтов, GitLab CI в Kubernetes)
должен для сайтов за Cloudflare-челленджем вызывать проверку **образом
ai-browser-gateway**. Сейчас так нельзя по двум причинам:

1. Оба наших CLI (`scripts/abg-fetch`, `scripts/abg-mcp`) — клиенты развёрнутого
   API на stand-host (`127.0.0.1:8765`), а из кластера он не виден.
2. Сама лестница запускает каждого провайдера отдельным `docker run` через
   `docker.sock` (`bench/providers/registry.build_argv`,
   `bench/runner/execute.DockerLauncher`). В поде CI docker-демона нет: образы
   check-sites собираются через `buildx` с драйвером `kubernetes`.

Нужен один образ, в котором лестница работает целиком, провайдеры запускаются
локальными процессами, а снаружи — CLI с тем же JSON, что отдаёт API. Эта веха —
только образ и CLI в этом репо. Встраивание в check-sites — следующая веха M20.

## Что проверено вживую, а что предположение

- Образ `abg-scrapling:m8` уже содержит ровно наши пины всех трёх провайдеров
  лестницы: `curl_cffi 0.16.3`, `patchright 1.62.3`, `playwright 1.62.0`,
  `scrapling 0.4.15` (`pip list` в образе). Метаданные PyPI `scrapling 0.4.15`:
  `curl_cffi>=0.16.1`, `patchright>=1.62.1`, `playwright>=1.62.0` в экстре
  `fetchers` — конфликта нет.
- В этом образе с актуальным `probe.py` при `ABG_PROVIDER=curl_cffi|patchright|
  scrapling` на `https://www.bizprofile.net/` получено: `curl_cffi` 403
  «Just a moment...», `patchright` 403, `scrapling` 200 с настоящим title —
  так же, как боевой шлюз.
- Прототип координатора (локальный launcher + `run_product` +
  `ProductFetcher`) внутри этого образа прогнал лестницу по loopback-странице
  с челленджем БЕЗ сети: `curl_cffi → patchright → scrapling`, у всех
  `http_403`, итог `ok=false`, `http_403`, шаг `human`. То же от root
  (`--user 0:0`) и с дефолтным `/dev/shm` 64 МБ (без `--shm-size`) — так будет
  в поде Kubernetes.
- Чекер `docs/specs/checks/m19_oneshot_image.py` (пишет и владеет координатор)
  прогнан на прототипе CLI координатора — `ok`; с убранной обёрткой `xvfb-run`
  у браузерных провайдеров — падает на первом шаге (`provider_error`,
  `investigate`).
- Лестница останавливается после первого провайдера на `provider_error` и
  `dns_error` (посчитано `run_product` с подменённым fetcher) — поэтому чекер
  гонит лестницу по локальной странице-челленджу, а не по недоступному хосту.
- Отсутствующий `expected_text` на странице 200 даёт `content_missing` (не
  `content_mismatch`) — посчитано прогоном.
- Точка подмены в коде: `gateway.fetch.ProductFetcher(url, launcher=...)`
  передаёт launcher в `bench.runner.fetch.fetch_content`, тот зовёт
  `launcher.run(argv, timeout_seconds, env=...)` → `(rc, stdout, stderr)` и
  ловит `subprocess.TimeoutExpired`. argv строит `build_argv`: `docker run …
  <provider.image> <url> --content-only [--include-content] --budget-ms N
  --mode cold`. JSON ответа API собирается в `gateway/api_http.py` (ключи
  `ok url final_url provider age_hours error_type step elapsed_ms` + `format`,
  `content` через `render_content`, `attempts` через `asdict`).
- Предположение: kubernetes-раннер check-sites запускает контейнер от root без
  особых прав. Поэтому образ не задаёт `USER` и обязан работать и от root, и от
  1002:1002.

## Задача

1. **`gateway/oneshot.py`** — CLI:
   `python3 -m gateway.oneshot URL [--format text|html|markdown|links|meta]
   [--expected-text TEXT] [--budget-ms N] [--no-browser]`.
   - Запрос: `ProductRequest(url, budget_ms (по умолчанию 30000),
     allow_browser (False при --no-browser), expected_text)`, `max_age_hours=0`,
     `egress_profiles=()` — только direct, без входов, прокси, токенов и кэша.
     Проверка аргументов — `plan_product` до запуска, как в API.
   - stdout: ровно одна строка JSON, ключи ровно как у ответа API (см.
     «Проверено»), та же сборка значения, что в `api_http.py` (вынести общее в
     функцию разрешено только внутри `gateway/oneshot.py`; `api_http.py` не
     править).
   - Код возврата: 0 — `ok=true`; 1 — `ok=false`; 2 — неверные аргументы
     (stdout пуст, в stderr одна строка `{"error": "invalid_request"}`);
     3 — внутренняя ошибка (stdout пуст, stderr `{"error": "internal_error"}`,
     без трейсбека).
2. **`LocalLauncher`** в `gateway/oneshot.py` — тот же контракт `run(argv,
   timeout, *, env=None)`: находит в argv образ провайдера из
   `bench.providers.registry.PROVIDERS`, всё после него — аргументы probe;
   запускает `python3 /opt/abg/probe.py <аргументы>` с `ABG_PROVIDER=<имя>`
   (переменные окружения из `env` сохраняются); для провайдеров `kind ==
   'browser'` — через `xvfb-run -a -s "-screen 0 1920x1080x24"`. Процесс в
   своей группе (`start_new_session=True`), на таймауте группа убивается целиком
   (браузер плодит детей) и `TimeoutExpired` пробрасывается. Неизвестный образ —
   `ValueError`.
3. **`deploy/Dockerfile.oneshot`**:
   `FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56`
   — bookworm, а не свежий Debian 13, осознанно: вся лестница измерена на
   образах `python:3.14-slim-bookworm`, одиночный образ обязан вести себя так
   же. `apt`: `xvfb xauth tini`; `pip`: `curl_cffi==0.16.3 patchright==1.62.3
   playwright==1.62.0 "scrapling[fetchers]==0.4.15"`; `patchright install
   --with-deps chrome`; `HOME=/opt/home` с правами на запись для любого uid;
   код `bench/` и `gateway/` — в `/opt/abg-src`, `bench/providers/docker/probe.py`
   — в `/opt/abg/probe.py`; `PYTHONPATH=/opt/abg-src`,
   `PYTHONDONTWRITEBYTECODE=1`; `ENTRYPOINT ["/usr/bin/tini","-g","--",
   "python3","-m","gateway.oneshot"]`; `USER` не задавать. Сборка из корня
   репо: `docker build -f deploy/Dockerfile.oneshot -t abg-oneshot:m19 .`.
4. **Тесты `tests/test_oneshot.py`** (офлайн, без Docker и браузеров; процесс
   probe подменяется), ровно с такими именами в классе `OneshotTests`:
   `test_exit_codes_and_output_contract`,
   `test_invalid_arguments_rc2_without_stdout`,
   `test_launcher_maps_image_to_provider_and_xvfb`,
   `test_launcher_timeout_kills_process_group`,
   `test_direct_only_request`.
5. **Мутанты** в `tests/mutation_gate_gateway.py` — три новых, каждый
   убивается своим тестом из пункта 4: (а) код возврата при `ok=false` — 0;
   (б) браузерный провайдер запускается без `xvfb-run`; (в) на таймауте
   убивается только лидер группы, а не группа. Итого 25.
6. **README**: раздел «One-shot image» — сборка, запуск
   (`docker run --rm abg-oneshot:m19 https://… --format meta`), коды возврата,
   что внутри только direct.
7. Закоммитить эту спеку `docs/specs/m19-oneshot-image.md` и чекер
   `docs/specs/checks/m19_oneshot_image.py` byte-identical первым коммитом.

## Разрешения

Создать `gateway/oneshot.py`, `tests/test_oneshot.py`,
`deploy/Dockerfile.oneshot`; править `tests/mutation_gate_gateway.py`,
`README.md`. Сборка образа `docker build` (сеть для apt/pip разрешена ТОЛЬКО
на сборку) и прогоны образом из критериев. Commit в клоне.

## Не трогать

Чекеры `docs/specs/checks/*.py` — только закоммитить новый, не править.
`bench/**` (включая `probe.py`, `registry.py`, `execute.py`), все прочие
модули `gateway/**` (включая `api_http.py`, `fetch.py`, `product.py`),
`deploy/Dockerfile`, `deploy/compose.yaml`, `scripts/**`, другие тесты и
specs, TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`,
чужие образы и registry (ничего не push'ить). Сторонних Python-зависимостей в
`pyproject.toml` не добавлять: `dependencies = []` — провайдеры живут только в
образе. Боевой сервис не трогать. Push и merge запрещены.

## Критерии приёмки

- **AC-250.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-251.** Тесты one-shot зелёные, пять именованных тестов существуют:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_oneshot tests.test_oneshot.OneshotTests.test_exit_codes_and_output_contract tests.test_oneshot.OneshotTests.test_invalid_arguments_rc2_without_stdout tests.test_oneshot.OneshotTests.test_launcher_maps_image_to_provider_and_xvfb tests.test_oneshot.OneshotTests.test_launcher_timeout_kills_process_group tests.test_oneshot.OneshotTests.test_direct_only_request'`
- **AC-252.** Образ собирается, база запинена по дайджесту, USER не задан:
  `bash -c 'grep -qx "FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56" deploy/Dockerfile.oneshot && ! grep -qi "^USER" deploy/Dockerfile.oneshot && docker build -q -f deploy/Dockerfile.oneshot -t abg-oneshot:m19 . >/dev/null'`
- **AC-253.** Чекер координатора внутри образа, без сети, от 1002 и от root; чекер не изменён:
  `bash -c 'echo "ba67a2a044f8acde01c3195643b932a514dc4a1af642622d9b21251c74526aec  docs/specs/checks/m19_oneshot_image.py" | sha256sum -c --quiet && for u in 1002:1002 0:0; do test "$(timeout 900 docker run --rm --network none --user $u --entrypoint python3 -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m19 /check.py)" = ok || exit 1; done'`
- **AC-254.** Точка входа образа — CLI: неверный вызов даёт код 2 и JSON-ошибку:
  `bash -c 'out=$(docker run --rm --network none abg-oneshot:m19 ftp://example.org/ 2>/tmp/abg-m19-err); rc=$?; test $rc -eq 2 && test -z "$out" && grep -qx "{\"error\": \"invalid_request\"}" /tmp/abg-m19-err'`
- **AC-255.** Мутационные ворота шлюза: 25 мутантов, все убиты. Считаются только строки отдельных мутантов; итоговая строка прогона в счёт не идёт:
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 25 && test -z "$(git status --porcelain -- tests gateway ":(exclude)report.json")"'`
- **AC-256.** Зависимостей в pyproject не прибавилось, вне разрешённых путей чисто, спека и чекер в истории:
  `bash -c 'grep -q "dependencies = \[\]" pyproject.toml && grep -q "One-shot image" README.md && git diff --exit-code fc5e9cff194132827c354c808712c0914408e52f HEAD -- . ":(exclude)gateway/oneshot.py" ":(exclude)tests/test_oneshot.py" ":(exclude)deploy/Dockerfile.oneshot" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)README.md" ":(exclude)docs/specs/m19-oneshot-image.md" ":(exclude)docs/specs/checks/m19_oneshot_image.py" && git ls-files --error-unmatch docs/specs/m19-oneshot-image.md docs/specs/checks/m19_oneshot_image.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m19-20260919 --base fc5e9cff194132827c354c808712c0914408e52f --range fc5e9cff194132827c354c808712c0914408e52f..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. У Grok 19.09.2026 кончился баланс (HTTP 402):
при quota error повторов не делать, записать в note и продолжать. Если
`accept_run.py` вернёт `blocked` только из-за отсутствия второго ревью — это
известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 7 записей AC-250…AC-256,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"fc5e9cff194132827c354c808712c0914408e52f","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-250","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m19-20260919 --spec /home/user/exec-clones/abg-m19-20260919/docs/specs/m19-oneshot-image.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер координатора требует поведения, противоречащего этой спеке; провайдер в
образе не стартует от root или без `--shm-size`; пины не ставятся вместе;
мутант не убивается своим тестом; требуется правка вне разрешённых файлов.
Спеку, чекер, AC, BASE и оснастку приёмки не менять, rc не выдумывать, чужое
не трогать, ничего не публиковать в registry.
