# M9 — вернуть полноту живого сценария

## Где работать

BASE_SHA 724d75894fe3efe25a0ef9196d4c5f694d1c261b.
Клон /home/user/exec-clones/abg-m9-real-fetcher-20260914, ветка m9-real-fetcher.
Тот же исполнитель Grok, явное продолжение приёмки M9 без новой монетки.
Не pull/push/merge/deploy. Spark/auto запрещены; последний показанный Grok
weekly6%, 5h/reset неизвестны. Координатор код и тесты не пишет.

## Что проверено вживую, а что предположение

Пакет предыдущего исправления: m9/corrections/ в cache координатора.
Координатор прочитал весь diff08a5da9..724d758, оба verification ревью приняты.
Реализация Unicode framing и HTML-границ исправлена. Но в live-сценарии
при этом удалены две проверки исходной M9: динамический уникальный маркер
больше не проверяется в HTML patchright/scrapling и в HTML ok_outcome.
Остались prefix в text и sentinel в html; это не подтверждает доставку
полного HTML за пределами sentinel. Найдено чтением immutable git diff,
не гипотеза о текущих сетевых сайтах. Замечание относится к тесту, продуктовый
код этой задачей не меняется.

## Что сделать

В tests/live_m9_fetch.py восстановить проверки уникального prefix в HTML
каждого успешного результата цикла PROVIDER_BUDGETS и в ok_outcome.html.
Существующий prefix уникален для запуска; полного байтового совпадения DOM
браузера с source HTML не требовать. Все текущие text/Unicode/status/timeout/
label/cleanup проверки оставить. Получить зелёный live на curl, patchright,
scrapling и gateway. Ничего другого рефакторить не нужно.

Сохранить предыдущий report и пакеты вне клона, не стирать квитанции.
Прочитанный/принятый дифф предыдущих исправлений повторно ревьюить не надо.
Здесь новый review journal по указанному BASE; только узкий diff этих проверок
и этой спеки. Код M9 не считается слитым или принятым до решения координатора.

## Не трогать

Разрешено менять/коммитить только tests/live_m9_fetch.py и эту спеку.
Продуктовый код, остальные тесты, замороженный probe и предыдущие спеки,
TASKS/CHANGELOG/README/research, образы, конфиги, секреты, чужая оснастка
не менять. Без sudo, host установок, чтения .env и опытов с чужими процессами.
Тесты/продуктовый Python в Docker1002:1002; host Python только Docker orchestration.
Чистить только собственные контейнеры прогона.

## Критерии приёмки

- **AC-901.** Полный suite:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-902.** Замороженный probe:
  `bash -c 'echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m tests.probe_m9_transport'`
- **AC-903.** Полный живой сценарий:
  `bash -c 'python3 tests/live_m9_fetch.py'`
- **AC-904.** Исторические мутации:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py'`
- **AC-905.** Узкий diff поверх проверенного продукта:
  `bash -c 'git diff --exit-code 724d75894fe3efe25a0ef9196d4c5f694d1c261b HEAD -- . ":(exclude)tests/live_m9_fetch.py" ":(exclude)docs/specs/m9-live-html-assertions.md"'`
- **AC-906.** Спека/тест tracked, чистое дерево:
  `bash -c 'git ls-files --error-unmatch tests/live_m9_fetch.py docs/specs/m9-live-html-assertions.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

## Контракт отчёта

Спеку коммитить неизменной. report.json: schema_version=2,
policy_id=cross-review-v1, spec_sha256 этой спеки, base_sha/reviewed_sha/final_sha,
executor.backend=grok/model=grok-4.6, review.initial_receipts/
verification_receipts/resolutions, handoff_status, criteria:6AC с точными
командами выше, status/pass|fail|blocked, rc, note. Не писать pass без прогона.
Гейт запускает AC. Для неизменившегося кода AC-901/902/904 допускается
сослаться на фактический успешный прогон предыдущего гейта на BASE_SHA
(m9/corrections/logs/accept_run.out), явно назвать SHA и повтор финальным
гейтом. Не выдавать старый лог за новый. AC-903 после добавления проверок
выполнить вживую. Не надо до гейта повторять suite/105мутантов.

## Авторевью

Исполнитель сам параллельно запускает initial codex и agy через
/home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh, --base как выше,
--range BASE..REVIEW, read-only контекст на эти две проверки и связанные риски.
ASK_MAX_FINDINGS=12, AGY_MODEL=gemini-3.8-flash-high AGY_TIMEOUT=900.
При неизменном коде REVIEW=FINAL, verification_receipts=[]; не дублировать
успешные ревью. При находках один fix round и два verification. Incomplete:
один технический повтор, quota error не циклировать. Новые неразрешённые
находки после verification честно needs_owner.

Гейт:
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m9-real-fetcher-20260914 --spec /home/user/exec-clones/abg-m9-real-fetcher-20260914/docs/specs/m9-live-html-assertions.md --timeout 3600`.
Пакет /home/user/.cache/abg-coord-20260914/m9/live-html-final/: полный итоговый
diff72b7ce8..FINAL, diff этой задачи, отчёт/команды/cwd/rc/логи/SHA256SUMS.
Независимые мутации17шт авторства cx лежат m9/mutations-cx/; координатор
обеспечит их финальный повтор на FINAL_SHA, Grok приложит результаты к пакету.

## Контракт на невыполнимое

Не ослаблять критерии, не заменять реальный live фейками. При противоречии
или нехватке ресурса сохранить report-blocked.md с командой, cwd, rc и уликой.
