# M20-fix1 — публичный образ сохраняет тексты лицензий пакетов

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `a097941ca64ed93f612d0ca01271bbb9f8f48414` — вершина ветки
`m20-slim-image` (результат M20, в main не влит).
Клон /home/user/exec-clones/abg-m20-fix1-20260919, ветка m20-fix1,
origin push DISABLED. Исполнитель — cx.

## Зачем

M20 принята: координатор перезапустил её критерии сам, все pass; живой
`https://www.bizprofile.net/` на облегчённом образе — `ok`, `scrapling`,
23 с. Ревью Codex нашло дефект, координатор проверил его:

Образ будет публичным в GHCR, то есть мы РАСПРОСТРАНЯЕМ входящие в него
Debian-пакеты. Их лицензии (GPL, LGPL, BSD, IPA Font License и др.) требуют
прикладывать текст лицензии, а Debian кладёт его в
`/usr/share/doc/<пакет>/copyright`. M20 удаляет `/usr/share/doc` целиком —
вместе с этими файлами. Пример: шрифты `fonts-ipafont-gothic` в образе
остаются, а их лицензия, которую IPA Font License (п. 3.2(3)) требует
прикладывать, исчезает. Экономия от удаления — всего 6,6 МБ.

## Что проверено вживую, а что предположение

Координатор собрал прототип из дерева BASE, убрав из строки
`rm -rf /usr/share/doc /usr/share/man /var/cache/apt /var/log/apt /var/log/dpkg.log`
только `/usr/share/doc `: размер 1 713 448 966 байт; у каждого
установленного пакета, кроме `google-chrome-stable`, есть
`/usr/share/doc/<пакет>/copyright` (у пакета Chrome такого файла нет и в
исходном образе — он поставляется по условиям Google, это решение владельца,
в веху не входит); `/usr/share/doc/fonts-ipafont-gothic/copyright` на месте.
Предположений о коде нет.

## Задача

1. `deploy/Dockerfile.oneshot`: в строке очистки `rm -rf …` убрать
   `/usr/share/doc`, остальные пути (`/usr/share/man /var/cache/apt
   /var/log/apt /var/log/dpkg.log`) оставить. Больше в Dockerfile ничего не
   менять.
2. Закоммитить эту спеку `docs/specs/m20-fix1-keep-licenses.md`
   byte-identical первым коммитом.

## Разрешения

Правка `deploy/Dockerfile.oneshot`. Сборка образа (сеть только на сборку) и
прогоны образом из критериев. Commit в клоне.

## Не трогать

Всё, кроме `deploy/Dockerfile.oneshot` и этой спеки: `gateway/**`,
`bench/**`, `tests/**`, чекеры `docs/specs/checks/*.py`, другие specs,
`deploy/Dockerfile`, `deploy/compose.yaml`, `scripts/**`, README.md,
TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`, registry
(ничего не push'ить). Push и merge запрещены.

## Критерии приёмки

- **AC-285.** Образ собирается и весит не больше 1 800 000 000 байт:
  `bash -c 'docker build -q -f deploy/Dockerfile.oneshot -t abg-oneshot:m20fix1 . >/dev/null && s=$(docker image inspect -f "{{.Size}}" abg-oneshot:m20fix1) && echo "$s" && test "$s" -le 1800000000'`
- **AC-286.** Тексты лицензий на месте у всех пакетов, кроме Chrome; облегчение M20 сохранено:
  `bash -c 'docker run --rm --network none --entrypoint sh abg-oneshot:m20fix1 -c "for p in \$(dpkg-query -Wf \"\\\${Package}\\n\"); do test \$p = google-chrome-stable || test -e /usr/share/doc/\$p/copyright || exit 1; done; test -s /usr/share/doc/fonts-ipafont-gothic/copyright; for p in cpp-12 perl python3.11 mesa-vulkan-drivers; do ! dpkg -s \$p >/dev/null 2>&1 || exit 1; done; S=/usr/local/lib/python3.14/site-packages; test \$(stat -c %i \$S/playwright/driver/node) = \$(stat -c %i \$S/patchright/driver/node) && ! python3 -c \"import pip\" 2>/dev/null && test ! -e /usr/share/man"'`
- **AC-287.** Оба чекера M19 внутри образа от 1002 и от root, чекеры не изменены:
  `bash -c 'printf "%s\n" "72ae5dfb854470b159bc9511d3e83ea819f820d09b41f3836dc3ef75d6f0dddb  docs/specs/checks/m19_fix1_process.py" "ba67a2a044f8acde01c3195643b932a514dc4a1af642622d9b21251c74526aec  docs/specs/checks/m19_oneshot_image.py" | sha256sum -c --quiet && for u in 1002:1002 0:0; do test "$(timeout 900 docker run --rm --network none --user $u --entrypoint /usr/bin/tini -v "$PWD/docs/specs/checks/m19_fix1_process.py:/check.py:ro" abg-oneshot:m20fix1 -s -- python3 /check.py)" = ok || exit 1; test "$(timeout 900 docker run --rm --network none --user $u --entrypoint python3 -v "$PWD/docs/specs/checks/m19_oneshot_image.py:/check.py:ro" abg-oneshot:m20fix1 /check.py)" = ok || exit 1; done'`
- **AC-288.** Вне разрешённых путей чисто, спека в истории:
  `bash -c 'git diff --exit-code a097941ca64ed93f612d0ca01271bbb9f8f48414 HEAD -- . ":(exclude)deploy/Dockerfile.oneshot" ":(exclude)docs/specs/m20-fix1-keep-licenses.md" && test "$(git diff a097941ca64ed93f612d0ca01271bbb9f8f48414 HEAD -- deploy/Dockerfile.oneshot | grep -c "^[-+][^-+]")" -eq 2 && git ls-files --error-unmatch docs/specs/m20-fix1-keep-licenses.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m20-fix1-20260919 --base a097941ca64ed93f612d0ca01271bbb9f8f48414 --range a097941ca64ed93f612d0ca01271bbb9f8f48414..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Grok 19.09.2026 без баланса (HTTP 402), agy
отвечал 429 и кодом 3 — при таких ошибках повторов не делать, записать в note
и продолжать. Если `accept_run.py` вернёт `blocked` только из-за отсутствия
ревью — это известное ограничение оснастки, координатор принимает вручную:
`report-blocked.md` не нужен, достаточно note в report.json.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 4 записи AC-285…AC-288,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"a097941ca64ed93f612d0ca01271bbb9f8f48414","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-285","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m20-fix1-20260919 --spec /home/user/exec-clones/abg-m20-fix1-20260919/docs/specs/m20-fix1-keep-licenses.md --timeout 5400`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
какой-то пакет, кроме Chrome, остаётся без copyright-файла; образ не
укладывается в порог; чекер падает; требуется правка вне разрешённых файлов.
Спеку, чекеры, AC, BASE и оснастку приёмки не менять, rc не выдумывать,
чужое не трогать, ничего не публиковать в registry.
