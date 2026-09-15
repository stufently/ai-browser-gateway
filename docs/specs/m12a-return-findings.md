# M12a — возврат после verify

15.09.2026. Это список для следующей execution-спеки, не разрешение менять
завершённый клон M12a. Новая веха и новый клон от FINAL
`62de539f586b95e6aeb971c3ab1f51e6f7080260`, тот же Grok по правилу квот.
M12a в main не влита и в origin не опубликована. M12b ждёт исправления.

## Проверенный пакет

Пакет /home/user/.cache/abg-coord-20260915/m12/author/.
BASE `7ca38c1aa62174a0a1de1a7685fee268c2ba2042`, REVIEW
`53ca5f95babb157885bb44d0ae0a428360aa6704`, FINAL выше.
Полный diff102853bytes совпал с git diff --binary --full-index BASE..FINAL.
Координатор прочитал весь новый код, tests/live и delta существующих файлов;
неизменные execution-spec/contract/frozenprobe сверены по git-объектам и SHA.
Все четыре выбранных review inputs совпали с соответствующими git ranges,
input/response hashes и размеры совпали, truncation=false, rc0, verdict parsed.
Initial Codex:7findings; initial Gemini:принято; оба verify:не принимать,
по одной находке про shutdown. Valid reviews неизменного кода не повторять.

46 хешей артефактов совпали. В SHA256SUMS есть некорректная самоссылка
./SHA256SUMS; она исключена из числа проверенных данных, исходник сохранён.
Корневой manifest SHA256:
6831fe0450fc1bd47947ff9f8fbe9c5fc53e77b6ab377ff6d763ee0ecb5ba164.
report SHA256:
6f476f6ea3552978ef539fec8f29787c6d14901749ae24684c5920901d005328.
Локальный полный bundle m12/m12a-unaccepted-final.bundle проверен, SHA256
7e57add97a0c68a99855564620fafd4fd8dce4616c90caefe5ceccb9cd48d169.
Публикация непринятого кода этим не подменяется.

Автор сохранил шесть AC command/cwd/rc и логи с rc0:419unit,114frozen probes,
локальный live. report handoff_status=needs_owner. Эти результаты не закрывают
найденные дефекты; coordinator gate/suite заново на заведомо непринятом пакете
не запускался. Текущий Grok-run завершён как blocked, его idle-панель закрыта.

## Единый список известных исправлений

1. **Shutdown race, оба verify F001.** service.main запускает server.shutdown
   в helper thread, затем server_close и два sweep с паузой0.2. Handler threads
   daemon, ожидание browser semaphore не отменяется. После удаления активного
   provider ожидающий обработчик может начать следующий запуск за последней
   уборкой. Нужен корректный допуск/завершение запросов и запусков с конечным
   временем shutdown, без ослабления owner+instance+role scope и M11 default.
   Проверять также уже допущенный, но задержанный запуск, не только новую HTTP
   сессию после shutdown. Конкретную реализацию выбирает Grok, frozen regression
   probe готовит противоположный исполнитель.
2. **Initial Codex F006 остаётся незакрытым.** live создаёт Compose-monitor с
   https://example.invalid/m12-ping. В нём вручную исполняется check_once, а
   автоматические success/fail получает отдельный subprocess из checkout в
   контейнере с host network/socket/token. Это не доказательство цикла sidecar
   принятого release. Проверять автоматический цикл реального Compose-monitor
   на своём receiver, в требуемой изоляции и с его release; без ручного ping
   вместо цикла. Независимая подготовка проверит обход с пассивной Cmd sidecar.
3. **Proxy whitespace/control.** _proxy принимает URL с U+00A0 и U+0085;
   компонентная Docker1002 проверка дала accepted=true для обоих. Исходный
   контракт запрещает whitespace/control. Независимый probe подтвердит отказ
   через make_service до bind; сохраняются допустимые HTTP(S)/userinfo/порт.
   Улика m12/coordinator-proxy-check.json в cache выше.
4. **Symlink manifest file.** manifest() проверяет symlink каталога manifests,
   но принимает существующий symlink manifests/<sha>.sha256 как готовый файл.
   Docker-проверка: accepted=true, symlink сохранён, внешний target не изменён.
   Нужен отказ по исходному no-symlink контракту; независимый probe проверит
   prepare CLI и обычный повтор. Улика m12/coordinator-manifest-check.json.
5. **Авторские tests.** Добавлены только6methods: launcher labels, sweep argv,
   строки Dockerfile/Compose, URL helper, один provision и один release case.
   Обязательные unit-проверки service config, rotation concurrency/copies,
   health-result/loop/redaction не представлены этими авторскими methods.
   Frozenprobe не заменяет независимую проверку качества авторских tests.
   Точный список дополнительных дыр будет взят из ожидаемых чужих мутаций.
6. **Оставшиеся live-доказательства контракта.** Текущий script проверяет часть
   API metadata, но не полный фактический user/group/RO/loopback/mount набор
   API, sidecar и providers. Проверка health после sleep0.5 не доказывает
   занятость browser-slot. Proxy counter проверяет any hit, а не отдельный
   фактический egress каждого из двух запросов. Дополнить наблюдения по этим
   конкретным рискам; старые M9–M11 suites не дублировать.

## Следующий шаг

docs/specs/m12a-shutdown-probes.md — подготовленная независимая задача cx на
неизменном FINAL: до24unit-мутаций, один live-обход и новый frozen probe с двумя
разными корректными эталонами/обходами. Клон уже создан, реализации исправлений
нет. После её принятия зафиксировать execution-спеку новой вехи от FINAL,
предполёт/BASE-команды, Grok, оба review, один fix/verify, независимая приёмка.
В новом report разрешить каждую finding_id обоих reviewers, включая одинаковые
по сути находки; не ограничиваться ID только Codex. Manifest без самоссылок.

Контракт M12a и прежние frozen probes неизменны. Никакого изменения оснастки,
ядра/transport, production credentials, внешних целей или чужих сервисов.
