# M21 — публичный английский README, лицензия MIT и метаданные для поиска

## Шапка и где работать

Репозиторий ~/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `ff8ff669302ea7da0fc442cbd5d87d1108724951` — вершина main после
чистки истории (M19 и M20 влиты).
Клон ~/exec-clones/abg-m21-seo-20260919, ветка m21-seo,
origin push DISABLED. Исполнитель — cx.

## Зачем

Владелец 19.09.2026: «давай просто откроем репо на гитхабе а сам проект
максимально оптимизируем для seo». Репозиторий `stufently/ai-browser-gateway`
станет публичным, а one-shot образ будет лежать в GHCR как
`ghcr.io/stufently/ai-browser-gateway-oneshot`. Сейчас README русский и
написан для внутренней работы (статусы вех, журнал решений), лицензии нет,
`pyproject.toml` без описания и ссылок. Человек из поиска GitHub/Google по
запросам «headless browser for AI agents», «Cloudflare challenge scraping»,
«MCP server fetch web page» не поймёт, что это и как запустить.

## Что проверено вживую, а что предположение

Проверено координатором на BASE:

- CLI `python3 -m gateway.oneshot URL` принимает ровно `--format`
  (`text|html|markdown|links|meta`, по умолчанию `text`), `--expected-text`,
  `--budget-ms` (по умолчанию 30000) и `--no-browser`
  (`gateway/oneshot.py`, строки с `add_argument`). `--help` НЕ печатает
  справку: любая ошибка разбора — `{"error": "invalid_request"}` и код 2.
- Коды выхода: 0 `ok=true`, 1 `ok=false`, 2 неверные аргументы, 3 внутренняя
  ошибка, 4 прерван сигналом. Поля JSON: `ok url final_url provider age_hours
  error_type step elapsed_ms format content attempts`.
- Живой `https://www.bizprofile.net/` (Cloudflare managed challenge) образом:
  `ok=true`, провайдер `scrapling`, ~23 с (curl_cffi 0,3 с → 403,
  patchright 1,4 с → 403, scrapling ~17 с → 200). Для сайтов за Cloudflare
  дефолтных 30 000 мс впритык — в README рекомендовать `--budget-ms 90000`.
- Образ: 1,71 ГБ, внутри Google Chrome (по условиям Google), работает от root
  и от любого UID, дефолтный `/dev/shm` достаточен.
- Раздел `## MCP server` текущего README уже английский и точный — его смысл
  переносится без изменений фактов.
- Ключевые выводы замера фазы 1 (`docs/research/04-phase1-verdict.md`,
  `05-scrapling.md`): браузер окупается рендерингом, а не обходом блокировок;
  scrapling с `solve_cloudflare` взял цель, которую patchright не взял.
- Пакет из `pyproject.toml` нигде не собирается (Docker-образы копируют
  исходники), поэтому правка метаданных ничего не ломает.

Предположение: образ в GHCR появится после этой вехи; README ссылается на
него заранее.

## Задача

1. `git mv README.md docs/README.ru.md` — русский README переезжает
   **без изменений содержимого** (byte-identical с BASE), это внутренняя
   документация развёртывания.
2. Новый `README.md` на английском, без кириллицы, для человека из поиска.
   Разделы — ровно эти заголовки второго уровня, в этом порядке:
   - H1 `# AI Browser Gateway` и сразу под ним одна фраза-описание со словами
     «AI agents», «headless browser» и «Cloudflare»; строка бейджей: лицензия
     MIT (shields.io, ссылка на `LICENSE`) и образ GHCR (ссылка на
     `https://github.com/stufently/ai-browser-gateway/pkgs/container/ai-browser-gateway-oneshot`).
   - `## Why` — самый дешёвый достаточный способ: HTTP с браузерными
     заголовками сначала, браузер только когда нужен; вывод замера.
   - `## Quick start` — `docker run --rm ghcr.io/stufently/ai-browser-gateway-oneshot:latest https://example.com/ --format markdown`,
     пример для сайта за Cloudflare с `--budget-ms 90000`, и сборка локально:
     `docker build -f deploy/Dockerfile.oneshot -t ai-browser-gateway-oneshot .`
   - `## CLI reference` — все четыре флага с дефолтами, формат вывода (одна
     строка JSON, перечень полей), таблица кодов выхода 0–4, что stderr при
     кодах 2–4.
   - `## How the provider ladder works` — таблица провайдеров
     `curl_cffi`, `patchright`, `scrapling` (что делает, когда включается),
     `--no-browser`, прокси-переменные окружения игнорируются.
   - `## MCP server for AI agents` — перенос раздела `## MCP server` с тем же
     JSON-примером конфигурации и теми же фактами.
   - `## Self-hosted HTTP API` — коротко: `/v1/fetch`, `scripts/abg-fetch`,
     ссылка на `docs/README.ru.md` за деталями развёртывания.
   - `## Benchmarks` — два вывода замера со ссылками на `docs/research/`.
   - `## Responsible use` — для своих сайтов, мониторинга и чтения страниц
     агентами; уважать условия сайтов и robots.txt; сервисов разгадывания
     капчи нет.
   - `## Development` — команды тестов Docker'ом (как в AC-290).
   - `## License` — MIT, ссылка на `LICENSE`; Google Chrome в образе — по
     условиям Google.
3. `LICENSE` — стандартный текст MIT (SPDX `MIT`) с первой строкой
   `MIT License` и строкой `Copyright (c) 2026 stufently`.
4. `SECURITY.md` на английском: как сообщить об уязвимости (GitHub private
   vulnerability reporting репозитория), не прикладывать токены и прокси.
5. `pyproject.toml`, секция `[project]`: `description` на английском (до 120
   символов), `readme = "README.md"`, `license = "MIT"`,
   `license-files = ["LICENSE"]`, `keywords` (не меньше 8, включая
   `web-scraping`, `headless-browser`, `cloudflare`, `mcp`, `ai-agents`,
   `playwright`), `classifiers` (Python 3, OS Independent, Topic Internet
   WWW/HTTP), `[project.urls]` с `Homepage`, `Repository`, `Issues`.
   `[build-system] requires = ["setuptools>=77"]` (нужна для SPDX-строки
   лицензии). `dependencies = []`, `name`, `version`, `requires-python` — не
   менять.
6. Закоммитить эту спеку `docs/specs/m21-public-readme-seo.md` и чекер
   `docs/specs/checks/m21_readme.py` byte-identical первым коммитом.

## Разрешения

Создание `README.md`, `LICENSE`, `SECURITY.md`, `docs/README.ru.md` (только
через `git mv`); правка `pyproject.toml`. Чтение любых файлов репо. Прогоны
из критериев. Commit в клоне.

## Не трогать

Код и тесты (`gateway/**`, `bench/**`, `tests/**`, `scripts/**`),
`deploy/**`, `docs/**` кроме `docs/README.ru.md`, этой спеки и её чекера
(чекер — только закоммитить, не править), TASKS.md,
CHANGELOG.md, `secrets/**`, `~/services/**`. Никаких внутренних
адресов, имён хостов, IP, путей `/home/…` в новых файлах. Не добавлять
`.github/workflows/`. Push, merge и публикация образа запрещены.

## Критерии приёмки

- **AC-290.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-291.** Русский README перенесён без изменений, новый README английский, разделы на месте и по порядку:
  `bash -c 'git show ff8ff669302ea7da0fc442cbd5d87d1108724951:README.md | cmp - docs/README.ru.md && ! grep -P "[\x{0400}-\x{04FF}]" README.md && test "$(head -1 README.md)" = "# AI Browser Gateway" && test "$(grep "^## " README.md | tr "\n" "|")" = "## Why|## Quick start|## CLI reference|## How the provider ladder works|## MCP server for AI agents|## Self-hosted HTTP API|## Benchmarks|## Responsible use|## Development|## License|"'`
- **AC-292.** README согласован с кодом (флаги, режимы, поля, коды выхода, образ, MCP), ссылки живые, внутренних адресов нет; чекер не изменён:
  `bash -c 'echo "4993c4b5f39139c1da76952108644c7ae8fafef00ae90139a08310a9df1f9e70  docs/specs/checks/m21_readme.py" | sha256sum -c --quiet && test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 docs/specs/checks/m21_readme.py)" = ok'`
- **AC-293.** LICENSE — MIT, SECURITY.md на английском, метаданные pyproject:
  `bash -c 'test "$(head -1 LICENSE)" = "MIT License" && grep -qx "Copyright (c) 2026 stufently" LICENSE && grep -q "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND" LICENSE && test -s SECURITY.md && ! grep -P "[\x{0400}-\x{04FF}]" SECURITY.md && python3 -c "import tomllib; d=tomllib.load(open(\"pyproject.toml\",\"rb\")); p=d[\"project\"]; assert p[\"license\"]==\"MIT\" and p[\"license-files\"]==[\"LICENSE\"] and p[\"readme\"]==\"README.md\"; assert p[\"dependencies\"]==[] and p[\"name\"]==\"ai-browser-gateway\" and p[\"version\"]==\"0.1.0\" and p[\"requires-python\"]==\">=3.12\"; assert len(p[\"description\"])<=120 and p[\"description\"].isascii(); kw=set(p[\"keywords\"]); assert len(kw)>=8 and {\"web-scraping\",\"headless-browser\",\"cloudflare\",\"mcp\",\"ai-agents\",\"playwright\"}<=kw; assert {\"Homepage\",\"Repository\",\"Issues\"}<=set(p[\"urls\"]); assert d[\"build-system\"][\"requires\"]==[\"setuptools>=77\"]"'`
- **AC-294.** Вне разрешённых путей чисто, workflows нет, спека в истории:
  `bash -c 'git diff --exit-code ff8ff669302ea7da0fc442cbd5d87d1108724951 HEAD -- . ":(exclude)README.md" ":(exclude)LICENSE" ":(exclude)SECURITY.md" ":(exclude)pyproject.toml" ":(exclude)docs/README.ru.md" ":(exclude)docs/specs/m21-public-readme-seo.md" ":(exclude)docs/specs/checks/m21_readme.py" && test ! -e .github/workflows && git ls-files --error-unmatch docs/specs/m21-public-readme-seo.md docs/specs/checks/m21_readme.py docs/README.ru.md LICENSE SECURITY.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash ~/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone ~/exec-clones/abg-m21-seo-20260919 --base ff8ff669302ea7da0fc442cbd5d87d1108724951 --range ff8ff669302ea7da0fc442cbd5d87d1108724951..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 и кодом 3 — при таких ошибках повторов не делать, записать в note
и продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-290…AC-294,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"ff8ff669302ea7da0fc442cbd5d87d1108724951","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-290","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 ~/.claude/skills/executor-milestone/scripts/accept_run.py ~/exec-clones/abg-m21-seo-20260919 --spec ~/exec-clones/abg-m21-seo-20260919/docs/specs/m21-public-readme-seo.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
факт, который спека велит написать в README, расходится с кодом; критерий
требует невозможного; требуется правка вне разрешённых файлов. Спеку, AC,
BASE и оснастку приёмки не менять, факты не выдумывать (нет в коде или в
`docs/research/` — не писать), rc не выдумывать, ничего не публиковать.
