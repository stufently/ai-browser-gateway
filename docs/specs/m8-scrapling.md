# Веха M8 — Scrapling: измерить, добавляет ли он хоть одну цель

| | |
|---|---|
| Репозиторий | `ai-browser-gateway` (`git@github.com:stufently/ai-browser-gateway.git`) |
| Дата | 14.09.2026 |
| BASE_SHA | `1337140b51482eb9b6d65cc60a406e533b627e4d` («Ignore executor scratch dirs») — коммит, С КОТОРОГО СНЯТ КЛОН |
| Клон | `/home/user/exec-clones/abg-m8-scrapling`, ветка `m8-scrapling` от `main` |
| Исполнитель | **Grok (`gk`)** — у вехи сетевые и Docker-критерии, это его профиль |
| Ревью | два независимых на квоте исполнителя (раздел «Авторевью») |
| Критериев | 7 |

## Где работать

- Клон `/home/user/exec-clones/abg-m8-scrapling`, ветка `m8-scrapling`.
- **Живое дерево `/home/user/github/ai-browser-gateway` не трогать.**
- **`git push` запрещён, включая `origin`.** Работу заберёт постановщик:
  `git -C /home/user/github/ai-browser-gateway fetch <клон> m8-scrapling:m8-scrapling`.
  `git add` — по именам файлов, никогда `-A`.
- Docker на хосте есть, контейнеры запускай под `1002:1002` (это уже делает
  `bench.providers.registry.build_argv`). Пакеты на ХОСТ не ставить: всё, что
  нужно Scrapling'у, живёт внутри образа.
- Сеть есть. Правило нагрузки из `bench/targets/targets.toml` соблюдается
  строго: один запрос на пару «провайдер × цель», пауза к одному хосту не
  меньше 30 с, в том числе после отказа.
- Спека `docs/specs/m8-scrapling.md` приезжает в клон untracked — её надо
  **закоммитить вместе с работой** (`git add docs/specs/m8-scrapling.md`), не
  редактируя текст.

## Задача и почему

Владелец прислал рилс и спросил, можно ли что-то из него применить у нас. Рилс
опознан: это **Scrapling** (автор `zhilnikov_it`, 11.09.2026). Разведка Codex'ом
14.09.2026 дала ровно одно предметное отличие от того, что у нас уже измерено:

> у Scrapling есть **обработчик челленджа Cloudflare поверх Patchright** —
> `if params.solve_cloudflare: self._cloudflare_solver(page)`: он ждёт
> завершения проверки и нажимает checkbox.

Наш собственный пробник этого не умеет — он только открывает страницу. Всё
остальное в рилсе к обходу блокировок отношения не имеет: «в 700 раз быстрее» —
это авторский бенчмарк ПАРСЕРА (1,99 мс против 1562 мс у BS4 на 5000 вложенных
элементах), а HTTP-движок Scrapling'а — это `curl_cffi`, который мы уже мерили и
получили **incremental 0**.

Поэтому веха не «внедряет Scrapling», а **измеряет ровно одну гипотезу**:

> Добавляет ли Scrapling с включённым `solve_cloudflare` хотя бы ОДНУ цель,
> которую не берёт `patchright` — тот самый Chrome, поверх которого Scrapling и
> работает?

Ответ «не добавил» — полноценный результат вехи, а не провал. Именно так фаза 1
закрыла `curl_cffi` и `primp`.

### Вторая половина вехи: живая цель со стеной логина

Строка `login-instagram` в `bench/targets/targets.toml` помечена `valid = false`
с 06.09.2026: id поста был подставлен наугад и оказался мёртвым. Владелец
прислал живую ссылку, и постановщик её замерил (числа ниже — измеренные, не
предположение). Веха возвращает строку в строй.

## Что проверено вживую, а что предположение

- **Scrapling 0.4.15, выложен 23.08.2026, `requires-python >=3.10`.** Проверено
  `curl -fsSL https://pypi.org/pypi/scrapling/json` + `jq` 14.09.2026. Пин в
  Dockerfile — ровно `scrapling==0.4.15`.
- **Живой рилс отдаёт подпись только браузеру.** Замерено 14.09.2026 с этого же
  хоста по адресу `https://www.instagram.com/reel/DdJ-MY6OITt/`:
  - `curl -sL` → HTTP 200, 675 468 байт, `<title>Instagram</title>`,
    подстроки `Кирилл Жильников` в теле **0 вхождений**;
  - headless Chromium со stealth (`~/.claude/skills/cf-fetch/fetch.sh`) → 200,
    1 138 260 байт, `og:title` = `Кирилл Жильников on Instagram: "…"`,
    подстрока `Кирилл Жильников` — **3 вхождения**.
  Значит цель РАЗЛИЧАЕТ провайдеров, и `expect = "Кирилл Жильников on Instagram"`
  на странице-заглушке не встречается. Это первая цель набора, где браузер
  может обойти HTTP-клиент.
  ⚠️ Честная оговорка, которую надо записать в `note` цели: так измеряется
  доступ к ПОДПИСИ и мета-разметке, а не к самому видео — видео остаётся за
  стеной логина, и эта строка его не меряет.
- `bench/providers/registry.py`: `Provider(name, image, tier, kind,
  needs_network, argv_extra)`, `kind ∈ {'http','browser','entrance'}`;
  `build_argv` уже добавляет `--user 1002:1002` и `--shm-size=1g` для
  `kind == 'browser'`. **Проверено чтением файла.**
- Образы собираются из каталога `bench/providers/docker` и выбирают адаптер по
  `ABG_PROVIDER`; интерфейс пробника — `probe.py URL SENTINEL [--mode cold|warm]`,
  на stdout последняя строка с `{` — нормализованный JSON. **Проверено**
  (`docs/m2-runner-usage.md`, `Dockerfile.patchright`).
- `Dockerfile.patchright` ставит `patchright==1.62.3`, тянет настоящий Chrome и
  запускается под `xvfb-run` через `tini`. **Проверено чтением файла.**
- **Предположение:** Scrapling соберётся в образ того же класса, что patchright
  (python-slim + Chrome через patchright). Если его зависимости этого не
  позволяют — это находка, а не повод чинить силой: остановись и доложи.
- **Предположение:** `solve_cloudflare` на наших целях вообще сработает. Ни у
  автора, ни у нас чисел нет; на `cf-bizprofile` его может не хватить так же,
  как не хватило всем пяти движкам.

## Что сделать

### 1. Провайдер `scrapling`

- `bench/providers/docker/Dockerfile.scrapling` по образцу `Dockerfile.patchright`:
  пин `scrapling==0.4.15`, браузер ставится штатной командой Scrapling'а или
  patchright'а, `ENV ABG_PROVIDER=scrapling`, тот же `tini` + `xvfb-run`.
- Адаптер `ScraplingAdapter` в `bench/providers/docker/probe.py` рядом с
  соседями: `start()` поднимает движок, `navigate(url)` идёт на страницу **с
  включённым `solve_cloudflare`**, `close()` гасит. Возвращает тот же
  нормализованный ответ через `_result(...)`, что и остальные адаптеры, включая
  `headers`, когда они доступны.
- Строка в `PROVIDERS`: `Provider('scrapling', 'abg-scrapling:m8', 2, 'browser', True)`.
- Тесты на поддельном движке по образцу существующих в `tests/test_probe.py`
  (сам Scrapling на хосте не ставится): проверяют, что адаптер запрашивает
  решение челленджа, что отказ движка превращается в `provider_error`, а не в
  исключение наружу, и что версия пакета попадает в ответ.

### 2. Живая цель со стеной логина

В `bench/targets/targets.toml` заменить строку `login-instagram`:

- `url = "https://www.instagram.com/reel/DdJ-MY6OITt/"`
- снять `valid = false`;
- `expect = "Кирилл Жильников on Instagram"`;
- `note` — измеренные числа из раздела выше и оговорка про видео за стеной.

### 3. Замер

Прогнать `scrapling`, `patchright` и `curl` по действительным целям файла
и положить результат в `docs/research/data/m8-scrapling.jsonl`, отчёт — в
`docs/research/05-scrapling.md` (строится `python3 -m bench report`). В отчёте:

- таблица «провайдер × цель» с временем и пиковым RSS;
- incremental coverage, посчитанный БОЕВЫМ кодом (`bench.report.coverage`), а не
  руками;
- прямой ответ на вопрос вехи: добавил ли `scrapling` хоть одну цель к
  `patchright`, и если нет — так и написать;
- размер образа и пиковый RSS против patchright (у того в замере раннера пик
  1773 МиБ) — это цена, за которую платим;
- оговорка про один egress: у нас по-прежнему один адрес,
  `AS206996 ZAP-Hosting`, и «инструмент не справился» от «адрес не пустили»
  неотличимо.

### 4. Документация

`CHANGELOG.md` — запись 14.09.2026. `TASKS.md` — веха в `DONE`; пункт
«Живой URL рилса для цели login-instagram» из раздела «За владельцем» **удалить**
(он закрыт этой вехой). `README.md` — строку про `scrapling` в таблицу стека
только если замер это подтвердил.

## Не трогать

- `bench/models.py`, `bench/escalate.py`, `bench/report/**`, `bench/runner/**` —
  контракт вех M1–M6. Правило успеха и таксономия отказов не меняются.
- Адаптеры соседних провайдеров в `probe.py` — добавляешь свой, чужие не трогаешь.
- `docs/research/01-…`–`04-…` — измеренные числа прошлых прогонов не переписывать.
- Пакет `gateway/`, если он появится в дереве: его пишет соседняя веха.
- Эта спека — коммитится, но не редактируется.

## Критерии приёмки

- **AC-801.** Образ собирается:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && docker build -f bench/providers/docker/Dockerfile.scrapling -t abg-scrapling:m8 bench/providers/docker'`
- **AC-802.** Пробник в образе отвечает контрактом на ЛОКАЛЬНОМ стенде A, без
  внешней сети. Проверку пишешь ты сам, файлом `tests/stand_a_scrapling_check.py`:
  он поднимает стенд A своим процессом, прогоняет сценарии `static` и `js`,
  печатает обе записи и возвращает 0 только если обе успешны:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && python3 tests/stand_a_scrapling_check.py'`
- **AC-803.** Полный корпус зелёный:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && python3 -m unittest discover -q -s tests -t .'`
- **AC-804.** Мутационный гейт вехи: не меньше трёх мутаций по НОВОМУ коду,
  каждая убита своим тестом на своей строке ассерта, файлы восстановлены:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && python3 tests/mutation_gate_scrapling.py'`
- **AC-805.** Замер настоящий: в JSONL есть запись для КАЖДОЙ действительной
  цели по каждому из трёх провайдеров, ни одной записи с `not_measured`:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && python3 -c "
import json, pathlib, tomllib
raw = tomllib.loads(pathlib.Path(\"bench/targets/targets.toml\").read_text(encoding=\"utf-8\"))
targets = {t[\"id\"] for t in raw[\"target\"] if t.get(\"valid\", True)}
records = [json.loads(line) for line in pathlib.Path(\"docs/research/data/m8-scrapling.jsonl\").read_text(encoding=\"utf-8\").splitlines() if line.strip()]
seen = {(r[\"provider\"], r[\"target\"]) for r in records if r.get(\"target\")}
missing = [(p, t) for p in (\"scrapling\", \"patchright\", \"curl\") for t in targets if (p, t) not in seen]
assert not missing, missing
stub = [r for r in records if r[\"error_type\"] == \"not_measured\"]
assert not stub, stub
"'`
- **AC-806.** Цель со стеной логина действительна и с проверенным ожиданием:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && python3 -c "
import pathlib, tomllib
raw = tomllib.loads(pathlib.Path(\"bench/targets/targets.toml\").read_text(encoding=\"utf-8\"))
row = [t for t in raw[\"target\"] if t[\"id\"] == \"login-instagram\"][0]
assert row.get(\"valid\", True) is True, row
assert \"DdJ-MY6OITt\" in row[\"url\"], row[\"url\"]
assert row[\"expect\"] == \"Кирилл Жильников on Instagram\", row[\"expect\"]
"'`
- **AC-807.** Состав работы на месте, дерево чистое:
  `bash -c 'cd /home/user/exec-clones/abg-m8-scrapling && git ls-files --error-unmatch bench/providers/docker/Dockerfile.scrapling docs/research/05-scrapling.md docs/research/data/m8-scrapling.jsonl tests/mutation_gate_scrapling.py tests/stand_a_scrapling_check.py docs/specs/m8-scrapling.md > /dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

## Контракт отчёта

`report.json` в КОРНЕ клона, untracked, записей ровно семь — `AC-801…AC-807`:

```json
{"criteria": [{"id": "AC-801", "status": "pass|fail|blocked",
               "command": "<команда ИЗ ЭТОЙ СПЕКИ, посимвольно>", "rc": 0, "note": "…"}]}
```

`blocked` — штатный исход, когда среда не даёт выполнить критерий (нет Docker,
цель недоступна): `"rc": null` и дословная ошибка в `note`. Обходить
несовместимость ЗАПРЕЩЕНО: `--no-deps`, `--break-system-packages`, `|| true`,
`set +e` в самой команде критерия, `sudo`, `git push`. Хвостовой `echo` после `;`
запрещён — он обнуляет код возврата.

## Контракт на невыполнимое

Scrapling не ставится в образ, требует ключа платного сервиса, не запускается
под `xvfb`, или его API не даёт включить `solve_cloudflare` — **остановись и
доложи**: `report-blocked.md` в корне клона с дословной командой, выводом и тем,
какое утверждение спеки опровергнуто. Подменять его `curl_cffi`-движком, чтобы
«хоть что-то померить», ЗАПРЕЩЕНО: это была бы уже измеренная вещь под новым
именем. Цель не отвечает или отдаёт челлендж — это РЕЗУЛЬТАТ замера, его надо
записать, а не обходить.

## Авторевью (перекрёстное ревью)

Круг «нашли — починили» проходит на твоей квоте, до передачи работы. Машинерии
`cross-review-v1` и `scripts/review_run.sh` в этом репозитории НЕТ.

1. Реализация → свои проверки → коммит (REVIEW_SHA). Незакоммиченный код
   ревьюерам не показывают.
2. Два независимых ревьюера, оба чужие для Grok, ПАРАЛЛЕЛЬНО и в отдельных
   вызовах: `bash /home/user/.claude/skills/ask-codex/scripts/run.sh result "<контекст>"`
   и `bash /home/user/.claude/skills/ask-agy/scripts/run.sh result "<контекст>"`
   (у `agy` бюджет 900 с, раньше не обрывать). Контекст — диапазон
   `1337140b51482eb9b6d65cc60a406e533b627e4d..REVIEW_SHA`, путь клона и суть
   вехи. Ревьюеры только читают.
3. Обрезанный вход, оборванный ответ или отсутствие вердикта — `incomplete`, а
   не «находок нет». «Находок нет» у `agy` — отсутствие сигнала.
4. Один заход исправлений по сведённому списку: `fixed` с доказательством,
   `disproved` с опровержением или `needs_owner`. Второго захода нет.
5. Ответы ревьюеров и решения по находкам — в `review/` в корне клона
   (untracked, не коммитить), имена файлов назвать в `note` критерия AC-803.

## Стыки с соседними вехами

- Соседняя веха пишет пакет `gateway/` (ядро лестницы) и `bench/` не трогает —
  пересечения по файлам быть не должно, кроме `CHANGELOG.md` и `TASKS.md`.
- Если замер подтвердит прирост, следующая веха добавит `scrapling` ступенью в
  лестницу ядра. Если не подтвердит — провайдер остаётся в бенчмарке как
  измеренный кандидат и в стек не идёт, как `curl_cffi` и `primp`.
