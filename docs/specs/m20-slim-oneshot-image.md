# M20 — облегчённый one-shot образ для проверок раз в 10 минут

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `4d84fdbe3527df973deda8d065ca75a87a1abddf` — вершина ветки
`m19-fix1` (образ M19 с исправлениями fix1, в main не влит).
Клон /home/user/exec-clones/abg-m20-slim-20260919, ветка m20-slim-image,
origin push DISABLED. Исполнитель — cx.

## Зачем

Образ `deploy/Dockerfile.oneshot` пойдёт в check-sites: CI-джоба в Kubernetes
раз в 10 минут перепроверяет им URL за Cloudflare-челленджем. Для этого образ
будет публичным в GHCR. Сейчас он весит 2 129 095 139 байт (сжатый 579 МБ), и
часть веса — мусор от `patchright install --with-deps chrome`:

- два одинаковых бинаря node по 124 МБ (`playwright/driver/node` и
  `patchright/driver/node`, sha256 совпадают);
- пакеты, притащенные рекомендациями и никому не нужные в рантайме:
  `cpp-12` (34 МБ), perl (46 МБ), системный python 3.11,
  `mesa-vulkan-drivers` (36 МБ);
- pip, `/usr/share/doc`, `/usr/share/man`, кэши apt.

Время проверки на это не влияет: на живом `https://www.bizprofile.net/`
лестница тратит 0,3 с на curl_cffi, 1,4 с на patchright и ~17 с на scrapling,
всего ~23 с. Выигрыш — в скачивании на новый или вычищенный узел кластера.

Заодно образ получает OCI-метки, по которым GHCR свяжет пакет с репозиторием
и покажет описание и лицензию (владелец выбрал MIT).

## Что проверено вживую, а что предположение

Координатор собрал прототип из дерева BASE, вставив в тот же `RUN`, сразу
после `patchright install --with-deps chrome`, ровно этот фрагмент:

```
 && apt-get purge -y mesa-vulkan-drivers \
 && apt-get -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false autoremove --purge -y \
 && SP=/usr/local/lib/python3.14/site-packages \
 && cmp $SP/playwright/driver/node $SP/patchright/driver/node \
 && ln -f $SP/patchright/driver/node $SP/playwright/driver/node \
 && pip uninstall -y pip \
 && rm -rf /usr/share/doc /usr/share/man /var/cache/apt /var/log/apt /var/log/dpkg.log \
```

Результат: 1 710 926 364 байта (сжатый 477 МБ); `cpp-12`, `perl`,
`python3.11`, `libpython3.11-stdlib` удалены; `libllvm15` и
`libgl1-mesa-dri` остались (от них зависит `xvfb` — их удаление снесло бы
xvfb, это проверено `apt-get -s purge`); оба node — один inode, 2 ссылки;
`import pip` падает. Чекеры `m19_oneshot_image.py` и `m19_fix1_process.py`
внутри прототипа печатают `ok` от root и от 1002. Живой
`https://www.bizprofile.net/` от 1002: три прогона из трёх `ok=true`,
`scrapling`, 22–23 с, заголовок страницы получен. Предположение одно:
apt-зеркало при сборке может отдать чуть другие версии, отсюда запас в
пороге размера (1 800 000 000 байт).

## Задача

1. `deploy/Dockerfile.oneshot`: вставить фрагмент выше в тот же `RUN` сразу
   после `patchright install --with-deps chrome \`. Остальные строки `RUN`
   (`chmod -R a+rwX /opt/home`, чистка `/var/lib/apt/lists`) сохранить.
   Базовый образ, версии pip-пакетов, `ENTRYPOINT`, раскладку `/opt/abg-src`
   и `/opt/abg` не менять.
2. Там же — OCI-метки одной инструкцией `LABEL`:
   - `org.opencontainers.image.source="https://github.com/stufently/ai-browser-gateway"`
   - `org.opencontainers.image.title="ai-browser-gateway one-shot"`
   - `org.opencontainers.image.description="Fetch one web page through the curl_cffi → patchright → scrapling ladder and print API-identical JSON"`
   - `org.opencontainers.image.licenses="MIT"`
3. Закоммитить эту спеку `docs/specs/m20-slim-oneshot-image.md`
   byte-identical первым коммитом.

## Разрешения

Правка `deploy/Dockerfile.oneshot`. Сборка образа (сеть только на сборку) и
прогоны образом из критериев. Commit в клоне.

## Не трогать

Всё, кроме `deploy/Dockerfile.oneshot` и этой спеки: `gateway/**`,
`bench/**`, `tests/**`, чекеры `docs/specs/checks/*.py`, `deploy/Dockerfile`,
`deploy/compose.yaml`, `scripts/**`, README.md, TASKS.md, CHANGELOG.md,
`secrets/**`, `/home/user/services/**`, registry (ничего не push'ить).
Push и merge запрещены.

## Критерии приёмки

- **AC-280.** Образ собирается из текущего дерева и весит не больше 1 800 000 000 байт:
  `bash -c 'docker build -q -f deploy/Dockerfile.oneshot -t abg-oneshot:m20 . >/dev/null && s=$(docker image inspect -f "{{.Size}}" abg-oneshot:m20) && echo "$s" && test "$s" -le 1800000000'`
- **AC-281.** Оба чекера M19 внутри образа от 1002 и от root, чекеры не изменены:
  `bash -c 'printf "%s\n" "72ae5dfb854470b159bc9511d3e83ea819f820d09b41f3836dc3ef75d6f0dddb  docs/specs/checks/m19_fix1_process.py" "ba67a2a044f8acde01c3195643b932a514dc4a1af642622d9b21251c74526aec  docs/specs/checks/m19_oneshot_image.py" | sha256sum -c --quiet && for u in 1002:1002 0:0; do test "$(timeout 900 docker run --rm --network none --user $u --entrypoint /usr/bin/tini -v "$PWD/docs/specs/checks/m19_fix1_process.py:/check.py:ro" abg-oneshot:m20 -s -- python3 /check.py)" = ok || exit 1; test "$(timeout 900 docker run --rm --network none --user $u --entrypoint python3 -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m20 /check.py)" = ok || exit 1; done'`
- **AC-282.** Лишнее удалено, нужное на месте, node один на двоих:
  `bash -c 'docker run --rm --network none --entrypoint sh abg-oneshot:m20 -c "for p in cpp-12 perl python3.11 mesa-vulkan-drivers; do ! dpkg -s \$p >/dev/null 2>&1 || exit 1; done; for p in google-chrome-stable xvfb xauth tini libgl1-mesa-dri; do dpkg -s \$p >/dev/null 2>&1 || exit 1; done; S=/usr/local/lib/python3.14/site-packages; test \$(stat -c %i \$S/playwright/driver/node) = \$(stat -c %i \$S/patchright/driver/node) && ! python3 -c \"import pip\" 2>/dev/null && test ! -e /usr/share/doc && python3 -c \"import curl_cffi, patchright, playwright, scrapling\""'`
- **AC-283.** OCI-метки на месте:
  `bash -c 'docker image inspect -f "{{json .Config.Labels}}" abg-oneshot:m20 > /tmp/abg-m20-labels.json && python3 -c "import json; l=json.load(open(\"/tmp/abg-m20-labels.json\")); assert l[\"org.opencontainers.image.source\"]==\"https://github.com/stufently/ai-browser-gateway\"; assert l[\"org.opencontainers.image.licenses\"]==\"MIT\"; assert l[\"org.opencontainers.image.title\"]==\"ai-browser-gateway one-shot\"; assert l[\"org.opencontainers.image.description\"].startswith(\"Fetch one web page\")"'`
- **AC-284.** Unit и frozen probes без регрессий, вне разрешённых путей чисто, спека в истории:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && git diff --exit-code 4d84fdbe3527df973deda8d065ca75a87a1abddf HEAD -- . ":(exclude)deploy/Dockerfile.oneshot" ":(exclude)docs/specs/m20-slim-oneshot-image.md" && git ls-files --error-unmatch docs/specs/m20-slim-oneshot-image.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m20-slim-20260919 --base 4d84fdbe3527df973deda8d065ca75a87a1abddf --range 4d84fdbe3527df973deda8d065ca75a87a1abddf..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 и кодом 3 — при таких ошибках повторов не делать, записать в note
и продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-280…AC-284,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"4d84fdbe3527df973deda8d065ca75a87a1abddf","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-280","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m20-slim-20260919 --spec /home/user/exec-clones/abg-m20-slim-20260919/docs/specs/m20-slim-oneshot-image.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
образ не укладывается в порог размера или чекер падает на облегчённом образе;
требуется правка вне разрешённых файлов; фрагмент из спеки не собирается.
Спеку, чекеры, AC, BASE и оснастку приёмки не менять, пакеты сверх списка не
удалять, rc не выдумывать, чужое не трогать, ничего не публиковать в registry.
