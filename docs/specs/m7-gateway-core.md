# Веха M7 — ядро шлюза: лестница как код

| | |
|---|---|
| Репозиторий | `ai-browser-gateway` (с 14.09.2026 — `git@github.com:stufently/ai-browser-gateway.git`) |
| Дата | 14.09.2026 |
| BASE_SHA | `1337140b51482eb9b6d65cc60a406e533b627e4d` («Ignore executor scratch dirs») — коммит, С КОТОРОГО СНЯТ КЛОН |
| Клон | `/home/user/exec-clones/abg-m7-gateway-core`, ветка `m7-gateway-core` от `main` |
| Исполнитель | **Codex (`cx`)** — веха чисто алгоритмическая, без сети и Docker; квота Grok в этот момент занята двумя другими панелями |
| Ревью | запускает ИСПОЛНИТЕЛЬ (`ask-grok` + `ask-agy`, параллельно) на СВОЕЙ квоте ДО передачи ветки — порядок в разделе «Авторевью». Постановщик после передачи читает находки и вердикты, своих ревью не гоняет. Машинерии `cross-review-v1` в этом репозитории НЕТ — не искать её и не запускать `review_run.sh`. *(Строка исправлена постановщиком 14.09.2026: прежняя редакция говорила «запускает постановщик» и противоречила разделу «Авторевью»; исполнитель законно остановился по «Контракту на невыполнимое».)* |
| Критериев | 6 |

## Где работать

- Клон `/home/user/exec-clones/abg-m7-gateway-core`, ветка `m7-gateway-core`.
- **Живое дерево `/home/user/github/ai-browser-gateway` не трогать.**
- **`git push` запрещён, включая `origin`.** Работу заберёт постановщик через
  `git -C /home/user/github/ai-browser-gateway fetch <клон> m7-gateway-core:m7-gateway-core`.
  Локальные коммиты обязательны, `git add` — по именам файлов, никогда `-A`.
- Зависимостей нет: только стандартная библиотека, `python3` на хосте 3.14.4,
  `requires-python = ">=3.12"`. Ставить пакеты на хост запрещено.
- Сети и Docker для этой вехи не нужно вовсе: всё проверяется на поддельном
  fetcher'е.

### Что кладёт постановщик ДО запуска (untracked, в корне клона)

| Файл | sha256 | Размер |
|---|---|---|
| `docs/specs/m7-gateway-core.md` | эта спека | — |
| `tests/coordinator_probe_gateway.py` | `a39340921a5dc12d43779a3d9ecc4e8b7a2fd4879e3fcca028d3089861825914` | ~8 КБ |

Оба файла **коммитятся вместе с работой** (иначе критерий чистоты дерева
недостижим). Зонд постановщика **править запрещено** — его sha256 сверяется
критерием AC-703. Зонд опирается только на публичный контракт из этой спеки;
если он падает — дефект в твоём коде либо в спеке, но не в зонде.

## Задача и почему

Фаза 1 закончена: измерено, какие способы достать страницу чего стоят, и написан
вердикт `docs/research/04-phase1-verdict.md`. **Самого шлюза при этом нет** — в
репозитории живёт только бенчмарк `bench/`, который умеет прогнать матрицу
«провайдер × цель» и построить отчёт. Продукта, который по одному URL сам
выбирает самый дешёвый достаточный способ, не существует ни строкой.

Эта веха кладёт его ядро — **лестницу как код**, отдельным пакетом `gateway/`,
без сети и без Docker. Ядро решает ЧТО и В КАКОМ ПОРЯДКЕ дёргать, а сам поход в
сеть получает извне (внедряемый `fetcher`). Так ядро проверяется целиком на
поддельных ответах, а следующая веха приносит настоящий fetcher поверх
`bench.runner`.

### Правило лестницы (оно измерено, не придумано)

Главный вывод замера: **браузер окупается рендерингом, а не обходом блокировок**
(`docs/research/04-phase1-verdict.md`). Ни один из пяти движков не добавил ни
одной цели к обычному HTTP-клиенту, зато на стенде способностей браузер берёт
7 сценариев из 12 против 5. Отсюда:

- признак для запуска браузера — **`content_missing` / `javascript_required`
  при `challenge = none`**: ответ пришёл, а содержимого в нём нет;
- `403`/`429` браузером **не лечится** — это про адрес, а не про инструмент, и
  оттуда дорога только в смену egress;
- вторая подряд неудача после смены egress — `human`, молча дальше не ломимся.

Ровно это уже записано в `bench/escalate.py::next_step` и проверено тестами
`tests/test_escalate.py`. **Веха не переписывает это правило, она его
ИСПОЛНЯЕТ.** Твоя задача — превратить одиночное решение «куда дальше» в
проход по лестнице с записью следов и бюджетом.

### Свежесть как условие обходного входа

Обходные входы (`rss`, `wayback`) стоят ноль и в одном случае из пяти оказались
ЕДИНСТВЕННЫМ работающим способом, но приносят СТАРОЕ содержимое: в живом
прогоне `wayback` отдавал снимок возрастом 220 часов, `rss` — 0,02 часа. Веха M6
уже сделала свежесть квалификатором покрытия. Поэтому здесь:

> **Вход участвует в лестнице только тогда, когда вызывающий явно разрешил
> несвежесть** (`max_age_hours > 0`), и его ответ засчитывается успехом только
> при `age_hours is not None and age_hours <= max_age_hours`.

При `max_age_hours == 0` (умолчание) входов в плане нет вовсе.

## Что проверено вживую, а что предположение

Каждое утверждение ниже подтверждено чтением тела кода в базовом коммите, а не
памятью.

- `bench/models.py`: `FetchResult` — frozen dataclass со слотами, поля ровно
  такие: `provider, provider_version, requested_url, final_url, status, html,
  text, elapsed_ms, startup_ms, cpu_ms, peak_rss_mb, bytes_received, redirects,
  error_type, challenge`. **Проверено.**
- `bench/models.py::evaluate(result, sentinel) -> (bool, FailureReason)` на
  пустом `sentinel` поднимает `ValueError`, на `error_type != none` возвращает
  эту же причину, на 403/429/5xx — свою, на найденном sentinel — `(True,
  none)`, на 200 без sentinel — `content_missing`. **Проверено чтением тела.**
- `bench/escalate.py::next_step(error_type, challenge, *, egress_changed)`
  возвращает `Step`; `Step` — `StrEnum` со значениями `stop, browser,
  change_egress, retry_later, give_up, human, investigate`. При
  `egress_changed=True` любой `change_egress` превращается в `human`.
  **Проверено чтением тела.**
- `bench/providers/registry.py`: `PROVIDERS` содержит `curl`, `curl_cffi`,
  `primp`, `playwright`, `patchright`, `camoufox`, `pydoll`, `wayback`, `rss`;
  у `Provider` есть поля `name, image, tier, kind, needs_network, argv_extra`,
  где `kind ∈ {'http','browser','entrance'}`; `by_name(name)` бросает `KeyError`
  на неизвестном имени. **Проверено.**
- `entrance_age_hours` в базовом коммите живёт на `RunRecord`
  (`bench/runner/record.py`), а НЕ на `FetchResult`; пробник кладёт его в JSON
  ответа входа (`bench/providers/docker/probe.py`). **Проверено.** Поэтому в
  ядре возраст приезжает отдельным полем `ProviderReply.age_hours`, а
  `FetchResult` не расширяется.
- Тесты гоняются `python3 -m unittest discover -s tests -t .` из корня;
  мутационный гейт бенчмарка — `python3 tests/mutation_gate.py`. **Проверено.**
- **Предположение:** у вызывающего когда-нибудь появится больше одного
  egress-профиля. Сейчас у владельца ноль рабочих профилей (креды GoldProxy не
  выданы), поэтому ветка смены egress проверяется только на поддельном fetcher'е.

## Что сделать

### 1. `gateway/models.py`

Frozen dataclasses со `slots=True`:

```python
@dataclass(frozen=True, slots=True)
class GatewayRequest:
    url: str
    sentinel: str
    max_age_hours: float = 0.0
    allow_browser: bool = True
    egress_profiles: tuple[str, ...] = ()
    budget_ms: int = 30_000

@dataclass(frozen=True, slots=True)
class PlanStep:
    provider: str
    egress_profile: str       # "direct" либо имя профиля
    purpose: str              # "entrance" | "http" | "browser" | "egress"

@dataclass(frozen=True, slots=True)
class ProviderReply:
    result: FetchResult
    age_hours: float | None = None

@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    egress_profile: str
    success: bool
    error_type: FailureReason
    challenge: ChallengeType
    status: int | None
    elapsed_ms: int
    age_hours: float | None
    next_step: Step | None   # None — решение не принималось (шаг-вход)

@dataclass(frozen=True, slots=True)
class GatewayOutcome:
    ok: bool
    url: str
    final_url: str
    html: str
    text: str
    provider: str | None
    age_hours: float | None
    error_type: FailureReason
    step: Step
    attempts: tuple[Attempt, ...]
    elapsed_ms: int
```

### 2. `gateway/plan.py` — `plan_steps(request) -> tuple[PlanStep, ...]`

Меню шагов, упорядоченное по цене. Состав:

1. если `request.max_age_hours > 0` — `rss`, затем `wayback`, оба `direct`,
   `purpose="entrance"`;
2. всегда — `curl` на `direct`, `purpose="http"`;
3. если `request.allow_browser` — `patchright` на `direct`, `purpose="browser"`;
4. для каждого профиля из `request.egress_profiles`, В ПОРЯДКЕ ОБЪЯВЛЕНИЯ —
   `curl` на этом профиле, `purpose="egress"`.

План — именно меню: порядок в нём задаёт цену, а выбирает шаг движок по
решению `next_step`. Функция чистая: ни ввода-вывода, ни часов.

### 3. `gateway/engine.py` — `run(request, fetcher, *, clock=...) -> GatewayOutcome`

- `fetcher` — вызываемый объект `fetcher(step: PlanStep, budget_ms: int) -> ProviderReply`.
- `clock` — вызываемый объект без аргументов, возвращающий монотонные
  миллисекунды; умолчание берёт `time.monotonic_ns() // 1_000_000`. Ядро НЕ
  зовёт `time.sleep` и ничего не ждёт.
- Порядок работы:
  1. `request.sentinel == ""` → `ValueError` (пустое ожидание — дефект вызова,
     ровно как в `evaluate`); пустой `url` и `budget_ms <= 0` → тоже `ValueError`;
  2. строится план; курсор идёт по плану сверху вниз;
  3. перед каждой попыткой считается `remaining = request.budget_ms - (clock() - start)`;
     если `remaining <= 0` — проход останавливается с `error_type = timeout`,
     `step = Step.retry_later` и уже накопленными попытками; fetcher при этом
     **не вызывается**;
  4. попытка: `reply = fetcher(step, remaining)`; затем
     `ok, reason = evaluate(reply.result, request.sentinel)`;
  5. **шаги-входы опортунистические.** Если `registry.by_name(step.provider).kind
     == "entrance"`, то `bench.escalate.next_step` для этой попытки НЕ вызывается
     вовсе, а `Attempt.next_step` = `None`. Ответ входа либо принимается —
     `ok` И `reply.age_hours is not None` И `reply.age_hours <= request.max_age_hours`,
     — либо попытка записывается неуспешной (`error_type = content_mismatch`,
     если сам ответ был успешным, но протух; иначе причина от `evaluate`), и
     движок просто переходит к СЛЕДУЮЩЕМУ шагу плана. Причина такого правила:
     отказ обходного входа ничего не говорит о защите цели — ярлык не сработал,
     идём обычной дорогой. Через `escalate` это провести нельзя: `content_mismatch`
     там означает `give_up`, и лестница встала бы на первом же протухшем снимке;
  6. для всех ОСТАЛЬНЫХ шагов вызывается
     `next_step(reason, reply.result.challenge, egress_changed=<был ли уже шаг с purpose="egress">)`;
     попытка дописывается в след со всеми полями, включая это решение;
  7. `ok` → успех: `provider`, `html`, `text`, `final_url`, `age_hours` берутся
     из этого ответа, `step = Step.stop`, `error_type = none`;
  8. иначе маршрутизация по решению:
     - `Step.browser` → следующий шаг с `purpose="browser"`; такого нет (браузер
       запрещён или уже израсходован) → остановка с `step = Step.browser`;
     - `Step.change_egress` → следующий неиспользованный шаг с `purpose="egress"`;
       такого нет → остановка с `step = Step.change_egress`;
     - `Step.retry_later | give_up | human | investigate` → немедленная
       остановка с этим же `step`;
     - `Step.stop` при неуспехе недостижим — если он всё же пришёл, это
       `AssertionError` с текстом, а не молчаливый успех;
  9. план кончился без успеха → `ok = False`, `step` и `error_type` от последней
     попытки.
- Провайдер, выбранный движком, вызывается РОВНО ОДИН раз за проход: попытка
  «ещё раз то же самое» запрещена.
- `elapsed_ms` итога — разница часов между началом и концом прохода.

### 4. Тесты и мутационный гейт

- `tests/test_gateway_plan.py` и `tests/test_gateway_engine.py` — поведенческие
  тесты на поддельном fetcher'е; свою фикстуру клади в `tests/gateway_helpers.py`.
- `tests/mutation_gate_gateway.py` — **не меньше пяти** мутаций по ЭТОЙ вехе, по
  форме `tests/mutation_gate.py`: сохранить байты и sha256 → прогнать целевой
  тест на ЧИСТОМ дереве и убедиться, что он зелёный → проверить, что заменяемый
  фрагмент встречается ровно один раз → наложить мутацию → прогнать ИМЕННО
  целевой тест → откатить в `finally` и сверить sha256 → вернуть 0, только если
  каждый мутант убит СВОИМ тестом на СВОЕЙ строке ассерта. Обязательные цели
  мутаций: порог свежести входа, ветка `Step.browser`, ветка `change_egress`,
  проверка бюджета, флаг `egress_changed`.

### 5. Документация

- `CHANGELOG.md` — запись 14.09.2026 про пакет `gateway/`.
- `TASKS.md` — веха в `DONE` одним абзацем: что закрыто и что осталось
  следующей вехе. `IN_PROGRESS` не оставлять.
- `README.md` — короткий раздел «Ядро шлюза» с примером вызова `run(...)`.

## Не трогать

- **Весь `bench/`** — читать и импортировать можно, изменять нельзя ни строкой.
  Особенно `bench/escalate.py`, `bench/models.py`, `bench/providers/registry.py`:
  правило эскалации и таксономия отказов — контракт вех M1–M6.
- `docs/research/**` — измеренные числа не переписываются.
- Существующие тесты в `tests/` — новые файлы добавляй, чужие не редактируй.
- `tests/coordinator_probe_gateway.py` — зонд постановщика, sha256 зафиксирован.
- Эта спека — исключение из «не трогать» только в смысле коммита: её надо
  закоммитить вместе с работой, но не редактировать.

## Критерии приёмки

- **AC-701.** Полный корпус зелёный, новые тесты входят сюда же:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && python3 -m unittest discover -q -s tests -t .'`
- **AC-702.** Мутационный гейт вехи: не меньше пяти мутаций, каждая убита своим
  тестом, файлы восстановлены:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && python3 tests/mutation_gate_gateway.py'`
- **AC-703.** Зонд постановщика не изменён и зелёный:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && echo "a39340921a5dc12d43779a3d9ecc4e8b7a2fd4879e3fcca028d3089861825914  tests/coordinator_probe_gateway.py" | sha256sum -c - && python3 -m tests.coordinator_probe_gateway'`
- **AC-704.** Ядро не ходит в сеть и не запускает процессов — ни одного импорта
  `subprocess`, `socket`, `urllib`, `http`, `requests`, `docker`, `asyncio` в
  `gateway/`:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && python3 -c "
import ast, pathlib
banned = {\"subprocess\", \"socket\", \"urllib\", \"http\", \"requests\", \"docker\", \"asyncio\"}
bad = []
for path in sorted(pathlib.Path(\"gateway\").rglob(\"*.py\")):
    tree = ast.parse(path.read_text(encoding=\"utf-8\"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [(str(path), alias.name) for alias in node.names if alias.name.split(\".\")[0] in banned]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(\".\")[0] in banned:
                bad.append((str(path), node.module))
assert not bad, bad
assert list(pathlib.Path(\"gateway\").rglob(\"*.py\")), \"пакета gateway нет вовсе\"
"'`
- **AC-705.** `bench/` и `docs/research/` не изменены ни на байт:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && test -z "$(git diff --name-only 1337140b51482eb9b6d65cc60a406e533b627e4d..HEAD -- bench docs/research)"'`
- **AC-706.** Состав работы на месте, дерево чистое:
  `bash -c 'cd /home/user/exec-clones/abg-m7-gateway-core && git ls-files --error-unmatch gateway/models.py gateway/plan.py gateway/engine.py tests/test_gateway_plan.py tests/test_gateway_engine.py tests/mutation_gate_gateway.py tests/coordinator_probe_gateway.py docs/specs/m7-gateway-core.md > /dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

## Контракт отчёта

`report.json` в КОРНЕ клона, untracked, записей ровно шесть — `AC-701…AC-706`:

```json
{"criteria": [{"id": "AC-701", "status": "pass|fail|blocked",
               "command": "<команда ИЗ ЭТОЙ СПЕКИ, посимвольно>", "rc": 0, "note": "…"}]}
```

Строку `command` копируй из спеки **дословно**. `blocked` — штатный исход, когда
среда не даёт выполнить критерий: тогда `"rc": null` и дословная ошибка в `note`.
Обходить несовместимость ЗАПРЕЩЕНО: `--no-deps`, `--break-system-packages`,
`|| true`, `|| :`, `set +e` в самой команде критерия, `sudo`, `git push`.
Хвостовой `echo` после `;` в команде критерия запрещён — он обнуляет код
возврата и превращает критерий в пустышку.

## Контракт на невыполнимое

Наткнулся на противоречие в спеке, на невыполнимый критерий или на факт,
опровергающий её утверждения (например зонд требует поведения, которого правило
лестницы дать не может) — **остановись и доложи**: положи в корень клона
`report-blocked.md` с дословной командой, её выводом и тем, какое именно
утверждение спеки опровергнуто. Обходить запрещено: ослаблять зонд, править
`bench/`, глушить код возврата. Остановка по контракту — правильный исход, а не
провал.

## Авторевью (перекрёстное ревью)

Круг «нашли — починили» проходит на ТВОЕЙ квоте, до передачи работы
постановщику. Машинерии `cross-review-v1` и `scripts/review_run.sh` в этом
репозитории НЕТ — не искать их. Порядок:

1. Реализация → свои проверки → коммит. Это REVIEW_SHA; незакоммиченный код
   ревьюерам не показывают.
2. Два НЕЗАВИСИМЫХ ревьюера, оба чужие для Codex, запускаются ПАРАЛЛЕЛЬНО, в
   отдельных вызовах, не показывая друг другу находок:
   - `bash /home/user/.claude/skills/ask-grok/scripts/run.sh result "<контекст>"`
   - `bash /home/user/.claude/skills/ask-agy/scripts/run.sh result "<контекст>"`
     (у `agy` бюджет 900 с — не обрывай его раньше).
   `ask-codex` вторым голосом НЕ считается: сам себя не ревьюит никто.
   Контекст — диапазон `1337140b51482eb9b6d65cc60a406e533b627e4d..REVIEW_SHA`,
   путь клона и суть вехи. Ревьюеры только читают.
3. Дождись ОБОИХ ответов. Обрезанный вход, оборванный ответ или отсутствие
   вердикта — это `incomplete`, а НЕ «находок нет». `agy`, ответивший «находок
   нет», — отсутствие сигнала, а не подтверждение качества.
4. Сведи находки в один список и пройди по нему ОДИН заход исправлений: по
   каждой — `fixed` с воспроизводимым доказательством, `disproved` с
   воспроизводимым опровержением или `needs_owner`. Несогласие само по себе
   находку не закрывает.
5. Второго захода нет. Новый дефект, найденный после него, идёт в отчёт как
   `needs_owner`, а не в ещё один круг.
6. Ответы ревьюеров и решения по находкам положи в `review/` в корне клона
   (untracked, не коммитить) и назови в `note` критерия AC-701.

## Стыки с соседними вехами

- Эта веха обещает следующей: `fetcher(step, budget_ms) -> ProviderReply` —
  единственное место, через которое ядро выходит наружу. Следующая веха приносит
  НАСТОЯЩИЙ fetcher поверх `bench.runner.execute` и HTTP-API поверх `run()`,
  ядро при этом не меняется.
- Веха НЕ добавляет провайдеров и не трогает реестр: отдельной вехой идёт
  `curl` с браузерными заголовками (измеренный в фазе 1 прирост +2 цели из 5,
  которого в коде до сих пор нет) и отдельной — замер Scrapling.
