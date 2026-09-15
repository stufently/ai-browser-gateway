# M12a — контракт сервиса и локальной поставки

15.09.2026. Следует за принятой владельцем M11, FINAL e6f7f0c,
merge e5fd99752f23c35f5d0ba2bdafde7aa80deee867. Координатор пишет контракт;
код, тесты и исправления пишут исполнители. M12b затем разворачивает принятый
код, создаёт приватную конфигурацию и выполняет уже разрешённый живой замер.
Этот контракт — постановка, а не утверждение о существующих новых функциях.

## Результат и границы

Запускаемый Docker-сервис с принятым API M11, пулом профилей, периодическим
мониторингом и воспроизводимым локальным release. M12a проверяется на своих
Docker-стендах с фиктивными секретами; production deployment и чтение реальных
credentials только в M12b после приёмки кода. Ни новых HTTP-полей клиента,
ни смены policy M10, ни переключения cf-fetch/потребителей. Без MCP/CI.

Существующее, подтверждённое разведкой и чтением тел:
- gateway.httpapi.make_server(address, token=..., browser_limit=1,
  profiles=None, entrances=None, fetcher_factory=None) сохраняет порядок
  переданных profiles. GET /health независим от fetch и browser semaphore.
- gateway.httpapi.main не грузит profiles. Новый service entrypoint отдельный.
- gateway.api_http.Handler строит ProductRequest с tuple(server.profiles).
- ProductFetcher принимает launcher и network; DockerLauncher.run принимает
  argv, timeout, env. Лестница M10 делает одну фактическую смену egress.
- bench.egress.load_profiles читает TOML; отсутствующий файл даёт пустой dict,
  групповые/общие права отвергаются. Для сервиса обязательный файл валидируется
  строже, существующий loader не меняется.
- PROBE_FILE вычисляется от resolved bench/runner/fetch.py; release на одном
  абсолютном пути host/API сохраняет transport без нового bind override.

## 1. Сервисный вход и конфигурация

Новый модуль gateway.service, команда `python3 -m gateway.service`.
Публичный шов для независимых проверок:
`make_service(environ=None, *, fetcher_factory=None)` возвращает HTTP server,
ещё не запущенный. environ — mapping либо os.environ; factory та же граница,
что make_server. Нормальный runtime всегда использует настоящий ProductFetcher.

Обязательны ABG_TOKEN_FILE, ABG_PROFILES_FILE. Оба — читаемые обычные файлы,
без group/world доступа, принадлежат текущему uid; нет/пусто/ошибка чтения или
формата → fail closed ДО listen/fetch, статическое invalid_configuration без
значений/путей в stderr. Сервис принимает token только из файла, запрещает
одновременно заданный непустой ABG_TOKEN (не молча выбирает другой источник).
Token: правила M11, допускается завершающий CR/LF; не генерировать на старте.

Профили: непустой mapping, непустые имена кроме direct, непустые HTTP(S)
proxy URL с hostname и корректным портом, userinfo допускается именно здесь.
Без control/whitespace. Плохой профиль не скипать молча. Для unit/local stand
допускается меньше15; production provisioning создаёт ровно ms1..ms15.

ABG_BIND default0.0.0.0, ABG_PORT default8765 (0 разрешён для теста),
ABG_BROWSER_LIMIT default1 — положительный int. Ошибки fail closed.
ABG_PROVIDER_NETWORK необязателен — только для собственного Docker stand;
в production не нужен. ABG_INSTANCE — обязательный безопасный slug для
идентификации одной установки, regexp [a-z][a-z0-9-]{0,62}.

## 2. Ротация без изменения M11 по умолчанию

make_server получает необязательный keyword rotate_profiles=False.
False сохраняет byte-level observable M11: порядок, copies, обработку запросов.
Сервис включает True. Только валидный авторизованный POST /v1/fetch расходует
позицию. GET /health,401,400 не двигают указатель. Вызовы получают циклические
сдвиги полного исходного списка под lock, без гонки shared dict. Для a,b,c:
(a,b,c), (b,c,a), (c,a,b), ...; первый запрос начинается с первого ключа TOML.
Конкурентные валидные запросы получают каждую следующую позицию ровно один раз.
Зафиксированный для запроса порядок не меняется из-за соседнего запроса.
Factory получает изолированный полный profiles dict; значения не идут в
ответ, trace или argv. ProductRequest получает порядок только имён.

Принятое ядро по-прежнему решает, когда нужен egress. Не более одной РЕАЛЬНОЙ
egress-попытки, даже при15профилях; успешный direct не вызывает proxy.
Нельзя превращать ротацию в15попыток или переписывать product/engine.

## 3. Граница Docker и завершение

Сервисная factory использует ProductFetcher с thin launcher wrapper над
неизменным DockerLauncher. Каждый docker run провайдера получает labels
abg.owner=ai-browser-gateway, abg.instance=<ABG_INSTANCE>,
abg.role=provider, abg.request=<уникальный id запроса>. Labels не включают URL,
token или proxy. Все попытки одного запроса имеют один id, соседние — разные.
Аргументы/env/deadline передаются без потери. Никакого shell=True.

Сохраняются user1002:1002, probe.py RO, env ABG_PROXY по имени, browser shm1g.
Провайдеры не получают socket, release tree или management/ping/token secrets.
Не менять bench.runner/registry/transport. Сервисный runtime может читать
socket и запускать provider Docker; sidecar/CLI — без socket.

SIGTERM внутри API-контейнера завершает HTTP server и убирает только provider
контейнеры этой owner+instance+role; cleanup ограничен временем. На старте
допускается уборка таких же собственных остатков. Другой instance, другой owner
и отсутствие label не дают права удалить контейнер. В test/live ресурсы
принадлежат уникальному run; host сигналы/чужие процессы не трогать.

## 4. Мониторинг

Новый модуль gateway.health_monitor. Тестируемая функция
`check_once(health_url, ping_url, *, timeout=5)` возвращает bool здоровья API.
GET health с timeout<=5, redirect запрещён; healthy только HTTP200 с JSON
объектом {ok:true} (дополнительные поля допустимы). Неверное тело, HTTP failure,
timeout → unhealthy. Затем GET ping_url (healthy) либо ping_url+'/fail'.
Ping URL — полный https, без userinfo/fragment/query, nonempty path; localhost
http допустим ТОЛЬКО при явном ABG_MONITOR_ALLOW_LOCAL_HTTP=1 для Docker tests.
Redirect ping запрещён. Сеть/ошибка ping не роняет loop, не меняет health-result;
лог только статический текст/класс ошибки, без repr/str(exception),URL/секретов.

Entrypoint `python3 -m gateway.health_monitor`: ABG_HEALTH_URL,
ABG_HC_PING_FILE (приватный файл с теми же правами/uid, что token),
ABG_HEALTH_INTERVAL_SECONDS default60, положительное конечное число.
Невалидная конфигурация → ненулевой выход ДО сети, статическая ошибка.
Настоящий цикл вызывает check_once периодически; не success по таймеру без health.
Sidecar не требует API token/management key, не имеет socket/host network.

Compose API HEALTHCHECK отдельно: GET localhost /health, проверяет тело,
30s/5s/3retries. Sidecar обращается к http://api:8765/health по своей сети.
Реальный check и history в M12b; M12a фиксирует автоматические запросы на своём
HTTP test-receiver без ручного ping и проверяет /fail при отказе health.

## 5. Образы, Compose, release

Новые deploy/Dockerfile и deploy/compose.yaml. Runtime image:
Python3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
+ COPY /usr/local/bin/docker из docker:29.8.0-cli@sha256:eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66.
Pins проверены registry15.09; совместимость COPY — гипотеза до реального build
и запуска docker client внутри образа. Ничего не ставить на host.
Не использовать host /usr/bin/docker mount как замену готовому runtime.
Sidecar — тот же pinned Python без Docker CLI; image включает/монтирует код RO.
Provider local IDs из разведки не пересобирать и не выдавать за registry pins.

Compose project задаётся явно, user1002:1002 обоим сервисам; API socket group
из фактического stat, default983 сейчас. Только port127.0.0.1:8765:8765.
Для tests разрешён иной свободный loopback-port. restart unless-stopped,
read_only true с writable tmpfs/tmp, код RO; API socket разрешён, sidecar нет.
Environment содержит только несекретные параметры/пути; token,profiles,ping URL
в отдельных RO file mounts. Management env никогда не монтируется.

Новый scripts/abg-release — host orchestration для одного собственного каталога:
`prepare --repo <repo> --sha <full40> --root <own-root>` создаёт
<root>/releases/<sha> из git archive указанного commit, без untracked/.git,
без секретов/checkout разработчика. SHA не tag/branch и должен существовать.
Повтор того же SHA проверяет совпадение файлов и mode, не переписывает чужое
содержимое; mismatch → ошибка. Symlink/traversal/overwrite-existing-refuse.
`prepare` не стартует Docker и не меняет active release. Manifest SHA256 вне
release фиксирует git-tracked contents; обычные файлы644/exec755/каталоги755.
Достаточен интерфейс prepare; переключение compose/rollback — M12b по README,
не добавлять общий deploy-framework. Код release helper — stdlib, host только
git/archive/files/metadata/subprocess; продукт не импортировать на host.
В Compose release bind и working_dir — ОДИНАКОВЫЙ абсолютный путь host/API.
Конфиг root/token/profile/ping вне release. Возможность rollback — выбрать
предыдущий сохранённый release, не пересобирая его из текущего checkout.

## 6. Подготовка приватной конфигурации

Новый scripts/abg-provision: `--source <env-file> --output <profiles-file>`
парсит только PROXY_LOGIN/PROXY_PASSWORD (strip, одиночные/двойные кавычки),
отсутствующие/дубли/пустые значения → ошибка. Не исполнять shell/env expansion.
Создаёт ровно15 HTTPprofiles ms1..ms15 для msN.example.net:8126; percent-encoding
userinfo, TOML escaping. Значения не выводить, не передавать в argv.
Файл атомарно0600, output-parent текущего uid; существующий target НЕ
перезаписывать (пользовательские креды не ротируются этой командой).
На отказе нет частичного target; временные файлы0600 убрать. Нельзя идти через
symlink target. stdout только безопасный итог count15, stderr статическая ошибка.
M12a использует synthetic source; реальный3proxy.env не читать.
Token и pingfile M12b создаст программно0600, вне git, после приёмки.

## 7. Проверки и документация

Новый tests/probe_m12_service.py готовит независимый исполнитель на этом
контракте до реализации. Два различных корректных эталона green, BASE red
по отсутствию нового API, обходные реализации assertion-red; frozen SHA в
execution-спеке. Автор продукта не читает эталоны/обходы/контекст проверяющего.
Мутации новых авторских tests — противоположный исполнитель на FINAL.

Авторские unit tests проверяют ошибки конфигов/права, concurrency/изоляцию
ротации, real launcher argv/labels/scoped cleanup, мониторинг/redaction,
release archive+повтор/mismatch и provisioning encoding/atomicity.
Все product imports/assertions только Docker1002:1002. Старые unit/frozen
M9/M10/M11 неизменны и green. Один полный unittest-критерий, без дублей.

Live M12a: собрать runtime; prepare release из committed SHA; поднять Compose
на своём root/network и fake secret files; CLI→service→реальные curl/patchright
получает JS-маркер своего стенда (в rawHTML нет). Проверить wrong-token,
health при занятом browser, два запроса с forced egress через локальный fake
proxy (реальный curl) и разные имена, один реальный egress; monitor loop на
receiver получает success и /fail автоматически. Restart/stop, cleanup своих
provider labels, сохранность foreign-labeled контрольного Docker-контейнера.
Проверить реальные mounts/user/group/порт и отсутствие secrets в argv/logs,
а не только текст YAML. Все ресурсы только своего run, finally cleanup.

README: build/prepare/config/compose up/down/выбор предыдущего release,
вызовы API/CLI без значений секретов, условие «production ещё M12b».
Не заявлять15proxy проверенными или deployed coverage до соответствующего
живого замера. TASKS/CHANGELOG пишет координатор после приёмки.

## Невыполнимое

Без обходов среды/оснастки/контракта. Один единый список blocker с командами,
cwd,rc и безопасными логами. Review/fix/verify по cross-review-v1; после verify
новый дефект — новый клон от FINAL и новая веха, никакого второго fix внутри
прежнего BASE. Код/пакет сохранить; валидные отзывы неизменного кода не повторять.

Уточнение проверок release: unit/probe в Docker могут подменять границу git
готовыми archive-байтами; настоящий git archive/prepare вызывается host
orchestration в live, а файловые assertions выполняются внутри Docker.
Установка git в production runtime ради теста не нужна. Независимый probe
не содержит проверок точного YAML-форматирования или частных имён helpers.
