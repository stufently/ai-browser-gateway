# M13b — probe регрессии: контейнер, созданный демоном после таймаута клиента

17.09.2026. Подготовительная задача cx, не реализация продукта. Директива
владельца 17.09.2026: «доделывай всё до конца»; владелец выбрал уборку поздних
контейнеров. Исправление напишет ДРУГАЯ cx-панель в другом клоне; она увидит
только byte-identical probe и короткий baseline, но не эталоны отсюда.

Клон /home/user/exec-clones/abg-m13b-probe-20260917, ветка m13b-probe, push
DISABLED. BASE_SHA `693400423b00eac6dd367c7fa54b64e9a20b94aa` (main, M12 влит).
Выход: /home/user/.cache/abg-coord-20260917/m13b-probe/.

## Дефект

Находка Codex при приёмке M12a (подтверждена координатором чтением кода):
`bench/runner/execute.py:DockerLauncher.run` запускает
`docker run --cidfile <tmp> …` с `subprocess.run(timeout=…)`. При
`TimeoutExpired` он удаляет контейнер ТОЛЬКО если cidfile уже существует и не
пуст. Если клиент Docker убит по таймауту ДО того, как демон записал cidfile
(медленный create/pull, занятый демон), демон может завершить создание и
запустить контейнер ПОСЛЕ возврата `run`. Такой контейнер никто не убирает:
`DockerLauncher` уже вернул управление, у сервиса M12 финальный sweep по
меткам мог пройти раньше. Код Moby 29.8.0 (`daemon/create.go`) не отменяет
create при обрыве клиента.

Требование следующей вехи (контракт поведения, не API):
- после `TimeoutExpired` у `docker run` `DockerLauncher.run` не возвращается,
  пока контейнер ЭТОГО запуска не убран или не доказано, что его не будет, —
  в ограниченное время (порядок существующего лимита уборки 30 с), и затем
  поднимает тот же `TimeoutExpired`;
- убирается только контейнер этого запуска (однозначная идентичность, которую
  launcher сам добавляет в argv), чужие — никогда;
- нормальный путь (успех, ненулевой rc, не-`docker run` команды), проброс
  env/timeout/argv провайдера, stdin=DEVNULL и возвращаемый кортеж не меняются;
- frozen probes M9–M12 и лимиты M12 shutdown остаются зелёными.

## Что сделать

Прочитать `bench/runner/execute.py`, `bench/runner/fetch.py`,
`bench/providers/registry.py` (`build_argv`), `gateway/service.py`
(`LabeledLauncher`, `LaunchGate`, `sweep_providers`) и frozen probes
`tests/probe_m9_transport.py`, `tests/probe_m12_service_regressions.py`.

1. Единственный новый tracked файл `tests/probe_m13_late_container.py`.
   Фейковый Docker только на границе `subprocess.run` (как в M12 regression
   probe), управляемые барьеры, без sleep-как-синхронизации: клиент `docker
   run` висит до таймаута, cidfile не пишется; «демон» создаёт контейнер этого
   запуска через заданную задержку ПОСЛЕ того, как `subprocess.run` поднял
   `TimeoutExpired`. Проверяет: `run` поднимает `TimeoutExpired`; после
   возврата живых контейнеров этого запуска нет; время ограничено (сторож
   стенда, не production SLA); чужой контейнер (другая идентичность) и
   контейнер, созданный демоном нормально другим запуском, не тронуты;
   сценарии «cidfile успел записаться» и «контейнер так и не создан» тоже
   корректны; нормальный путь и проброс env/timeout сохранены. Не требовать
   придуманных имён helper/атрибутов; опираться на наблюдаемые argv/вызовы
   `docker` через `subprocess.run`. Только Docker 1002:1002, `--network none`.
2. Валидация: BASE — assertion-red именно на позднем контейнере (не ошибка
   среды/импорта); ДВА разных корректных эталона в отдельных копиях (например,
   `--name` уникальным именем + ограниченный опрос `docker ps -a --filter
   name=…` и удаление; и метка-идентичность + `docker rm` по фильтру с
   ожиданием) — green вместе со ВСЕМИ frozen probes и полным unittest; обходы
   (одна попытка rm сразу после таймаута; удаление по слишком широкому фильтру;
   бесконечное ожидание; только cidfile) — assertion-red. Проверить, что
   мутированное поведение реально достигнуто, затем restore green.

## Пакет и границы

Выход: `result.md` (что проверяет probe, BASE red с строками assertion, два
эталона green, таблица обходов), `commands.json`, `refs/`, `logs/`,
`SHA256SUMS`, отдельно `handoff/probe-baseline.md` (кратко: BASE, SHA256
probe, команда запуска, что BASE красный и почему) и
`handoff/probe_m13_late_container.py` byte-identical tracked файлу.

Коммитить только новый probe: HEAD = BASE + один файл, subject ≤50 символов, без
attribution/amend. Продукт, остальные tests, specs, TASKS/CHANGELOG не менять.
Push/merge/deploy запрещены; сервис и `/home/user/services/**` не трогать.
Без reviewers, других моделей, новых панелей, sudo, host installs. Импорт и
assertions продукта — только Docker 1002:1002; host Python — git/файлы/
оркестрация. Реальный Docker-демон для эталонов не нужен — только фейковая
граница; реальный socket не монтировать. Если корректный эталон требует правки
вне `bench/runner/execute.py` или ломает frozen probe — точный blocker, скоуп не
расширять. report.json не требуется. На quota error — сохранить доказательство и
остановиться. После пакета остановиться с итоговым SHA и путями.
