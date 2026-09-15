# AI Browser Gateway

Единый шлюз доступа к веб-страницам для агентов и автоматизации: один API, за
которым спрятаны все способы достать страницу — от обычного HTTP-запроса до
браузера с антидетектом, — и который выбирает **самый дешёвый достаточный**.

Проект заводится вместо того, чтобы в пятый раз повторять один и тот же бой с
Cloudflare в очередном проекте: сейчас скрапинг размазан по `cf-fetch`,
`gpt-web-gateway`, мониторингу и SEO-парсерам, и каждый решает его заново.

## Статус: фаза 1 измерена

Стек выбран **по числам, а не по описаниям**. Главный вывод замера 06.09.2026:

> **Браузер окупается рендерингом, а не обходом блокировок.**

Ни один из пяти движков (playwright, patchright с настоящим Chrome, camoufox,
pydoll, playwright+stealth) не добавил **ни одной** цели к обычному `curl` с
браузерными заголовками. Зато на стенде способностей браузер берёт 7 сценариев из
12 против 5 — и вся разница там, где нужен JS. Признак для запуска браузера,
следовательно, не отказ, а `content_missing`: ответ пришёл, а содержимого в нём
нет.

Лестница по итогам замера:

```
обходной вход (RSS, sitemap, JSON, архив) → HTTP с браузерными заголовками →
patchright → смена egress → человек
```

14.09.2026 замер M8: `scrapling` с `solve_cloudflare` взял `cf-bizprofile`,
которую patchright на том же прогоне не взял (incremental 1). В лестницу ядра
ещё не встроен — это следующий шаг, если владелец подтвердит. Числа:
`docs/research/05-scrapling.md`.

| Документ | Что в нём |
|---|---|
| `docs/research/05-scrapling.md` | M8: scrapling vs patchright vs curl, в том числе живой Instagram |
| `docs/research/04-phase1-verdict.md` | вердикт: кто остаётся, кто исключён и на каком основании |
| `docs/research/03-stand-b-results.md` | измеренные таблицы: проходимость и способности |
| `docs/research/01-candidates.md` | 25 кандидатов, сверенных с реестрами |
| `docs/research/02-egress-and-managed-browser.md` | свой egress и managed-браузер Cloudflare |
| `docs/BENCHMARK_PLAN.md` | как меряем: два стенда, 12 сценариев, признак успеха |
| `TASKS.md` | статус работ |

## Ядро шлюза

Пакет `gateway/` исполняет лестницу для одного URL: `curl`, затем по решению
`bench.escalate.next_step` — `patchright` для рендеринга или `curl` через другой
egress. После повторной блокировки на новом egress требуется человек.
При `max_age_hours > 0` перед HTTP пробуются `rss` и `wayback`; успех входа
требует найденного sentinel и известного возраста не больше заданного допуска.
При нулевом допуске входов в плане нет.

```python
from gateway.engine import run
from gateway.fetch import BenchFetcher
from gateway.models import GatewayRequest

request = GatewayRequest(url="https://example.invalid/page", sentinel="PAGE_OK")
fetcher = BenchFetcher(request.url, request.sentinel)
outcome = run(request, fetcher)
print(outcome.ok, outcome.provider, outcome.step)
```

`BenchFetcher` запускает провайдер в Docker (`--user 1002:1002`, образы из
реестра). Нужен работающий Docker; провайдерам не монтируется Docker socket.
Ядро требует sentinel. Python-вход M10:

```python
from gateway.fetch import ProductFetcher
from gateway.product import ProductRequest, run_product

request = ProductRequest("https://example.org")
outcome = run_product(request, ProductFetcher(request.url))
```

URL-only не подтверждает смысл. `expected_text` клиента — точная подстрока
HTML/text; HTTP-ошибки и interactive challenge она не отменяет.
Trace с challenge — `outcome.attempts`; отказ: пустые html/text,
причина `error_type`, решение `step`.
Docker UID/GID `1002:1002`; live: `python3 tests/live_m10_product.py`.
[Контракт M10](docs/specs/m10-product-contract.md).
HTTP API/CLI — M11, сервис — M12.

Имена `profiles` и `entrances` у `BenchFetcher` обязаны совпадать с именами в
`GatewayRequest` (`egress_profiles` и входы плана). Несовпадение сейчас даёт
`not_measured` на транспорте, а ядро M7 на этом reason не продолжает лестницу —
это ограничение согласованного контракта, а не безопасный продуктовый запрос.

Контракт транспорта: `fetcher(step, budget_ms) -> ProviderReply`. Ядро передаёт
остаток общего бюджета перед каждой попыткой, записывает её результат и решение
в `outcome.attempts`. На отказе содержимое пустое, `provider` и `age_hours` равны
`None`, а `error_type` и `step` объясняют остановку. Исключения адаптера выходят
вызывающему; штатные отказы адаптер возвращает как `FetchResult`.

## Харнесс

```bash
python3 -m bench.server            # поднять стенд A (12 детерминированных сценариев)
python3 -m unittest discover -s tests -t .
python3 tests/mutation_gate.py     # 17 мутаций, каждая обязана быть убита
python3 tests/mutation_gate_gateway.py  # 5 мутаций ядра M7
```

Ни одной сторонней зависимости: только стандартная библиотека Python.

## Правила проекта

- **Сначала измерить, потом выбрать.** Провайдер попадает в стек не потому, что
  хорошо выглядит, а потому что закрывает страницы, которые не закрывают более
  дешёвые.
- **HTTP 200 успехом не считается.** Заглушка Cloudflare тоже приходит с 200 и
  бывает длиннее настоящей страницы. Успех — найденный sentinel на ответе,
  который не является отказом.
- **Строка ожидания не должна встречаться на странице отказа.** Оплачено:
  `expect = "bizprofile"` совпадал с заглушкой, которая называет заблокированный
  хост, и провал засчитывался успехом.
- **Замер без egress ничего не доказывает.** Один и тот же образ с одним
  отпечатком получает 200 с одного адреса и 403 с другого.

## M11: HTTP API и Docker CLI

Это интерфейсы для локального запуска; deployed service, профили/ротация пула,
monitoring и production-конфигурация относятся к M12.

HTTP API использует stdlib и существующий `ProductFetcher`. Для локального
запуска из корня клона с уже подготовленным **тестовым** token в окружении:

```bash
docker run --rm --user 1002:1002 \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD:$PWD:ro" -w "$PWD" \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e ABG_TOKEN \
  python@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 \
  python3 -m gateway.httpapi
```

Вместо `-e ABG_TOKEN` сервер принимает `ABG_TOKEN_FILE`: смонтируйте подготовленный
файл только для чтения и передайте путь внутри контейнера. Файл должен читаться
UID 1002. Значение `ABG_TOKEN` имеет приоритет, в том числе пустое значение,
которое отклоняется. Без токена сервер завершается со статической ошибкой.
Не храните private token в репозитории. Defaults: `ABG_BIND=0.0.0.0`,
`ABG_PORT=8765`, `ABG_BROWSER_LIMIT=1`.

```bash
# ABG_TOKEN уже задан в окружении; его значение не входит в Docker argv.
scripts/abg-fetch https://example.org text
scripts/abg-fetch https://example.org html
scripts/abg-fetch https://example.org markdown
scripts/abg-fetch https://example.org links
scripts/abg-fetch https://example.org meta

# Или существующий файл пользователя; значение токена не передаётся аргументом.
ABG_TOKEN_FILE="$HOME/.config/abg/client-token" scripts/abg-fetch https://example.org
```

Wrapper работает через symlink, запускает только самостоятельный `client.py` в
Docker UID 1002:1002 с `--network host` и RO mount одного файла клиента. По
умолчанию файл токена ищется относительно **host HOME**; CLI не получает repo,
server config или Docker socket. `ABG_CLIENT_IMAGE` переопределяет образ клиента.

`GET /health` возвращает `200 {"ok":true}` без авторизации и fetch.
`POST /v1/fetch` требует `Authorization: Bearer <token>`, `Content-Length` и
`Content-Type: application/json`; тело — объект с обязательным `url` и опциями:

| Поле JSON | CLI env | По умолчанию |
| --- | --- | --- |
| `budget_ms` | `ABG_BUDGET_MS` | 30000, максимум 180000 |
| `max_age_hours` | `ABG_MAX_AGE_HOURS` | 0 |
| `allow_browser` | `ABG_ALLOW_BROWSER` | true; env только 0/1 |
| `expected_text` | `ABG_EXPECTED_TEXT` | null, если env отсутствует |
| `format` | второй positional CLI | text |

`ABG_URL` по умолчанию `http://127.0.0.1:8765/v1/fetch`. Неизвестные поля,
повторные JSON keys, некорректный framing, неполное или превышающее 64 KiB тело
дают 400. Общее время чтения тела ограничено четырьмя секундами.

Валидный запрос возвращает HTTP 200 даже при `ok:false`: это результат продуктовой
политики, а не transport error. Ответ содержит выбранный `content`, `provider`,
`error_type`, `step`, `elapsed_ms` и `attempts`. Trace сохраняет status/challenge,
решения и имена proxy profiles без URL/credentials и промежуточных страниц.
На неуспехе content пустой (`""`, `[]` или `{}` по формату).

CLI выводит только content: строки для text/html/markdown, JSON для links/meta.
Ошибки HTTP/сети, `ok:false` и неверная response schema дают ненулевой rc,
пустой stdout и статический JSON error в stderr. Redirects не выполняются.
Общий бюджет включает ожидание единого browser semaphore на экземпляр сервера;
HTTP/RSS/Wayback и `/health` не занимают browser slot. Политику переходов M10 API
не дублирует. Живая проверка на изолированном JS stand: `python3 tests/live_m11_api.py`.
