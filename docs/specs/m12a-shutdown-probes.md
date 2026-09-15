# M12a — независимые мутации и probe регрессий

15.09.2026. Подготовительная задача противоположному cx, не реализация продукта.
Клон /home/user/exec-clones/abg-m12a-shutdown-probes-20260915,
ветка m12a-shutdown-probes, push DISABLED.
BASE_SHA `62de539f586b95e6aeb971c3ab1f51e6f7080260` — FINAL Grok M12a.
M12a НЕ принята: verify-codex нашёл поздний запуск provider после уборки.
Владелец разрешил продолжать все задачи; после verify исправления пойдут
новой вехой от этого FINAL, основной код здесь не править.

## Две части одного независимого пакета

### 1. Мутации новых авторских unit-tests на неизменном FINAL

Прочитать весь docs/specs/m12a-service-contract.md, gateway/service.py,
health_monitor.py, httpapi.py/api_http.py, scripts/abg-release/abg-provision
и четыре новых tests/test_{service,health_monitor,provision,release}.py.
Шесть новых test methods — авторский набор, не старые413unit и не frozenprobe.
Сначала green именно этой команды в Docker1002:1002:

`docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_service tests.test_health_monitor tests.test_provision tests.test_release`

Смысловые мутации только в отдельных копиях файлов под private package root.
Не менять исходный продукт/авторские tests в клоне и не добавлять туда фиксы.
До24 целевых вариантов, по одному изменению за раз. Не раздувать одинаковыми
вариантами: цель — проверяемые свойства и конкретные пробелы, не число kills.

Обязательные оси: label owner/instance/role/request, argv/env/timeout;
cleanup filters/bounds; make_service file permissions/token/profiles и
opt-in rotation/copies; health-result/redirect/timeout/ping-failure/redaction;
provision password encoding/count15/no-overwrite/atomicity/source rejection;
release file+directory modes/symlink/mismatch. Подбирать конкретные изменения
по прочитанному коду. Нет вызова изменённого поведения авторскими tests —
честный survivor/непокрытый контракт, не invalid и не выдуманный kill.

Зафиксировать каждый mutation id, sourceSHA/diff/активацию, command/cwd/rc,
полный log, failing test и assertion line, restoreSHA. Syntax/import/fixture
error не kill. Падение frozenprobe/старыхtests не считать авторским kill.
Эквивалентные и invalid отдельно. Исходные tests не ослаблять и не чинить.
В конце восстановленный green, source HEAD и дерево unchanged.

Отдельно один обязательный live-мутант: заменить команду Compose-monitor
на пассивный процесс, оставив рабочими image/env и docker exec. BASE live
сейчас проверяет автоматические пинги через дополнительный monitor из checkout,
а в настоящем sidecar вручную вызывает check_once. Покажи, проходит ли
существующий tests/live_m12_service.py при выключенном sidecar loop. Нужны
baseline, доказательство реальной Cmd/Image/mount активации мутанта, rc/log,
restore. Внешние цели не нужны; свои локальные Dockerресурсы и finally cleanup.
Не засчитывать проверку из checkout как проверку Compose release.

### 2. Новый frozen regression probe для следующей вехи

Единственный разрешённый tracked новый файл: tests/probe_m12_service_regressions.py.
Он описывает НАБЛЮДАЕМОЕ устранение verify-codex-1:F001:

> При SIGTERM обработчик, ожидающий browser semaphore, может продолжить
> лестницу и запустить provider после последнего sweep. Два sweep и sleep0.2
> не закрывают гонку. Нельзя оставлять provider этой установки после остановки.

Требования следующей вехи остаются прежним контрактом, не новым API:
- остановка закрывает допуск новых provider launch этой установки;
- уже допущенный запуск не должен создавать позднего сироту после уборки;
- ожидающий browser-slot запрос после начала shutdown не запускает provider;
- shutdown ограничен по времени, свои существующие providers убраны;
- другой owner/instance/role и foreign-labeled контроль сохранены;
- обычные запросы до shutdown, timeout/env/argv/labels и default M11 работают.

Прочитать фактическую цепочку semaphore/fetch/launcher, не угадывать швы.
Пробник воспроизводит гонку детерминированно через управляемые барьеры и
наблюдение launch/remove; один произвольный sleep без доказанной активации
не подходит. Не требовать придуманное имя нового private helper/атрибута.
Допустимы существующие публичные make_service/HTTP/entrypoint и наблюдаемые
границы DockerLauncher/subprocess; заменять их фейками только внутри Docker.
Все эксперименты с сигналами/процессами исключительно ВНУТРИ Docker с фейками.
Host tmux socket, kill-server, сигналы в чужие процессы запрещены. Для проверки
SIGTERM адресовать конкретный собственный процесс внутри тестового контейнера.

Дополнительно подтвердить через CLI/публичный make_service и включить в тот
же probe ещё два обнаруженных координатором нарушения исходного контракта:
- proxy URL с U+00A0 или U+0085 сейчас принимается _proxy, хотя контракт
  запрещает whitespace/control; проверить fail-closed до bind через make_service;
- scripts/abg-release manifest() принимает symlink вместо файла
  manifests/<sha>.sha256. Проверить через prepare CLI: отказ без изменения
  внешнего target, при обычном manifest/repeat поведение остаётся корректным.
Компонентные Docker-подтверждения координатора (не замена твоего CLI-probe):
/home/user/.cache/abg-coord-20260915/m12/coordinator-proxy-check.json и
coordinator-manifest-check.json в том же каталоге. Источник FINAL неизменен.
Не добавлять произвольный hardening сверх исходных no-symlink/URL правил.

Зонд постановщика валидировать: этот BASE red именно по этим нарушениям,
не среды/отсутствующего API; ДВА различных корректных эталона на отдельных
копиях — green; обходные варианты (включая два sweep/sleep, проверку closed
слишком рано, пропуск pending handler и ослабление scope) — assertion-red.
Проверить, что мутированное поведение реально достигнуто, затем restore green.
Эталоны/обходы/контекст остаются в приватном пакете; будущему автору продукта
передаются только byte-identical probe и короткий baseline summary.
Если корректный эталон требует изменения запрещённых ядра/transport или
контракт неоднозначен, дать точный blocker; не расширять скоуп молча.

## Пакет, границы и завершение

Выход /home/user/.cache/abg-coord-20260915/m12/shutdown-probe/:
result.md, commands.json (command/cwd/rc/log для каждой операции),
author-mutations.json, probe-validation.json, logs/, refs/, mutations/,
SHA256SUMS с относительными путями; отдельно handoff/probe-baseline.md.
В summary — итоговая таблица survivors/invalid/equivalent/kills и перечень
непокрытых обязательных свойств, известная гонка отдельно. Не править продукт
для получения красивой таблицы. Координатор соберёт единый возврат Grok.

Коммитить только новый probe; HEAD=BASE плюс этот один файл. Commit subject
до50символов, без attribution/amend. Push/merge/deploy запрещены. Продукт,
старые/frozen/авторские tests, specs, TASKS/CHANGELOG не менять. Main-клон
автора /home/user/exec-clones/abg-m12a-service-20260915 не трогать.
No reviewers/другие модели/новые панели/host installs/sudo. Runtime/imports/
assertions продукта только Docker1002:1002; host Python только git/files/meta.
Не читать реальные .env/секреты/чужие trees/services, не ходить по внешним
целям. Не пересобирать provider images и не повторять M9–M11/recon/M12probe
эталоны. Нужен только этот независимый пакет. report.json v2 не требуется:
это подготовка пробника/мутаций, а не приёмка или реализация сервиса.
На quota error — сохранить доказательство и остановиться без повторов.
После пакета и cleanup своих ресурсов остановиться с итоговым SHA и путями.
