# M9 — настоящий fetcher: страница из Docker до ядра

## Шапка и где работать

- Реализацию запускать только после заморозки SHA независимого пробника.
  Литерал PROBE_SHA_PENDING запрещает запуск даже при зелёном статическом preflight.
- Репозиторий `/home/user/github/ai-browser-gateway`, дата 14.09.2026.
- BASE_SHA `4af46c52a4376d903f0fc49f41d211f94149a6c8`
  (`Record gateway readiness task and reconnaissance`). Клон снят именно с него.
- Клон `/home/user/exec-clones/abg-m9-real-fetcher-20260914`, ветка `m9-real-fetcher`.
- Новая спека: `launch_executor.sh auto ... --select-only` бросает монетку один
  раз; после подготовки независимых пробников запуск явным выбранным backend,
  повторно монетку не бросать. Остатки 5h/weekly обоих backend неизвестны.
- Код, тесты и все исправления пишет выбранный Grok/Spark. Основной Codex
  пишет спеку и принимает. Независимые пробники/мутации — противоположный backend.
- Живое дерево и чужие клоны не трогать. `git push`, merge, deploy запрещены,
  origin push URL отключён. Работу заберёт координатор через fetch из клона.
- Docker под deploy, bind mounts `--user 1002:1002`. Никаких sudo, установок
  на хост, чтения боевых `.env` или секретов. Опыты с процессами/tmux только
  Docker с фейками, host tmux socket и чужие процессы не трогать.

## Задача и почему

Владелец требует используемый шлюз. Сейчас `run()` принимает только поддельный
fetcher: реальный раннер сохраняет метрики, но выбрасывает страницу. Эта веха
закрывает транспорт. Следующая меняет продуктовую лестницу/приём без sentinel;
API, сервис, CLI и боевые профили egress идут после неё.

## Что проверено вживую, а что предположение

Разведка Grok: `/home/user/.cache/abg-coord-20260914/recon-result.md`, SHA256
`bcddcd468c76d3bc792f9deab9a1accb7575052daf3e59203e77feaded988b21`, дерево BASE_SHA.
Логи, команды, cwd, rc и SHA артефактов там. Координатор прочитал указанные ниже
тела в базовом дереве:

- `gateway.engine.run(request, fetcher)` зовёт `fetcher(PlanStep, remaining_ms)`;
  `ProviderReply` содержит `FetchResult` и `age_hours`. M7 sentinel обязателен.
- `bench.runner.execute.execute_plan` возвращает `RunRecord`, в нём нет тела;
  `_record` создаёт `html=''`, `text=sentinel if found else ''`.
- `probe.run_probe` получает `response['body']`, но не кладёт его в JSON.
  `main` принимает URL, sentinel и `--mode`. `parse_output` читает последнюю
  JSON-строку; `_validated` проверяет метрики, статус, enum, возраст входа.
- `build_argv` задаёт Docker user 1002:1002, browser shm=1g; Dockerfiles копируют
  пробник в `/opt/abg/probe.py`, browser entrypoint использует tini/Xvfb.
- `DockerLauncher` на timeout завершает конкретный контейнер через cidfile.
  Сейчас `execute_plan` временно меняет общий `os.environ['ABG_PROXY']`.
  Новый конкурентный fetcher не должен повторять этот подход.
- В curl нет браузерных заголовков и собственного timeout; browser timeout
  120000 ms. Браузерные заголовки полезны по исследованию фазы 1, но их эффект
  сегодня не измерен; заголовки и политика — следующая веха.
- 353 unittest зелёные в Docker (`python:3.14-slim`, image ID
  `sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6`).
  Старые mutation gates 105/105, 5/5, 4/4. Живой curl example.com: 200,
  sentinel=true, 559 bytes; HTML в записи отсутствует.

Образы curl/patchright/scrapling/rss/wayback уже локально. Веха использует их
как runtime с read-only bind нового пробника поверх `/opt/abg/probe.py`, не
меняет общие теги и не запускает сборку с плавающими версиями. Их входы
сохраняются. Новый пробник поддерживает старый CLI и старый JSON без тела.

## Что сделать

### 1. Опциональный протокол содержимого и таймаута пробника

`bench/providers/docker/probe.py`:

- Добавить keyword-only `include_content=False`, `budget_ms=None` к `run_probe`
  и CLI `--include-content`, `--budget-ms`. Старый вызов сохраняет поведение.
- При include_content JSON дополнительно несёт строки `html` и `text`:
  html = реальное декодированное body адаптера, text = текст этого HTML,
  с декодированными сущностями, без тегов и script/style/template содержимого.
  Нельзя заменять страницу строкой sentinel, заголовком или синтетической HTML.
  При исключении поля пустые. Без флага оба поля отсутствуют (benchmark JSONL
  по-прежнему не содержит страниц).
- Непустой sentinel остаётся обязательным. Эту проверку и `evaluate` не менять.
- budget_ms — положительный int, bool недопустим. Передать остаток от запуска
  пробника в сетевой timeout curl, patchright, scrapling, rss и wayback;
  использовать монотонные часы, учитывать startup, не выдавать новый полный
  бюджет каждой навигации. У входа с несколькими HTTP-запросами общий deadline.
  Без budget_ms остаются старые значения. Штатный timeout классифицировать
  `err='timeout'`. Внешний Docker timeout остаётся обязательным ограничителем.
- Не менять измеренное правило челленджей, провайдеров и параметры stealth.

### 2. Один реальный запрос поверх runner.execute

Добавить публичную функцию в `bench/runner/execute.py` (детали вынести в новый
`bench/runner/fetch.py`, если это сокращает смешение ответственности):

```python
fetch_page(provider, *, url, sentinel, budget_ms, launcher=None,
           egress=None, entrance_url=None, network=None
           ) -> tuple[FetchResult, float | None]
```

`provider` — имя из реестра. `launcher` по умолчанию DockerLauncher.
`egress` — None для direct или `(profile_name, proxy_url_or_None)`.
`network` — None по умолчанию; `'host'` только для своего тестового стенда.

- Валидация до запуска: positive int budget_ms (не bool), непустой sentinel,
  URL абсолютный http/https с hostname, без userinfo; неизвестный provider —
  ValueError. Невалидный пользовательский ввод — ValueError без утечки значений.
- build_argv использовать, расширять необязательными параметрами совместимо.
  Новый путь монтирует текущий абсолютный probe.py read-only; работает из
  любого cwd. Не включать весь репозиторий или Docker socket в провайдер.
- Только одна попытка, mode cold, без sleep/retry. launcher получает timeout
  `budget_ms / 1000`, включая доли секунды: нельзя округлять вверх до секунды.
- Proxy в Docker через `--env ABG_PROXY` без значения. Передавать окружение
  отдельного subprocess, не мутировать os.environ даже временно; параллельные
  direct/profile A/profile B не могут обменяться кредами. Расширение
  `DockerLauncher.run(argv, timeout, *, env=None)` обратно совместимо.
- Для rss без entrance_url и именованного egress без URL вернуть not_measured,
  не запускать Docker. Wayback без entrance_url использует URL запроса.
  requested_url сохраняет исходный URL, final_url берётся из ответа входа.
- Распарсить и строго проверить JSON/метрики через существующую проверку;
  html/text должны присутствовать и быть str. Отсутствующее/битое тело —
  provider_error, не синтетическая страница и не успех по sentinel bool.
- Возврат FetchResult с реальными HTML/text, метриками, final_url, challenge,
  статусом, возрастом. 403 с найденным sentinel остаётся 403 для evaluate.
  Ненулевой rc: 125/126/127 environment_error, прочие provider_error;
  внешняя TimeoutExpired/TimeoutError → timeout; невалидный протокол →
  provider_error. Детали stderr/stdout/креды не попадут в ошибку/лог/exception.
  При сбое html/text пустые. err от пробника учитывается, в том числе timeout.
- Старый execute_plan контракт/формат результата сохраняются. Не переписывать
  его поведение прокси в этой вехе: новый путь изолирован и тестируется отдельно.

### 3. Fetcher ядра

`gateway/fetch.py`:

```python
class BenchFetcher:
    def __init__(self, url, sentinel, *, entrances=None, profiles=None,
                 launcher=None, network=None): ...
    def __call__(self, step: PlanStep, budget_ms: int) -> ProviderReply: ...
```

Копии entrances/profiles (dict имя → URL) на экземпляре, не global.
Direct не использует профили; остальные только по имени. Неизвестный профиль
не должен незаметно стать direct. Обёртка вызывает fetch_page и переводит
его кортеж в ProviderReply. `gateway.engine.run` и модели M7 не менять.

### 4. Тесты, живой сценарий и документация

- Новые `tests/test_gateway_fetch.py`, при необходимости `tests/test_fetch_protocol.py`.
  Ключевые случаи: настоящие байты body, Unicode/entities, ошибки протокола,
  subsecond budget, env изоляция параллельных вызовов, входы/возраст,
  контейнерная отмена/классификация, отсутствие контента у benchmark.
- `tests/live_m9_fetch.py` — перезапускаемый сквозной сценарий: поднимает свой
  временный Docker HTTP-стенд, вызывает настоящий BenchFetcher через curl,
  patchright и scrapling по отдельности, затем `gateway.run` через HTTP.
  Проверяет динамический уникальный маркер в HTML и text (ожидание не только
  sentinel), 403 с маркером не успешен, медленный ответ обрывается по бюджету,
  относящиеся к прогону контейнеры отсутствуют после cleanup.
  Не трогать чужие контейнеры; создать/удалить только ресурсы своего прогона.
  По browser допускается до 30 s на холодный старт, стенд без внешней сети.
  Командный скрипт запускается на host только как Docker-оркестратор;
  весь продуктовый код/проверки внутри Docker под 1002:1002. Socket доступен
  только оркестратору; провайдерам его не монтировать.
- README: пример GatewayRequest с sentinel и BenchFetcher, требования Docker,
  что API/продуктовый вход без sentinel ещё впереди.

## Что кладёт постановщик

- Эта спека, без редактирования коммитится вместе с работой.
- Исполнителю обязательно закоммитить спеку `docs/specs/m9-real-fetcher.md`.
- `tests/probe_m9_transport.py`, независимый от автора реализации, коммитится
  без правок; SHA256 будет заморожен до запуска реализации: PROBE_SHA_PENDING.
- Независимый автор пробника перед запуском реализации проверяет его на базе
  (красный по отсутствию fetch_page/BenchFetcher), на эталонных копиях (зелёный)
  и обходных копиях (красный). Код эталонов в продукт не переносить.

## Не трогать

TASKS.md, CHANGELOG.md, docs/research/**, все старые спеки/пробники/тесты,
gateway/engine.py, gateway/models.py, gateway/plan.py, bench/models.py,
bench/escalate.py, реестр провайдеров/теги/образы, боевые конфиги, cf-fetch.
Разрешены только перечисленные новые файлы, probe.py, runner/execute.py,
registry.py (совместимое расширение argv), README.md и эта спека для коммита.
При необходимости общего хелпера — только bench/runner/fetch.py и
bench/providers/docker/content.py (если нужен, обеспечь доставку в контейнер).

## Критерии приёмки

- **AC-901.** Полный сьют один раз:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-902.** Замороженный независимый пробник:
  `bash -c 'echo "PROBE_SHA_PENDING  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m tests.probe_m9_transport'`
- **AC-903.** Настоящие контейнеры и сквозной сценарий:
  `bash -c 'python3 tests/live_m9_fetch.py'`
- **AC-904.** Регрессия старых мутаций транспорта/пробника:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py'`
- **AC-905.** Инварианты ядра/политики и исторических измерений не изменены:
  `bash -c 'git diff --exit-code 4af46c52a4376d903f0fc49f41d211f94149a6c8 HEAD -- gateway/engine.py gateway/models.py gateway/plan.py bench/models.py bench/escalate.py docs/research TASKS.md CHANGELOG.md'`
- **AC-906.** Ожидаемые файлы закоммичены, рабочее дерево чисто:
  `bash -c 'git ls-files --error-unmatch gateway/fetch.py tests/test_gateway_fetch.py tests/live_m9_fetch.py tests/probe_m9_transport.py docs/specs/m9-real-fetcher.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

Предполётные ожидания: suite и исторические инварианты зелёные; новые probe,
live и состав красные по отсутствию новых файлов, не по среде. После доставки
независимого probe он красный по отсутствию fetch_page. Логи baseline приложить.

## Контракт на невыполнимое

Противоречие, отсутствующий ресурс, неподтверждённая гипотеза: остановиться,
сохранить report-blocked.md с командой, cwd, rc и дословным безопасным выводом.
Запрещено ослаблять критерии, менять замороженный зонд, выдумывать числа,
глушить rc, обходить launcher/ограничения, устанавливать зависимости на host.
Дефекты приёмки возвращаются тому же backend отдельным заданием.

## Авторевью и передача

Применить cross-review-v1 через АБСОЛЮТНУЮ обёртку
`bash /home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh`.
До ревью коммит REVIEW_SHA, full.diff = BASE_SHA..REVIEW_SHA.
Оба ревью запускает исполнитель параллельно, только чтение:
Grok → codex + agy; Spark → grok + agy. AGY_MODEL=gemini-3.8-flash-high,
AGY_TIMEOUT=900. Дополнительно Codex result обязателен по инструкции владельца
для этого проекта, если автор Spark: отдельный read-only вызов ask-codex,
сохранить сырой вердикт (самостоятельным автором реализации он не является).
Пример квитанции:
`bash /home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh initial agy --clone /home/user/exec-clones/abg-m9-real-fetcher-20260914 --base 4af46c52a4376d903f0fc49f41d211f94149a6c8 --range <BASE_SHA>..<REVIEW_SHA> --context '<суть; только чтение>'`.
Для обеих фаз одинаковый --base. run_id = basename клона + '-' + BASE_SHA[:12].
Журнал вне клона в ~/.cache/tg-claude/review-journal/<run_id>/.
Оборванный ответ, обрезанный вход, отсутствие финального `ВЕРДИКТ: ПРИНЯТО`
или `ВЕРДИКТ: НЕ ПРИНИМАТЬ` означает incomplete, даже rc=0.
Дождаться обоих, свести находки: fixed/disproved с доказательством либо needs_owner.
Один заход фиксов (несколько коммитов допустимы) → FINAL_SHA; те же ревьюеры
один раз проверяют REVIEW_SHA..FINAL_SHA. Неизменный код повторно не ревьюить.
Новый дефект/спор после verification → needs_owner, второй автономный круг
не начинать. Один технический повтор незавершённого вызова; quota error без
повторов. Квитанции создаёт только review_run.sh, не вручную.

## Контракт отчёта

report.json v2 в корне untracked, ровно шесть критериев AC-901…AC-906.
Команды из спеки посимвольно; blocked: rc=null и причина, не фиктивный ноль.
Поля обязательны:
```json
{"schema_version":2,"policy_id":"cross-review-v1",
 "spec_sha256":"<sha256 этой спеки>",
 "base_sha":"4af46c52a4376d903f0fc49f41d211f94149a6c8",
 "reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"grok|spark","model":"<точная модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready",
 "criteria":[{"id":"AC-901","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<доказательство>"}]}
```
Исполнитель сам запускает машинный гейт
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m9-real-fetcher-20260914 --spec /home/user/exec-clones/abg-m9-real-fetcher-20260914/docs/specs/m9-real-fetcher.md --timeout 3600`.

Пакет вне клона: `/home/user/.cache/abg-coord-20260914/m9/`: полный diff,
команды/cwd/rc/SHA/логи suite и живого сценария, квитанции/находки/решения.
Независимые мутации новых тестов выполнит противоположный backend отдельным
заданием координатора на FINAL_SHA; автор кода их не подменяет. Grok собирает
их с пакетом. Основной Codex делает одну финальную независимую приёмку:
полный diff, SHA/логи/ревью, гейт --timeout 3600, сквозной сценарий и мутации.
Зелёный гейт не разрешает push и не заменяет эту приёмку.
