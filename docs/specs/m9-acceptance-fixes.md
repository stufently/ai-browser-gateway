# M9 — исправления приёмки транспорта

## Где работать

BASE_SHA 08a5da91e68d46998c1f9ae0755aa75bf9d15fe1.
Это продолжение НЕПРИНЯТОЙ M9 тем же исполнителем Grok, без новой монетки.
Клон /home/user/exec-clones/abg-m9-real-fetcher-20260914, ветка m9-real-fetcher.
Не pull, не push/merge/deploy. Spark исчерпан до 20.09.2026 15:59; auto/Spark
не запускать. Последний фактический Grok weekly6%, 5h/reset неизвестны.

## Что проверено вживую, а что предположение

Координатор получил пакет исходной спеки docs/specs/m9-real-fetcher.md,
прочитал полный продуктовый дифф, новые тесты и оба ревью. Исходный SHA
не принят: известные дефекты нельзя перенести в бэклог или скрыть зелёными AC.
Владелец заранее разрешил возвращать дефекты приёмки тому же исполнителю.
Это явное задание координатора на исправления после остановки needs_owner,
а не самовольный второй круг прежнего авторевью.

Сначала сохранить исходные report.json/report-blocked.md (если есть), полный
дифф и результат старого гейта в cache m9/rejected-08a5da9/; квитанции старого
журнала НЕ редактировать, не удалять, результаты не переименовывать в accepted.
Оригинальную спеку и замороженный независимый probe не менять.
Старый гейт также имеет ограничение: needs_owner initial-ссылка затирается
verify-ссылкой того же backend в allowed.update и получается invalid. Это
не основание менять чужую оснастку, удалять находку или выдумывать disproved.
Архивировать точный rc/лог. Новый пакет относится к этой корректирующей спеке
и новому BASE_SHA; старый остаётся свидетельством отклонения.

## Один список исправлений

1. **Unicode framing.** parse_output через str.splitlines ломает единственную
   JSON-строку из json.dumps(ensure_ascii=False), если HTML/text содержит
   U+0085/U+2028/U+2029. Сохранять все символы HTML и text без подмены, корректно
   разбирать однострочный протокол. Старое правило «последняя JSON-строка
   повреждена — отказ, даже если раньше была правильная» сохранить. Добавить
   регрессию, которая берёт реальный payload пробника с ensure_ascii=False,
   проводит его через fetch_page и проверяет точное содержимое всех разделителей.
   Ссылки initial-codex-2.json I-C2-2.
2. **Границы текста.** Убрать склейку на обычном br/hr и границах блоков,
   не разрывать слова на inline b/i/span/em и подобных. Примеры:
   `<p>PAGE<br>_OK</p>` и `PAGE<div>_OK</div>` не содержат PAGE_OK в тексте;
   `<b>PAGE</b>_OK` и `PA<span>GE</span>_OK` содержат PAGE_OK. Учесть br и br/,
   начало и конец блоков. script/style/template по-прежнему исключены,
   сущности и Unicode сохранены. HTML остаётся исходным. Добавить регрессии
   с проверкой фактического текста и решения evaluate, а не только наличия тега.
   Ссылки verify-codex-1.json и verify-agy-2.json первые две находки.
3. **Доказательство очистки.** Сейчас live метит только стенд/оркестратор,
   провайдеры остаются вне учёта. В своём live launcher допустимо добавлять
   run-specific label в argv и вызывать настоящий DockerLauncher. Учесть ВСЕ
   собственные провайдеры и после timeout убедиться, что launcher их удалил,
   ДО аварийного cleanup в finally. Остаток должен делать сценарий красным;
   затем finally всё равно чистит только свои ресурсы. Проверка не должна
   поглощать rc ошибки docker ps или считать пустой stdout доказательством
   успешной проверки. Не сравнивать глобальные списки контейнеров: чужая
   активность не влияет. Ссылки последние находки обоих verification reviewers.
4. **Бюджет живого теста.** В цикле patchright/scrapling сейчас 60000 ms,
   исходная спека допускает максимум30000 на холодный запуск. Вернуть30000,
   сохранить реальное измерение wall time для slow и уверенность, что бюджет
   не просто переклассифицировали после произвольного ожидания. Контейнерный
   overhead учитывать разумным фиксированным допуском в тесте, не увеличением
   бюджета провайдера. Уникальный маркер дополнить Unicode, проверить реальные
   разделители из пункта1 в живом curl; browser может нормализовать DOM,
   поэтому не требовать совпадения source HTML с сериализацией браузера.
5. **Отчёт без ложного опровержения.** Отсутствующий профиль действительно
   выдаёт not_measured по M9, и M7 engine на нём не умеет продолжать. Это
   ограничение согласованного транспортного контракта, не исправлять engine
   в этой вехе. Явно указать в README, что имена profiles/entrances обязаны
   соответствовать GatewayRequest; mismatch ещё не безопасный продуктовый
   запрос. Координатор закроет это в продуктовой лестнице следующей вехи.
   Другие перечисленные подтверждённые дефекты исправить сейчас, не disproved.

## Не трогать

Разрешено менять только probe.py, registry.py (минимальная совместимая правка
framing/argv), runner/fetch.py, runner/execute.py при необходимости конкретного
дефекта, gateway/fetch.py, новые test_gateway_fetch.py/test_fetch_protocol.py/
live_m9_fetch.py, README.md и эту спеку. Старые тесты, независимый probe,
M7 engine/models/plan, bench/models/escalate, измерения, TASKS/CHANGELOG,
образы/теги и чужую оснастку не менять. Координатор не пишет код или тесты.

Независимые мутации пишет cx в отдельном клоне; сейчас он проверяет BASE_SHA.
Его результат /home/user/.cache/abg-coord-20260914/m9/mutations-cx/mutation-result.md.
Если до фикса REVIEW_SHA появятся содержательные survived, вернуть координатору
точные причины и включить подтверждённые недостающие тесты в этот заход.
Автор кода не подменяет независимого автора мутаций. После пакета cx повторит
harness на FINAL_SHA, Grok добавит готовые доказательства в комплект.

## Критерии приёмки

Все тесты и продуктовый Python в Docker UID1002:1002; host Python только для
оркестрации Docker. Без sudo, секретов/.env, установок на хост и экспериментов
с host tmux/сигналами. Live чистит только свои контейнеры. Не дублировать
старые мутации в ходе правки: полный нужный прогон сделает гейт один раз.

- **AC-901.** Полный suite:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-902.** Независимый probe неизменен и зелёный:
  `bash -c 'echo "4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190  tests/probe_m9_transport.py" | sha256sum -c - && docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m tests.probe_m9_transport'`
- **AC-903.** Реальные провайдеры, Unicode, бюджет и очистка:
  `bash -c 'python3 tests/live_m9_fetch.py'`
- **AC-904.** Исторические мутации:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py'`
- **AC-905.** Исторические инварианты всей M9:
  `bash -c 'git diff --exit-code 72b7ce87713a8c12d0620704b598d8a9b6f3e215 HEAD -- gateway/engine.py gateway/models.py gateway/plan.py bench/models.py bench/escalate.py docs/research TASKS.md CHANGELOG.md'`
- **AC-906.** Файлы и чистое дерево:
  `bash -c 'git ls-files --error-unmatch gateway/fetch.py tests/test_gateway_fetch.py tests/live_m9_fetch.py tests/probe_m9_transport.py docs/specs/m9-real-fetcher.md docs/specs/m9-acceptance-fixes.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md" ":(exclude)review/")"'`

## Контракт отчёта

Коммитить эту спеку неизменной. report.json: schema_version=2,
policy_id=cross-review-v1, spec_sha256 этой спеки,
base_sha/reviewed_sha/final_sha, executor grok, six criteria посимвольно как выше,
initial_receipts/verification_receipts/resolutions, handoff_status.
Новый review journal по BASE_SHA этой спеки. Старые валидные ревью полного
диффа сохраняются; новые ревью охватывают ТОЛЬКО исправления BASE..REVIEW.
Исполнитель сам параллельно запускает Codex result и ask-agy Gemini через
/home/user/gitlab/9qw/tg-claude-userbot/scripts/review_run.sh.
ASK_MAX_FINDINGS=12, AGY_MODEL=gemini-3.8-flash-high AGY_TIMEOUT=900.
Ревьюеры только читают, без изменения дерева и своих фоновых live/mutation
прогонов. Обоим одинаковый контекст: старые находки, эти требования, проверить
дифф исправлений и связанные риски. Оборванный/усечённый ответ — incomplete;
один технический retry, quota не циклировать. При находках один fix round и
parallel verification; если код неизменен — verification не запускать.
Новая неразрешённая находка после verification — честный needs_owner.

Гейт исполнителя:
`python3 /home/user/gitlab/9qw/tg-claude-userbot/scripts/accept_run.py /home/user/exec-clones/abg-m9-real-fetcher-20260914 --spec /home/user/exec-clones/abg-m9-real-fetcher-20260914/docs/specs/m9-acceptance-fixes.md --timeout 3600`.
Артефакты в /home/user/.cache/abg-coord-20260914/m9/corrections/:
полный итоговый diff 72b7ce8..FINAL, отдельный diff исправлений, команды/cwd/rc,
SHA и логи AC, копии/ссылки квитанций, разбор всех пунктов, SHA256SUMS.
Координатор проверит изменения и связанные риски, запустит собственный гейт
и получит независимые мутации cx на том же FINAL_SHA. До этого нет приёмки
M9 или push.

## Контракт на невыполнимое

При противоречии или отсутствующем ресурсе — report-blocked.md с командой,
cwd, rc и точной безопасной уликой. Критерии не ослаблять, числа не выдумывать,
не скрывать ошибки. Остальной разрешённый флоу сохраняется.
