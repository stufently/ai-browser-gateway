# M11 — контракт HTTP API и CLI для независимого probe

Контракт координатора,15.09.2026. Реализация только после принятого frozen probe
и полной execution-спеки. M10 принята на ebb852410c3c218b41acae068b11bda653ee0dc4,
merge69b6911a428c3655069359e3e2a15b86a8fd7a98; код main совпадает с принятым.
Автор реализации планируется cx, независимый probe/эталоны/мутации Grok.
Основание: принятая Grok-разведка m10-recon-result.md, разделы4–6,
контракт M10 SHA01b9df3ffb99559883d3438b7fe8727c4ba0ccefd8e9591363a6bfb3d068ea84,
существующие gateway.models и StrEnum bench.models/bench.escalate.
Политика/транспорт M10 не меняются. Сервис, profiles file и monitoring — M12.
Python stdlib, без новых зависимостей. Всё исполнение/тесты в Docker1002:1002.

## Публичные границы

- gateway.format.render_content(outcome, format_name): str для text/html/markdown,
  list для links, dict для meta. Никакой сети и повторного fetch.
- gateway.httpapi.make_server(address, *, token, browser_limit=1, profiles=None,
  entrances=None, fetcher_factory=None) возвращает ещё не запущенный HTTPServer.
  address=(host,port), port0 допустим для тестового listener. Вызывающий управляет
  serve_forever/shutdown/server_close. token — непустая ASCII строка без пробелов
  и control; browser_limit положительный int, не bool. Невалидный config —
  статический ValueError до bind. address: пара(host,port), host непустойstr,
  port int0..65535 кромеbool. maps копируются, внешние изменения не влияют.
  factory по умолчанию ProductFetcher; после validation зовётся как
  factory(url, entrances=..., profiles=...). Из неё получается callable M10.
- gateway.httpapi.limit_fetcher(fetcher, semaphore, *, url, clock=<monotonic ms>)
  возвращает callable(PlanStep, budget_ms)->ProviderReply, см. limiter ниже.
- gateway/client.py — самостоятельный stdlib HTTP client, без импорта продукта.
  scripts/abg-fetch — shell wrapper, запускающий этот client только в Docker.

Внутренние классы/slots/число чтений clock не фиксируются. Публичные функции
нужны для настоящих независимых tests, без проверки приватной реализации.
Не менять gateway.product/fetch/models/plan/engine, bench/probe/registry или
старые tests/frozen probes ради API. Условия M10 остаются единственным policy.

## HTTP

GET /health без токена ->200 {"ok":true}, не берёт browser slot и не делаетfetch.
POST /v1/fetch: Authorization: Bearer <token>, сравнение constant-time.
Нет/неверный auth ->401 {"error":"unauthorized"}, до fetcher_factory/fetch.
Только application/json (разрешён charset parameter), UTF8 JSON object.
Неизвестные поля, duplicate JSON keys, NaN/Infinity, неверные типы/значения ->400
{"error":"invalid_request"}. Body ограничен64KiB; Content-Length обязателен,
неотрицательный int; дубли Content-Length и Transfer-Encoding отклоняются.
Неправильный media type/framing, body>64KiB или неполноеbody ->400 invalid_request.
Body read имеет timeout<=5s, никакого read-until-EOF на открытом соединении. Connection close
после ответа допустим. Ответы application/json с корректной UTF8 длиной.
Unknown path404; известный path с неверным method405. Неожиданное внутреннее
исключение ->500 {"error":"internal_error"}, без traceback/данных клиента влоге.
Не возвращать тело ошибочного upstream как error JSON, исключения не печатать.

Request поля:
- url: обязательно, валидация M10;
- max_age_hours=0.0, budget_ms=30000 (cap180000), allow_browser=true;
- expected_text=null, точная семантика/валидация M10;
- format="text", один из text/html/markdown/links/meta.

JSON профилей, proxy URL, Docker options, provider или token fields нет.
Имена egress_profiles формируются сервером из keys его profiles по порядку;
в M11 порядок стабильный. Настройка ротации пула — отдельнаяM12.
Полная validation request/format до запуска run_product, factory и fetch;
clock бюджета стартует после validation. Это не запрещает внутренние часы
HTTP-сервера/socket для ограничения чтения.
Для валидного запроса итог M10 всегда200 JSON, в том числе okfalse.

Response обязательные поля:
ok,url,final_url,format,content,provider,age_hours,error_type,step,elapsed_ms,attempts.
content тип зависит отformat; status/challenge доступны внутриattempts.
Attempts сериализует все поля существующего Attempt: provider,egress_profile,
success,error_type,challenge,status,elapsed_ms,age_hours,next_step.
Enums ->.value, включая Step.human="human". Не вводить альтернативные имена.
В trace только имя proxy profile; никаких proxy URL/creds/env. Промежуточных
HTML/text нет. На okfalse content="" для строк, [] дляlinks, {} дляmeta.
Сервер не добавляет ложных provider calls и не меняет outcome policy.

## Browser limiter и budget

Один общий BoundedSemaphore(browser_limit) на make_server instance, общий всем
HTTP requests. API запускается одним процессом. Берут слот только providers
kind browser (patchright/Scrapling); HTTP/RSS/Wayback не ждут слота.
run_product уже считает общийdeadline и передаёт remaining budget вwrapper.
limit_fetcher учитывает время acquire внутри этого budget: acquire с конечным
remaining timeout, затем вычитает прошедшее время перед inner fetcher. Если
слот не получен или остаток<=0, возвращает нормальный ProviderReply timeout
без внутреннего fetch/Docker. При получении слота release обязательноfinally,
включая исключение. Нельзя передавать0 или заново полный исходныйbudget.
Для небраузерного шага передать fetcher тот же budget безsemaphore.
url helper — заранее проверенный исходный URL запроса. Timeout reply использует
его в requested_url/final_url, нужныйprovider, error_type=timeout, status=None,
challenge=none, пустыеhtml/text, ageNone. Остаток перед inner fetch — положительный
int, округлённый вниз; если после округления0 — timeout. Остальные нулевые
метрики timeout не выдумывают сеть, elapsed_ms отражает ожидание.
Тестовый clock монотонный вms; не требовать фиксированного числа чтений.
Timeout ожидания слота может быть в trace логическим вызовом wrapper, statusnull;
не выдавать его за успешный запуск браузера. /health в очереди не стоит.

## Форматы

text = outcome.text, html = outcome.html. Форматирование не меняет outcome.
На okfalse всегда пустое значение нужного типа, даже если fake outcome содержитbody.
Невалидное имяformat -> статический ValueError. formatter без IO.
Markdown передаёт видимый текст и h1–h6,p/br,li,HTTP(S) anchors,strong/em,code/pre,
blockquote,img alt/src; исключает script/style/noscript/iframe/svg/nav/header/footer.
Допустимы разумные варианты whitespace/списков, не байтовая копия cf-fetch JS.
Не терять текст при вложенных inline tags, декодировать HTML entities.
links: document-order [{"text":<нормализованный label<=100символов>,"href":<URL>}].
Только http(s), относительные href разрешать относительно outcome.final_url;
mailto/javascript исключаются. Пустой label допускается, дубликаты сохраняются.
meta: title; description (meta[name=description], иначе og:description);
ogTitle (og:title), ogImage (og:image), canonical (link[rel=canonical], absolute);
h1 (массив текстов), lang (html lang). title/h1 присутствуют всегда (""/[]);
остальные отсутствующие поля опускать. Без новых network calls.

## CLI и запуск HTTP module

python -m gateway.httpapi: ABG_BIND=0.0.0.0, ABG_PORT=8765,
ABG_BROWSER_LIMIT=1. ABG_TOKEN имеет приоритет, иначе ABG_TOKEN_FILE;
без токена fail closed со статической ошибкой. Ни server token, ни private file
не писать в repo. Развёртывание/создание настоящего token не входит вM11.

abg-fetch URL [text|html|markdown|links|meta], defaulttext; один/два positional.
Ноль/лишние аргументы/неизвестный mode -> ненулевойrc, stderrJSONerror, stdoutпуст.
Config env: ABG_URL=http://127.0.0.1:8765/v1/fetch; ABG_BUDGET_MS=30000;
ABG_MAX_AGE_HOURS=0; ABG_ALLOW_BROWSER=1 (только0/1); ABG_EXPECTED_TEXT
не задан ->null; ABG_TOKEN, иначе ABG_TOKEN_FILE=~/.config/abg/client-token.
Значения numeric/expected валидируются как request M10, без тихого fallback.

Wrapper --user1002:1002, --networkhost, standaloneclientfile RO. Разрешить
symlink wrapper из service/bin, определить реальный путь к соседнемуclient.
Только Docker client runtime, не hostPython и не product imports вCLI.
Default image python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6;
ABG_CLIENT_IMAGE override допустим как конфиг владельца, не полеHTTPrequest.
Передавать токен только env поимени или ROfile; его значения в Docker argv нет.
В client контейнере нет Docker socket/всегоrepo/serverconfig. Никакихhostinstall.

CLI обращается ровно один раз к API; не следует redirects и не переносит Bearer
на Location. Сетевые/HTTP/okfalse/неправильнаяschemaresponse -> ненулевойrc,
stdoutпуст, stderrвалидный JSON со статическим/whitelisted error, без сырого
errorbody или str(exception). При success stdout=выбранныйcontent (допускается
конечный newline), links/meta ->JSON, stderrпуст, rc0. Проверить typeformat/content
до вывода. Не выводить полныйслужебныйenvelope. Не делать скрытый localfetch.
cf-fetch/егоskill/потребителей не менять. MCP не добавлять в этой вехе.

## Доказательства

Независимый frozen probe до реализации: два правильных API/format/client
эталона, BASEred по отсутствию API, обходы на своихassertions. Без слотовых/
приватных/layout ограничений и без переполнения review input; не дублировать
уже полностью проверенную лестницу M10 в новомprobe. Assertions по новомуAPI.

Unit: actual local HTTPServer вDocker, auth/schema/форматы/секреты; globalbrowser
concurrency сEvents/barriers, acquiretimeout/releaseпослеexception и /healthпри
занятомслоте, HTTP-only безacquire. Не опираться на точный millisecond sleep.
CLI tests вDocker, fakeDocker для argv/secret rules и реальный HTTPstand дляclient,
redirect receiver получает0запросов/токенов. Symlink-install работает.
Live: CLI→настоящий HTTPAPI→ProductFetcher→реальный JS browser на собственном
локальномстенде; правильныйtoken/format/stdout, wrongtoken иokfalse неуспех.
Все product/assertions вDocker1002, host толькооркестрация, собственныйscopedcleanup.
Не повторять внешний targets benchmark здесь, его место — deployedM12.

Уточнения live/CLI: default client-token путь разворачивается относительно HOME
host пользователем wrapper, затем монтируется RO в известный путь внутриclient;
не искать host token в /tmp HOME контейнера. В live допустим factory, создающий
настоящий ProductFetcher с network=уникальнаясетьстенда; это настройка сети,
не fakefetcher. API публиковать только на loopback динамическом порту, CLI
--networkhost обращается туда, провайдеры достигаютstand через ту же сеть.

Исходники cf-fetch прочитаны при разведке: fetch.sh SHA256
7de3f29111b1caf5ee260ef10449983a6048692200f7f5f942ead52ff54d1b9d,
docker/fetch.js SHAcc160725c815915169969b8099882ddbed18cad91ceb9f8d96835e9e034ae2a8.
Режимы совместимы семантически; byte-exact JS DOM formatting не обещается.
Унаследованные no-header/raw HTTP отпечатки и провайдеры M10 не менять.
