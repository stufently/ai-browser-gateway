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
