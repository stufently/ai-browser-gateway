# M21-fix1 — команды публичного README работают у постороннего

## Шапка и где работать

Репозиторий ~/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `de1f0bdbff0695c572b7c0451647ec71474e556c` — вершина ветки `m21-seo`
(результат M21, в main не влит).
Клон ~/exec-clones/abg-m21-fix1-20260919, ветка m21-fix1,
origin push DISABLED. Исполнитель — cx.

## Зачем

M21 принята по критериям (координатор перезапустил все пять, pass), но
README пишется для человека, у которого нет нашей машины. Разбор координатора
и ревью Codex нашли пять мест, где он споткнётся:

1. Раздел `## Development`: обе команды тестов запускают образ по голому
   `sha256:cad9a2c8…` — это ID локального образа, Docker у постороннего его не
   скачает, обе команды падают до запуска тестов.
2. `## Quick start`: абзац «The GHCR image is scheduled for publication after
   this documentation milestone. Until it is available, …» устарел — образ
   `ghcr.io/stufently/ai-browser-gateway-oneshot` опубликован (теги `0.1.0`,
   `latest`).
3. `## Quick start`: пример для Cloudflare бьёт в реальный сторонний сайт
   (`https://www.bizprofile.net/`). Публичный README не должен приглашать
   читателей долбить конкретный чужой сайт — нужен плейсхолдер.
4–5. `docs/README.ru.md` переехал из корня, а три markdown-ссылки остались
   с префиксом `docs/` и ведут в несуществующий `docs/docs/…`
   (`docs/specs/m10-product-contract.md`, `docs/research/04-phase1-verdict.md`,
   `docs/research/07-deployed-service.md`).

## Что проверено вживую, а что предположение

- Весь набор тестов проходит на публичном образе
  `python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56` (тот же базовый, что у
  `deploy/Dockerfile.oneshot`): `unittest discover` — 658 тестов OK, frozen
  probes — 125 OK, те же флаги, что у первого критерия M21.
- Образ опубликован координатором и проверен до публикации: оба чекера M19 от
  root и 1002 — `ok`, живой Cloudflare-сайт — `ok`, `scrapling`, 23 с.
- Координатор применил на копии BASE ровно правки пунктов «Задача» ниже —
  чекер `docs/specs/checks/m21_fix1_readme.py` печатает `ok`, чекер M21
  `m21_readme.py` тоже `ok`; на BASE новый чекер падает на пункте 1.

Предположений нет.

## Задача

1. `README.md`, `## Development`: в обеих командах тестов заменить
   `sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6` на
   `python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56`;
   текст раздела поправить соответственно (не «pinned image used for
   acceptance», а официальный образ Python с пином по дайджесту).
2. `README.md`, `## Quick start`: убрать абзац о том, что образ ещё не
   опубликован; сборку из исходников оставить как альтернативу («Or build and
   run from the repository root:» или близко). Пример для Cloudflare — на
   `https://cloudflare-protected.example/`, с `--budget-ms 90000`.
3. `docs/README.ru.md`: в трёх markdown-ссылках `](docs/…)` убрать префикс
   `docs/`. Больше в этом файле ничего не менять.
4. Закоммитить эту спеку `docs/specs/m21-fix1-readme-commands.md` и чекер
   `docs/specs/checks/m21_fix1_readme.py` byte-identical первым коммитом.

## Разрешения

Правка `README.md` и `docs/README.ru.md`. Прогоны из критериев (сеть для
скачивания образа Python разрешена). Commit в клоне.

## Не трогать

Всё, кроме `README.md`, `docs/README.ru.md`, этой спеки и её чекера (чекеры —
только закоммитить, не править): код, тесты, `deploy/**`, `scripts/**`,
`LICENSE`, `SECURITY.md`, `pyproject.toml`, другие specs и чекеры,
TASKS.md, CHANGELOG.md, `secrets/**`. Никаких внутренних адресов и путей
`/home/…`. Push, merge и публикация запрещены.

## Критерии приёмки

- **AC-296.** Тесты из README идут на публичном образе Python:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-297.** Оба чекера README печатают ok и не изменены:
  `bash -c 'printf "%s\n" "4993c4b5f39139c1da76952108644c7ae8fafef00ae90139a08310a9df1f9e70  docs/specs/checks/m21_readme.py" "2c3c5eee120e7b7f6432c417234c3a4fc1744fb75caad678a16aca37e9e026b5  docs/specs/checks/m21_fix1_readme.py" | sha256sum -c --quiet && for c in m21_readme m21_fix1_readme; do test "$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e PYTHONDONTWRITEBYTECODE=1 python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 python3 docs/specs/checks/$c.py)" = ok || exit 1; done'`
- **AC-298.** Русский README изменён только в трёх ссылках, вне разрешённых путей чисто, спека и чекер в истории:
  `bash -c 'test "$(git diff de1f0bdbff0695c572b7c0451647ec71474e556c HEAD -- docs/README.ru.md | grep -c "^-[^-]")" -eq 3 && test "$(git diff de1f0bdbff0695c572b7c0451647ec71474e556c HEAD -- docs/README.ru.md | grep -c "^+[^+]")" -eq 3 && git diff --exit-code de1f0bdbff0695c572b7c0451647ec71474e556c HEAD -- . ":(exclude)README.md" ":(exclude)docs/README.ru.md" ":(exclude)docs/specs/m21-fix1-readme-commands.md" ":(exclude)docs/specs/checks/m21_fix1_readme.py" && git ls-files --error-unmatch docs/specs/m21-fix1-readme-commands.md docs/specs/checks/m21_fix1_readme.py >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash ~/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone ~/exec-clones/abg-m21-fix1-20260919 --base de1f0bdbff0695c572b7c0451647ec71474e556c --range de1f0bdbff0695c572b7c0451647ec71474e556c..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 и кодом 3 — при таких ошибках повторов не делать, записать в note
и продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 3 записи AC-296…AC-298,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"de1f0bdbff0695c572b7c0451647ec71474e556c","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-296","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 ~/.claude/skills/executor-milestone/scripts/accept_run.py ~/exec-clones/abg-m21-fix1-20260919 --spec ~/exec-clones/abg-m21-fix1-20260919/docs/specs/m21-fix1-readme-commands.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
чекер требует поведения, противоречащего этой спеке; тесты не проходят на
публичном образе; требуется правка вне разрешённых файлов. Спеку, чекеры, AC,
BASE и оснастку приёмки не менять, rc не выдумывать, ничего не публиковать.
