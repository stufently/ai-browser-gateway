# M13b-fix2 — уборка не крутится 30 с по уже удалённому контейнеру

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `858fd85fa729088c1fd9ced11bcc88a7b025e5ff` — FINAL M13b-fix.
Клон /home/user/exec-clones/abg-m13b-fix2-20260917, ветка m13b-fix2, origin push DISABLED. Исполнитель — cx (директива
владельца 17.09.2026: «доделывай всё до конца»). M13b-fix писала другая cx-панель.

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать. Push/merge запрещены. Продукт, импорт и assertions — только Docker
1002:1002 с `--network none`; host — git/файлы/оркестрация. Реальный
Docker-сокет в контейнеры не монтировать.

## Задача

Codex result review M13b-fix нашёл, координатор подтвердил чтением
`bench/runner/execute.py:_cleanup`: если cidfile заполнен, а контейнер уже
удалён (`--rm` провайдера, shutdown-sweep `gateway/service.py:sweep_providers`),
`docker rm --force <cid>` возвращает ненулевой код (`No such container`), и
цикл повторяет удаление до истечения всех 30 с. Запрос с бюджетом 1 с занимает
~31 с, превышая клиентский таймаут и удерживая `LaunchGate`. Тот же эффект, если
`docker ps` по метке нашёл контейнер, а к моменту `rm` он уже исчез.

Требование (контракт поведения): как только уборка УВИДЕЛА контейнер этого
запуска (id из cidfile либо непустой успешный `docker ps` по метке), успешный
(`returncode == 0`) `docker ps --all --quiet --filter label=<identity>` с
пустым выводом означает «контейнер убран» — уборка сразу возвращается. После
неуспешного `rm` следующая итерация делает такую проверку по метке, а не
повторяет `rm` вслепую. Пока контейнер НЕ виден ни разу, пустой `ps` —
по-прежнему «ещё не создан», опрос продолжается до общего дедлайна 30 с
(поздний create). Неуспешный `ps` (rc≠0, исключение) ничего не доказывает:
продолжать опрос в пределах дедлайна. Все прочие свойства M13b-fix сохраняются:
уникальная метка на запуск, единый дедлайн 30 с, `timeout=remaining`, `env` и
`stdin=DEVNULL` в уборке, удаляется только свой контейнер, исходный
`TimeoutExpired` поднимается тем же объектом, нормальный путь не меняется.

Тесты в `tests/test_execute.py` (`DockerLauncherTests`, фейковый
`subprocess.run` и часы, как в M13b-fix), падающие на BASE по причине лишнего
ожидания:
- cidfile с id, `rm` → rc=1, `ps` по метке → rc=0 пусто: ровно
  `run, rm, ps`, исходный TimeoutExpired, часы продвинулись не больше, чем на
  время фейковых вызовов (без сна до дедлайна);
- `ps` по метке нашёл id, `rm` → rc=1, следующий `ps` пусто: возврат без
  ожидания дедлайна;
- контроль: cidfile с id, `rm` → rc=1, `ps` по метке снова возвращает id —
  опрос продолжается (повторный `rm`), в пределах 30 с;
- контроль: `ps` по метке → rc=1 с пустым выводом после увиденного
  контейнера не считается доказательством удаления.
Существующие тесты M13b-fix сохранить (менять только если они закрепляли
вслепую повторяемый `rm` — тогда объяснить в коммите).

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026 чтением BASE: цикл `_cleanup`
(`bench/runner/execute.py` ~49–81) выходит только при `removed.returncode == 0`
или по дедлайну; `ids = [cid] if cid else []` не переходит на метку после
неуспешного `rm`. `gateway/service.py:30-31` документирует ≤30 с уборки.
Предположение: frozen probe `tests/probe_m13_late_container.py` отвечает на
`docker ps --filter label=…` согласованно с созданными контейнерами; если
probe краснеет от проверки по метке — blocker с тестом и строкой assertion.

## Разрешения

Правка `bench/runner/execute.py` (только `DockerLauncher._cleanup` и при
необходимости `DockerLauncher.run`), `tests/test_execute.py`. Commit в клоне.

## Не трогать

Probe `tests/probe_m13_late_container.py`, frozen probes M9–M12, gateway/**,
остальной bench/**, deploy/**, scripts/**, остальные tests, другие specs,
TASKS/CHANGELOG, `/home/user/services/**`. Сначала закоммитить эту спеку
byte-identical (`docs/specs/m13b-fix2.md`).

## Критерии приёмки

- **AC-931.** Probe M13 зелёный и неизменный:
  `bash -c 'test "$(sha256sum tests/probe_m13_late_container.py | cut -d" " -f1)" = 68cb3f15e05d2e0ce018d71e736fb53f93b0e00669f92de262972c8a5a58f402 && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m13_late_container'`
- **AC-932.** Frozen probes M9–M12 неизменны и зелёные:
  `bash -c 'git diff --exit-code 858fd85fa729088c1fd9ced11bcc88a7b025e5ff HEAD -- tests/probe_m9_transport.py tests/probe_m10_product.py tests/probe_m11_api_cli.py tests/probe_m12_service.py tests/probe_m12_service_regressions.py && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions'`
- **AC-933.** Unit без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-934.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code 858fd85fa729088c1fd9ced11bcc88a7b025e5ff HEAD -- . ":(exclude)bench/runner/execute.py" ":(exclude)tests/test_execute.py" ":(exclude)docs/specs/m13b-fix2.md"'`
- **AC-935.** Чистое дерево, спека в git:
  `bash -c 'git ls-files --error-unmatch docs/specs/m13b-fix2.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base 858fd85fa729088c1fd9ced11bcc88a7b025e5ff --range 858fd85fa729088c1fd9ced11bcc88a7b025e5ff..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов. Ответ, отвергнутый wrapper'ом
только по формату, — сохранить квитанцию, записать в report-blocked.md и сдавать.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 5 записей AC-931…AC-935,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"858fd85fa729088c1fd9ced11bcc88a7b025e5ff","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-931","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m13b-fix2-20260917 --spec /home/user/exec-clones/abg-m13b-fix2-20260917/docs/specs/m13b-fix2.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если probe M13 нельзя сделать
зелёным правкой только `bench/runner/execute.py`, если правка ломает frozen
probe M9–M12, или если probe требует поведения, противоречащего контракту выше
(записать тест и строку assertion). Probe, спеку, AC, BASE и оснастку не
менять, rc не выдумывать.
