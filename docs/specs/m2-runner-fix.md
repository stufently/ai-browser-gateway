# Веха M2, заход исправлений — дыры в тестах и один артефакт в диффе

| | |
|---|---|
| Репозиторий | `ai-browser-gateway`, клон `/home/user/exec-clones/abg-m2-runner` |
| Ветка | `m2-runner`, работа в коммите `62c549e` |
| Дата | 06.09.2026 |
| Исполнитель | **Codex** — автор вехи, чинит свою работу |
| Основание | мутационный прогон противоположного исполнителя (Grok) |

Машинный гейт прошёл 8/8. Образы я собрал сам, все семь; раннер прогнан вживую
против стенда A и воспроизвёл ожидаемое — `curl`, `curl_cffi` и `primp` берут по
5 сценариев из 12, отчёт строится, incremental coverage считается.

**Ревью Grok по коду: принято, находок нет.** Дефектов в боевом коде не нашли ни
он, ни я. Но мутационный прогон по твоим тестам дал **шесть выживших мутантов** —
это дыры в ТЕСТАХ, и закрыть их надо. Заход единственный.

## Где работать

- Клон тот же, ветка та же, работа уже там.
- **Живое дерево `/home/user/gitlab/9qw/ai-browser-gateway` не трогать.**
- Постановщик кладёт только эту спеку (`docs/specs/m2-runner-fix.md`, untracked).
- Исправления — НОВЫМ коммитом поверх `62c549e`. `git commit --amend` запрещён.

## Что закрыть: шесть выживших мутантов

Каждому нужен тест, который его убивает, и сама мутация в `tests/mutation_gate.py`.

| # | Файл | Что выжило | Чего не хватает |
|---|---|---|---|
| 1 | `runner/execute.py` | `network = 'host'` **всегда**, включая `target:` | Никто не проверяет, что боевым целям `--network` НЕ передаётся. Тест `test_modes_and_local_network` утверждает только обратное направление |
| 2 | `runner/execute.py` | удалён `docker rm --force` по cidfile при таймауте | `DockerLauncher` не покрыт вовсе |
| 3 | `report/build.py` | `threshold=threshold` заменён константой | Нет теста, что порог реально доезжает до `coverage`/`render` |
| 4 | `runner/execute.py` | снята проверка `mode in ('cold','warm')` | Нет теста на мусорный `mode` в готовом плане |
| 5 | `runner/execute.py` | удалена ветка `timeout <= 0` | Нет теста, что неположительный таймаут отвергается ДО запуска |
| 6 | `runner/execute.py` | снята проверка уникальности `run_id` | Нет теста на дубликаты в плане, собранном в обход `build_plan` |

Мутант №1 — самый существенный и не косметический: при нём **чужие сайты уедут в
host-сеть контейнера**. Тест обязан проверять именно отсутствие `--network` в
argv для ячейки `target:`, а не наличие для `scenario:`.

Мутант №2 закрывается тестом на `DockerLauncher` с поддельным `subprocess.run`:
на `TimeoutExpired` обвязка обязана прочитать cidfile и позвать
`docker rm --force <cid>`. Настоящий Docker для этого не нужен и не должен
использоваться — у тебя его нет.

## Что убрать из диффа

`docs/superpowers/plans/2026-09-06-m2-runner.md` — артефакт твоего собственного
скила планирования, а не работа по вехе, и он нарушает раздел «Не трогать»
исходной спеки. Удали файл из индекса и с диска, а каталог `docs/superpowers/`
добавь в `.gitignore`, чтобы он больше не попадал в коммиты.

`docs/m2-runner-usage.md` **оставь** — формально он тоже вне разрешённого, но по
делу это описание того, как раннером пользоваться, и оно полезно. Считай его
согласованным задним числом.

## Не трогать

- Боевой код `bench/` — правок по коду нет, ревью его приняло. Меняешь код ради
  теста — **остановись и доложи**: значит тест требует не того.
- Контракты M1: `bench/models.py`, `bench/scenarios.py`, `bench/server/`,
  `bench/report/coverage.py`, `bench/report/render.py`, `bench/runner/record.py`.
- Существующие 131 тест и 23 мутации — не удалять и не ослаблять.
- `README.md`, `TASKS.md`, `CHANGELOG.md`, `docs/research/`, `tests/fixtures/`,
  `bench/targets/targets.toml`.
- `docs/specs/m2-runner-fix.md` — исключение: приезжает untracked и **коммитится
  вместе с исправлениями**.
- Сторонних зависимостей по-прежнему ноль.

## Критерии приёмки

- **AC-301 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -m unittest discover -s tests -t . -q'`

- **AC-302 — мутационный гейт: не меньше 29 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=29 else 1)" && python3 tests/mutation_gate.py'`

- **AC-303 — боевая цель не уезжает в host-сеть.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && python3 -c "
from bench.providers.registry import by_name
from bench.runner.matrix import build_plan
from bench.runner.execute import execute_plan
seen = []
class Spy:
    def run(self, argv, timeout):
        seen.append(list(argv))
        return (0, \"\", \"\")
cells = {\"target:t\": {\"url\": \"https://example.com/\", \"sentinel\": \"S\"},
         \"scenario:s\": {\"url\": \"http://127.0.0.1:1/x\", \"sentinel\": \"S\"}}
plan = build_plan([by_name(\"curl\")], [\"target:t\", \"scenario:s\"], cold=1, warm=0)
execute_plan(plan, launcher=Spy(), cells=cells, env={}, sleep=lambda s: None)
target_argv = [a for a in seen if \"https://example.com/\" in a][0]
scenario_argv = [a for a in seen if \"http://127.0.0.1:1/x\" in a][0]
assert \"--network\" not in target_argv, target_argv
assert \"--network\" in scenario_argv, scenario_argv
"'`

- **AC-304 — артефакт скила убран и заигнорирован.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && test ! -e docs/superpowers && ! git ls-files --error-unmatch docs/superpowers/plans/2026-09-06-m2-runner.md >/dev/null 2>&1 && grep -q "docs/superpowers" .gitignore'`

- **AC-305 — состав работы.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && git ls-files --error-unmatch docs/specs/m2-runner-fix.md tests/mutation_gate.py tests/test_execute.py tests/test_report_build.py >/dev/null'`

- **AC-306 — дерево чистое.**
  `bash -c 'cd /home/user/exec-clones/abg-m2-runner && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

Перезапиши `report.json` в корне клона, записей ровно шесть:

```json
{"criteria": [{"id": "AC-301", "status": "pass|fail|blocked",
               "command": "<команда-доказательство>", "rc": 0, "note": "…"}]}
```

🚨 Строку `command` копируй из спеки **дословно**, не перекавычивая: в вехе M1
исполнитель на этом уронил исправный критерий с `rc=127`.

## Контракт на невыполнимое

Требование невыполнимо или требует правки боевого кода — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест, удаление
неудобного теста.

Если считаешь какую-то из шести мутаций **эквивалентной** — то есть по
наблюдаемому поведению неотличимой от исходного кода, — исключи её с ПИСЬМЕННЫМ
обоснованием, почему поведение не меняется. «Не смог убить» обоснованием не
является. Настоящий Docker для тестов не поднимай: его у тебя нет, и он не нужен.
