# M12b-fix2 — окно проверки ошибок доставки monitor

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `895bc83e9f5b4e2339a68783fe8adcad162b8b64` — FINAL M12b-fix.
Клон /home/user/exec-clones/abg-m12b-fix2-20260917, ветка m12b-fix2, origin
push DISABLED. Исполнитель — cx (директива владельца 17.09.2026: «доделывай
всё, используя кодекс»).

Сервис `ai-browser-gateway` (127.0.0.1:8765, release `929bded`) работает; его
НЕ перезапускать, НЕ останавливать, `/home/user/services/**` НЕ менять,
healthchecks не трогать. Push/merge запрещены. Исполнение кода — Docker
1002:1002, хостовые git/файлы/оркестрация — как уже делает runner.

## Задача

В M12b-fix проверка развёртывания упала на `monitor_delivery_errors`: `check_deploy` требует
пустые логи monitor за ВСЮ жизнь контейнера. Единственная строка лога —
`URLError` в 04:06:25Z: координатор намеренно остановил api, чтобы проверить
fail/recovery в healthchecks. Это дефект спеки: после любой настоящей
кратковременной аварии проверка развёртывания падала бы навсегда.

Изменить в `tests/deployed_m12b.py` только это правило:
- ошибки доставки monitor ищутся в логах за последние 150 секунд
  (`docker logs --since 150s <id>`), после уже существующего ожидания
  uptime monitor ≥130 с; непустой вывод в этом окне — `monitor_delivery_errors`;
- скан секретов (`worker_call('scan', …)`) по-прежнему получает ПОЛНЫЕ логи
  обоих контейнеров за всё время;
- в `deploy.json` вместо `monitor_logs_empty` записать
  `monitor_recent_logs_empty` и `monitor_log_window_seconds: 150`.

В `tests/test_deployed_m12b.py` — тесты с фейковым `subprocess.run`/`docker`,
падающие по причине: старая строка вне окна не валит проверку (полный лог при
этом уходит в scan), строка в окне даёт `monitor_delivery_errors`, скан
секретов получает полный лог, а не оконный. В
`docs/research/07-deployed-service.md` — одна фраза про окно 150 с.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: `docker logs -t ai-browser-gateway-monitor-1`
— одна строка `URLError` в 04:06:25Z, совпадает с остановкой api 04:05:54 и
fail-пингом 04:06:25; после неё success каждые 60 с. Остальные 6 AC M12b-fix
прошли у исполнителя. Docker 29.8.0 поддерживает `docker logs --since`.

## Разрешения

Правка `tests/deployed_m12b.py` (только правило логов monitor и запись в
deploy.json), `tests/test_deployed_m12b.py`, одна фраза в
`docs/research/07-deployed-service.md`. Запуск `--check-deploy`. Commit в клоне.

## Не трогать

Всё остальное, включая остальные функции runner, gateway/**, bench/**,
scripts/**, deploy/**, README, specs, TASKS/CHANGELOG, `/home/user/services/**`.
Сначала закоммитить эту спеку byte-identical (`docs/specs/m12b-fix2.md`).

## Критерии приёмки

- **AC-801.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-802.** check_deploy проходит и не меняет дерево сервиса:
  `bash -c 'snap(){ find /home/user/services/ai-browser-gateway/releases /home/user/services/ai-browser-gateway/manifests -printf "%p %m %T@ %C@ %s\n" | sort | sha256sum; }; a=$(snap) && python3 tests/deployed_m12b.py --check-deploy && b=$(snap) && test "$a" = "$b"'`
- **AC-803.** Окно логов записано в улики:
  `bash -c 'python3 -c "import json,sys; d=json.load(open(\"/home/user/.cache/abg-coord-20260917/m12b/deploy.json\")); sys.exit(0 if d.get(\"monitor_recent_logs_empty\") is True and d.get(\"monitor_log_window_seconds\") == 150 else 1)"'`
- **AC-804.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 895bc83e9f5b4e2339a68783fe8adcad162b8b64 HEAD -- . ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)docs/research/07-deployed-service.md" ":(exclude)docs/specs/m12b-fix2.md"'`
- **AC-805.** Чистое дерево и спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m12b-fix2.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 895bc83e9f5b4e2339a68783fe8adcad162b8b64 --range 895bc83e9f5b4e2339a68783fe8adcad162b8b64..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Если ответ отвергнут wrapper'ом
только по формату — сохранить квитанцию, записать в report-blocked.md и
сдавать: координатор проверит сам.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-801…AC-805,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"895bc83e9f5b4e2339a68783fe8adcad162b8b64","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-801","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m12b-fix2-20260917 --spec /home/user/exec-clones/abg-m12b-fix2-20260917/docs/specs/m12b-fix2.md --timeout 1200`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если в окне 150 с у monitor есть
ошибки доставки (это настоящий сигнал — записать класс ошибки без URL, не
расширять окно), если нужна правка вне разрешённого или рестарт сервиса.
Спеку, AC, BASE и оснастку не менять, rc не выдумывать.
