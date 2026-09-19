# M17 — оснастка сохраняет причину отказа воркера

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 19.09.2026.
BASE_SHA `da97ec9a2647da5165374780f6a28e7e5226df86` — вершина main после
закрытия M16c.
Клон /home/user/exec-clones/abg-m17-20260919, ветка m17-harness-cause,
origin push DISABLED. Исполнитель — cx (директива владельца: «доделывай все
через кодекс»). Задача поставлена владельцем 19.09.2026: «заводи веху на
оснастку, чтобы причина отказа сохранялась».

Трогаем ТОЛЬКО оснастку проверки развёрнутого сервиса. Продуктовый код
(`gateway/**`, `bench/**`) не меняется вообще.

## Зачем

`tests/deployed_m12b.py` — проверялка боевого сервиса. Реальные HTTP-запросы
она делает изнутри одноразового контейнера-воркера, чтобы токен и прокси-креды
не покидали его; наружу воркер отдаёт JSON. Сейчас ЛЮБОЙ отказ воркера
схлопывается в одну строку `worker_internal_error` (строка 212), а сам воркер
кладёт в `internal_error` лишь три общих значения — `worker_timeout`,
`worker_connection`, `worker_failure`. Причём в `worker_failure` попадает и
разбор ответа шлюза: `parse_api` бросает `CheckError('api_http_error')` при
HTTP 500, а общий `except Exception` превращает это в то же самое
`worker_failure`.

Цена этого измерена вживую 18.09.2026 на выкладке M16c: проверка ротации
egress упала с `worker_internal_error`, и отличить сбой прокси от HTTP 500 самого шлюза
оказалось НЕЧЕМ — логи контейнеров пусты, ответ не сохранён. Веха была принята
с открытым критерием, потому что улик для вывода не хватило. Задача M17 —
сделать так, чтобы в следующий раз причина была видна из отчёта.

Ограничение, ради которого всё и построено: наружу нельзя выпускать секреты.
Поэтому причина передаётся только в виде СТАТИЧЕСКИХ кодов (`CheckError`
документирован как «static, non-secret internal failure code») и имени класса
исключения — но НЕ текста произвольного исключения, который может содержать
URL с кредами или токен.

## Задача

1. **Воркер различает разбор ответа и прочие падения.** В `worker()` перед
   общим `except Exception` добавить ветку для `CheckError`:
   `{'internal_error': 'worker_check', 'cause': <код CheckError>}`. Общую ветку
   дополнить именем класса: `{'internal_error': 'worker_failure',
   'cause': <тип исключения>}`. Текст произвольного исключения наружу НЕ
   отдавать. Ветки `worker_timeout` и `worker_connection` не трогать —
   они уже конкретны и `cause` им не нужен.
2. **Статус ответа шлюза виден.** В ветке действий `api`/`bizprofile`/`health`/
   `unauthorized` обернуть вызов `parse_api` так, чтобы к коду добавлялся
   HTTP-статус, который воркер реально увидел: `api_http_error:500`,
   `api_invalid_schema:200`. Коды самого `parse_api` НЕ менять: на них стоит
   тест с якорем `^api_http_error$` (`tests/test_deployed_m12b.py:51`).
3. **Вызывающая сторона отдаёт причину наружу.** В `worker_call()` заменить
   общий `require(... 'internal_error' not in data, 'worker_internal_error')`
   на проверку словаря плюс отдельный подъём `CheckError` с причиной:
   `worker_internal_error:<internal_error>[:<cause>]`, пропущенный через
   `redact()`. Проверку «ответ — словарь» сохранить отдельным кодом.
   Существующий путь сохранения улик (`save(mode + '-result', {'ok': False,
   'internal_error': redact(error)})`) менять не нужно: он уже пишет текст
   `CheckError` в файл, и причина попадёт в улики сама.
4. **Тесты `tests/test_deployed_m12b.py`**, класс `WorkerTests` (в нём уже есть
   помощник `invoke`). Значения ниже ПОСЧИТАНЫ координатором на прототипе
   правки, а не выведены рассуждением:
   - шлюз ответил HTTP 500 → воркер отдаёт
     `{'internal_error': 'worker_check', 'cause': 'api_http_error:500'}`;
   - шлюз ответил 200 с непригодной схемой (`{"ok": true}`) →
     `{'internal_error': 'worker_check', 'cause': 'api_invalid_schema:200'}`;
   - `OSError` на открытии соединения → `{'internal_error': 'worker_connection'}`
     (без `cause`, как и было);
   - `TimeoutError` → `{'internal_error': 'worker_timeout'}` (без `cause`);
   - прочее исключение (`ValueError('secret-tok')`) →
     `{'internal_error': 'worker_failure', 'cause': 'ValueError'}`, и текста
     `secret-tok` в выводе НЕТ.
   Отдельный тест на `worker_call` (подменяя `docker`): текст поднятого
   `CheckError` равен
   `worker_internal_error:worker_check:api_http_error:500`,
   `worker_internal_error:worker_connection`,
   `worker_internal_error:worker_timeout`,
   `worker_internal_error:worker_failure:ValueError`.
   Этот тест назвать `test_worker_call_reports_failure_cause`.
   Отдельный тест на утечку: если воркер вернул `cause` с токеном, URL или
   `Bearer …`, в тексте `CheckError` их нет (сработал `redact`); назвать
   `test_worker_call_redacts_secrets_in_cause`.
5. **Мутанты**: два новых в `tests/mutation_gate_gateway.py` (он умеет
   `"path"`, см. существующие мутанты форматтера) — по одному на пункт 1 и
   пункт 3, с `"path": "tests/deployed_m12b.py"`. Каждый обязан убиваться своим
   новым тестом. Итого в этих воротах 13.
6. **Документ** `docs/research/04-phase1-verdict.md`: в разделе про M16c
   заменить фразу о долге оснастки на описание того, что теперь причина
   сохраняется, с перечнем кодов.

## Что проверено вживую, а что предположение

Проверено координатором 19.09.2026 на прототипе правки (Docker, образ из
критериев, `--network none`): все пять кортежей пункта 4 и четыре строки
`CheckError`; полный набор из 613 тестов остаётся зелёным; ворота
`tests/mutation_gate_gateway.py` на BASE дают 11/11. Проверено чтением кода:
`parse_api` вызывается только внутри `worker()`; на код `api_http_error` стоит
тест с якорем `^api_http_error$`; `redact()` вычищает URL, `Bearer …`,
`token=…` и 64-значный hex.

Предположение: имена новых тестов и точное место веток — на усмотрение автора.

## Разрешения

Правка `tests/deployed_m12b.py`, `tests/test_deployed_m12b.py`,
`tests/mutation_gate_gateway.py`, `docs/research/04-phase1-verdict.md`.
Docker-прогоны образом из критериев. Commit в клоне. Первым коммитом
закоммитить эту спеку `docs/specs/m17-harness-failure-cause.md` byte-identical.

## Не трогать

`gateway/**`, `bench/**`, `scripts/**`, `deploy/**`, остальные файлы `tests/**`,
другие specs, TASKS.md, CHANGELOG.md, `secrets/**`, `/home/user/services/**`
(боевой сервис В ЭТОЙ ВЕХЕ НЕ ТРОГАЕТСЯ ВООБЩЕ — ни выкладки, ни живых
запросов). Сеть не нужна: все проверки офлайн. Push и merge запрещены.

## Критерии приёмки

- **AC-200.** Unit и frozen probes без регрессий:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-201.** Новые тесты причины зелёные (машинная проверка пунктов 1–4):
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_deployed_m12b.WorkerTests'`
- **AC-202.** Причина доходит до вызывающей стороны, а секрет — нет
  (имена тестов фиксированы: на них ссылаются мутанты):
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_deployed_m12b.WorkerTests.test_worker_call_reports_failure_cause tests.test_deployed_m12b.WorkerTests.test_worker_call_redacts_secrets_in_cause'`
- **AC-203.** Мутационные ворота шлюза: два новых убиты, всего 13. Считаются
  только строки отдельных мутантов; итоговая строка прогона в счёт не идёт
  (на BASE точный счётчик даёт 11, а счёт по одному слову дал бы 12):
  `bash -c 'set -o pipefail; n=$(docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate_gateway.py | grep -c ": killed") && test "$n" -eq 13 && test -z "$(git status --porcelain -- tests ":(exclude)report.json")"'`
- **AC-204.** Документ:
  `bash -c 'grep -q "worker_check" docs/research/04-phase1-verdict.md && grep -q "api_http_error" docs/research/04-phase1-verdict.md'`
- **AC-205.** Вне разрешённых путей ничего не изменено, дерево чистое, боевой сервис не тронут:
  `bash -c 'git diff --exit-code da97ec9a2647da5165374780f6a28e7e5226df86 HEAD -- . ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)tests/mutation_gate_gateway.py" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m17-harness-failure-cause.md" && git ls-files --error-unmatch docs/specs/m17-harness-failure-cause.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1: после commit REVIEW_SHA параллельно
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m17-20260919 --base da97ec9a2647da5165374780f6a28e7e5226df86 --range da97ec9a2647da5165374780f6a28e7e5226df86..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать все finding_id; один FIX_ONCE, затем
verify на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов, записать в note.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 6 записей AC-200…AC-205, command посимвольно из спеки; blocked — rc=null и
безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"da97ec9a2647da5165374780f6a28e7e5226df86","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-200","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m17-20260919 --spec /home/user/exec-clones/abg-m17-20260919/docs/specs/m17-harness-failure-cause.md --timeout 3600`.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
какой-то из посчитанных кортежей пункта 4 недостижим (показать фактический
результат — это ошибка координатора, а не повод менять правило); мутант не
убивается своим тестом; правка требует выхода за разрешённые файлы; для
проверки понадобился боевой сервис или сеть. Спеку, AC, BASE и оснастку
приёмки не менять, rc не выдумывать, чужое не трогать.
