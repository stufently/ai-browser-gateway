# M10 — продуктовая лестница: execution-спека

ЧЕРНОВИК ДО SHA НЕЗАВИСИМОГО PROBE. Реализацию пока не запускать.

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 14.09.2026.
BASE_SHA `632b2df314230c68da579811679a18409938f7e9`
(Import accepted Grok two-egress measurement and product handoff).
Клон /home/user/exec-clones/abg-m10-product-20260914, ветка m10-product.
Исполнитель — явный cx по разрешению постановщика; Spark исчерпан до
20.09.2026 15:59, auto запрещён. Последний Grok weekly4%, 5h/reset неизвестны;
окна обычного cx неизвестны. Исправления остаются cx, новой монетки нет.
Независимый probe/эталоны/мутации — Grok, отдельный клон m10-probes.
Координатор пишет спецификацию и принимает, продукт/тесты/фиксы пишет cx.

Только назначенный клон, origin push отключён; push/merge/deploy запрещены.
Docker UID1002:1002 для всего продукта и тестов. Host Python только
оркестрация subprocess, без импорта продукта. Без sudo/host installs,
боевых .env/кредов, чужих деревьев/сервисов. Опыты с процессами/tmux —
только Docker с фейками, host tmux socket/чужие процессы не трогать.

## Задача и почему

Владелец требует используемый шлюз. M9 доставляет реальные страницы только
со строгим sentinel; M10 добавляет продуктовый URL-only вход с необязательным
expected_text клиента, конечную лестницу со Scrapling, trace и общийdeadline.
Полный обязательный контракт: `docs/specs/m10-product-contract.md`, SHA256
`01b9df3ffb99559883d3438b7fe8727c4ba0ccefd8e9591363a6bfb3d068ea84`.
Прочитать целиком, исполнять буквально вместе с этой спекой. API/CLI — M11;
сервис/пул/развёрнутый прогон — M12. Не расширять веху на них.

## Что проверено вживую, а что предположение

M9 принята на bab00353adbbfc9484a1b5ab6ea63705d5aa99e1, merge f3c3913.
Код BASE идентичен f3c3913 по bench/gateway/tests (git diff --exit-code rc0).
Разведка Grok `m10-recon-result.md` в /home/user/.cache/abg-coord-20260914/,
SHA0dca8623a2aaa13e3b2f8f7478d4540184738b3bb62842cd3b78987e429b48fc:
24 Docker-наблюдения, исходники RO. Старую host-улику не считать доказательством.
Существующие сигнатуры/тела/ограничения приведены в контракте; координатор
прочитал gateway models/engine/plan, bench.escalate/fetch, detector и run_probe.
Новые имена/API из контракта — задача, на BASE их нет.

Принятый замер `docs/research/06-two-egress.md` и data/m10-egress.jsonl:
36 уникальных клеток на direct192.0.2.10 и ms1 198.51.100.21, одинаковый
код/образы/budget120000, паузы>=30с, Docker1002:1002. На каждомIP покрытие
3/5/6 дляcurl/patchright/Scrapling. Код исследовательских helper и35хешей
проверены; повторять сеть не нужно. Переходы403→браузер и403→Scrapling
опираются на этот замер; гарантию стабильности одного запроса не обещать.
Без ожидания URL-only не подтверждает смысл страницы; challenge-метки
lowendtalk/bizprofile не считать скрытым успехом и не стирать из trace.

## Что сделать

Реализовать разделы «Публичные границы», «Транспорт», «Валидация», «Проверка
страницы», «План и переходы», «Обязательная живая проверка» контракта.
Новые gateway/product.py, tests/test_gateway_product.py,
tests/test_content_transport.py, tests/live_m10_product.py.
Расширения gateway/fetch.py, bench/runner/fetch.py, экспортfetch_content в
bench/runner/execute.py, совместимые content-only изменения registry.py/probe.py.
README: пример ProductRequest+ProductFetcher, expected_text и его ограничения,
trace/отказы, Docker; API/сервис ещё не объявлять готовыми.

Спека и контракт приехали untracked; оба коммитятся БЕЗ правок.
Независимый `tests/probe_m10_product.py` также коммитится БЕЗ правок:
SHA256 [PROBE_SHA], размер [PROBE_SIZE]. Пакет подготовки
/home/user/.cache/abg-coord-20260914/m10/probe/preparation-result.md.
Эталоны в продукт не переносить. Full review diff должен быть <100000байт;
если не помещается, остановиться до ревью, не обрезать вход.

## Не трогать

TASKS.md, CHANGELOG.md, существующие исследования/спеки/тесты/пробники,
gateway/engine.py, gateway/models.py, gateway/plan.py, bench/models.py,
bench/escalate.py, execute_plan, старые теги/образы/версии/UA/stealth,
конфиги/сервисы/профили/креды/cf-fetch. Разрешены только перечисленные новые
файлы, README и названные совместимые расширения. Новых зависимостей нет.
Нельзя менять смысл старого fetch_page/BenchFetcher, benchmark JSONL,
evaluate/next_step или ослаблять проверки ради зелёного гейта.

## Критерии приёмки

- **AC-101.** Полный unittest:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-102.** Неизменные контракт/независимые probes M9+M10:
  `bash -c 'echo "01b9df3ffb99559883d3438b7fe8727c4ba0ccefd8e9591363a6bfb3d068ea84  docs/specs/m10-product-contract.md" | sha256sum -c - && echo "[PROBE_SHA]  tests/probe_m10_product.py" | sha256sum -c - && echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product'`
- **AC-103.** Живой сквозной сценарий:
  `bash -c 'python3 tests/live_m10_product.py'`
- **AC-104.** Исторические мутации:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py'`
- **AC-105.** Старое ядро, исследования, статус и тесты неизменны:
  `bash -c 'git diff --exit-code 632b2df314230c68da579811679a18409938f7e9 HEAD -- gateway/engine.py gateway/models.py gateway/plan.py bench/models.py bench/escalate.py docs/research TASKS.md CHANGELOG.md tests ":(exclude)tests/test_gateway_product.py" ":(exclude)tests/test_content_transport.py" ":(exclude)tests/live_m10_product.py" ":(exclude)tests/probe_m10_product.py"'`
- **AC-106.** Состав коммита и чистота:
  `bash -c 'git ls-files --error-unmatch gateway/product.py tests/test_gateway_product.py tests/test_content_transport.py tests/live_m10_product.py tests/probe_m10_product.py docs/specs/m10-product.md docs/specs/m10-product-contract.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

На BASE старые suite/invariants зелёные, новый API/probe/live/состав красные
по отсутствию реализации, не по среде. Baseline-улики подготовки приложить;
старые результаты на идентичном коде маркировать как baseline, не новый pass.

## Авторевью

cross-review-v1. Перед ревью коммит REVIEW_SHA; полный diff BASE..REVIEW.
Автор cx сам запускает параллельно Grok+agy через АБСОЛЮТНЫЙ
/home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh, обаread-only,
раздельные контексты, один диапазон. ASK_MAX_FINDINGS=12,
AGY_MODEL=gemini-3.8-flash-high, AGY_TIMEOUT=900.
Дополнительно проект требует Codex result: отдельный read-only
`bash ~/.claude/skills/ask-codex/scripts/run.sh result '<тот же контекст>' --file REVIEW_DIR/full.diff`.
Сохранить raw/rc/SHA; не создавать дополнительную ручную квитанцию в журнале.
Пример машинного review:
`bash /home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m10-product-20260914 --base 632b2df314230c68da579811679a18409938f7e9 --range <BASE_SHA>..<REVIEW_SHA> --context '<контракт/риски; только чтение>'`.
Одинаковый --base обеих фаз, run_id=basename-clone+'-'+BASE[:12]. Квитанции
пишет толькоreview_run.sh. Обрезанный вход/ответ, потолок находок, отсутствие
финального ВЕРДИКТ: ПРИНЯТО либо НЕ ПРИНИМАТЬ — incomplete дажеrc0.
Один технический повтор незавершённого вызова; quotaerror безretry.
Дождаться всех ответов, единый список fixed/disproved с уликой либоneeds_owner.
Один заход фиксов, затем те же ревьюеры один раз REVIEW..FINAL. Неизменный
код повторно не ревьюить. Новый дефект/спор verification — needs_owner,
без второго автономного круга и без переноса дефекта в backlog.

## Контракт отчёта

report.json v2 в корне untracked; ровно6 критериев AC-101…AC-106,
команды посимвольно изспеки, blocked rc=null с безопасной уликой.
Обязательная форма:
```json
{"schema_version":2,"policy_id":"cross-review-v1",
 "spec_sha256":"<sha256 этой execution-спеки>",
 "base_sha":"632b2df314230c68da579811679a18409938f7e9",
 "reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<точная>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready",
 "criteria":[{"id":"AC-101","status":"pass|fail|blocked",
 "command":"<команда изспеки>","rc":0,"note":"<улика>"}]}
```
Автор сам запускает ПОЛНЫЙ гейт, не только dry-run:
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m10-product-20260914 --spec /home/user/exec-clones/abg-m10-product-20260914/docs/specs/m10-product.md --timeout 3600`.
Пакет /home/user/.cache/abg-coord-20260914/m10/: полныйdiff, BASE/REVIEW/FINAL,
команды/cwd/rc/логиDocker/live, receipts/raw/решения/SHA256SUMS.
Независимые мутации новых тестов — Grok по отдельному заданию на FINAL_SHA:
baselinegreen, активация, assertionkill (неruntimeerror), finallyrestore/SHA,
0survived/invalid. Авторcx их не подменяет. Grok собирает итоговыйпакет.
Координатор читает весьdiff, сверяет SHA/ревью/логи и запускает свой полный
accept_run.py один раз; повторённый тем же гейтом сьют отдельно не дублирует.
Зелёный гейт не разрешает push и не заменяет разбор известных дефектов.

## Контракт на невыполнимое

Противоречие/блокер: сохранить report-blocked.md с командой/cwd/rc и дословным
безопасным выводом, остановиться. Не менять контракт/AC/frozenprobe,
не выдумывать числа/квоты, не обходить среду/launcher. Исправления приёмки
возвращаются тому же cx отдельным заданием координатора.
