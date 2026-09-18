# Фаза 1 — вердикт: какие способы остаются

Составлен 06.09.2026 по измеренным числам из `03-stand-b-results.md`.
Таблица покрытия посчитана **боевым кодом проекта** (`bench.report.coverage`) на
30 записях JSONL нашего же формата, а не руками.

## Incremental coverage, стенд B (5 действительных целей)

| Провайдер | Взял | Incremental | Unique | Решение |
|---|---|---|---|---|
| `curl` как есть | 2 | 2 | 0 | оставить: 2/5 = 0,40 |
| `curl` + браузерные заголовки | 4 | **2** | 0 | оставить: 2/5 = 0,40 |
| `curl_cffi` | 4 | **0** | 0 | исключить |
| `primp` | 4 | **0** | 0 | исключить |
| playwright | 3 | **0** | 0 | исключить |
| patchright | 4 | **0** | 0 | исключить (по этому стенду) |
| camoufox | 4 | **0** | 0 | исключить |
| pydoll | 3 | **0** | 0 | исключить |

**Ни один браузер не добавил ни одной цели к обычному curl с заголовками.**
Единственная цель, которую не берёт curl (`bizprofile.net`), не берётся и ни одним
из пяти движков, включая настоящий Chrome headful под Xvfb.

Механически применённое правило отбора («≥5 % прироста ИЛИ уникальный класс»)
выбрасывает из стека все браузеры. **Так делать нельзя**, и вот почему.

## Почему одной таблицы недостаточно

Стенд B меряет ПРОХОДИМОСТЬ, стенд A — СПОСОБНОСТИ. На стенде A `curl` берёт
5 сценариев из 12, любой браузер — 7. Разница ровно там, где нужен JS.

Значит вывод не «браузеры не нужны», а точнее и полезнее:

> **Браузер окупается рендерингом, а не обходом блокировок.**

Это прямо противоречит порядку из затравки, где браузер стоял ступенью эскалации
ПОСЛЕ отказа HTTP-клиента. Эскалация «получил 403 → запускаю браузер» на нашем
наборе не помогла ни разу, а на LowEndTalk сделала хуже: `curl` берёт страницу за
0,4 с, ванильный Playwright получает там челлендж и тратит 33 с.

Правильный признак для запуска браузера — **не отказ, а отсутствие контента при
успешном ответе** (`content_missing` в нашей таксономии): страница пришла, а
ожидаемого в ней нет, потому что его дорисовывает JS.

## Что остаётся в стеке

| Ступень | Что | Почему именно это |
|---|---|---|
| 0 | **Обходные входы**: RSS, `sitemap.xml`, JSON-эндпоинты, архив с возрастом снимка | Стоят ноль и в одном случае из пяти оказались ЕДИНСТВЕННЫМ работающим способом: Wayback отдал `bizprofile.net` снимком возрастом 3,9 часа тогда, когда его не взял никто |
| 1 | **HTTP с полным набором браузерных заголовков** | 4 цели из 5, 0,2–1,3 с, 280 МБ образа. Заголовки дают +2 цели к голому curl |
| 2 | **Один браузер — `patchright`** | Нужен ради JS (7/12 против 5/12), а не ради обхода. Из четырёх: 33,5 МБ RSS и 1,84 ГБ образа — лучший баланс; единственный вместе с camoufox взял LowEndTalk, где ванильный Playwright получил челлендж; и он **уже в проде у владельца** в `gpt-web-gateway`, то есть сопровождать придётся один стек, а не два |
| 3 | **Смена egress** (прокси владельца) | Не измерено. См. ниже — это главный незакрытый вопрос |
| 4 | **Человек** | Интерактивный челлендж по замыслу проекта не обходится молча |

## Кто исключён и на каком основании

| Кандидат | Основание |
|---|---|
| `curl_cffi`, `primp` | Incremental **0** на всех пяти целях поштучно. Затравка ставила `curl_cffi` обязательной ступенью Tier 1 — замер этого не подтвердил. Оговорка: пять целей мало, решение пересмотреть при расширении набора |
| ванильный playwright | Строго хуже patchright на стенде B (3/5 против 4/5), равен на стенде A. Остаётся в бенчмарке как контроль, в стек не идёт |
| camoufox | Тот же результат, что у patchright, при **3,07 ГБ образа против 1,84** и **102 МБ RSS против 33,5**. В одиннадцать раз тяжелее всего HTTP-класса и не закрыл ни одного класса страниц, который не закрывают остальные |
| pydoll | 3/5: на обеих CF-целях `CommandExecutionTimeout` при 220 МБ RSS. Самый лёгкий образ (1,24 ГБ), но нестабилен там, где нужен |
| `undetected-chromedriver`, `tls-client`, `hrequests` | Мертвы: последние релизы 02.2024 — 12.2024 |
| `nodriver`, `zendriver`, `rnet`, `trawl`, `Byparr` | AGPL/GPL — несовместимо с сетевым сервисом под пермиссивной лицензией. `trawl` и `Byparr` остаются как внешние эталоны для сравнения, но не встраиваются |
| `r.jina.ai` | Сам стоит под Cloudflare: 403 `Just a moment...` на всех шести целях с нашего хоста |
| Common Crawl | Свежесть месяц против 3,9 часа у Wayback; в индексе 2 цели из 5; а на `bizprofile.net` он сохранил саму заглушку со статусом 403 — уткнулся в тот же Cloudflare, что и мы |
| Платные скраперы | Сняты владельцем 06.09.2026: «платные скраперы не нужны» |

## Главный незакрытый вопрос

**Ни один из пяти движков не взял `bizprofile.net`.** Одинаковый отказ у ванильного
Playwright, patchright с настоящим Chrome, camoufox и pydoll — это не свойство
инструментов, это свойство **адреса**. Наш единственный egress —
`198.51.100.30`, `AS206996 ZAP-Hosting GmbH`, хостинговый ASN без репутации.

У `gpt-web-gateway` тот же вывод уже получен независимо и раньше (26.07.2026):
один образ, один отпечаток, **разные адреса — 200 и 403**.

Пока второго egress нет, «инструмент не справился» и «адрес не пустили»
неразличимы, и любая работа над отпечатками — стрельба вслепую. Поэтому
**креды GoldProxy — самый ценный незакрытый замер фазы 1**, дороже любого нового
кандидата. Пункт стоит в `TASKS.md` за владельцем.

## Чего этот вердикт не доказывает

- Пять целей — маленький набор. «Incremental 0» у TLS-impersonation означает «на
  этих пяти», а не «никогда».
- По одному запросу на пару. Cloudflare решает вердикт **по навигации**, а не по
  адресу (измерено в `gpt-web-gateway`), так что повтор может дать другое.
- Холодный и тёплый режимы не разделены: все браузерные числа — холодный старт.
  Тёплый браузер в проде дешевле, и его замер впереди.
  **Закрыто раннером M2 06.09.2026:** тёплый дешевле холодного в 40 раз
  (playwright 14,5 мс против 559,5), числа — в `03-stand-b-results.md`.
- Сценарии `iframe`, `shadow` и `session` на стенде A завалены чертами моего
  чернового пробника, а не браузеров. Настоящий раннер (веха M2) обязан обходить
  граф фреймов и Shadow DOM и держать сессию между запросами.
  **`iframe` закрыт в M2** (пробник обходит `page.frames`, стало 8/12);
  `shadow` и `session` остаются за следующими вехами.

## Пересмотр 17.09.2026

По решению владельца «Сразу curl_cffi в лестницу» в M14a HTTP-ступень direct
и все egress-ступени `plan_product` переведены с `curl` на `curl_cffi`.
Порядок ступеней, входы RSS/Wayback и браузеры patchright/scrapling сохранены.
Это пересмотр прежнего исключения решением владельца, а не новый замер
incremental coverage; исторический результат 0 на пяти целях остаётся в силе.

Координатор 17.09.2026 проверил образ `abg-curl_cffi:m2` с текущим `probe.py`
через bind и `--content-only`: example.com — HTTP 200, `challenge=none`,
106 мс; lowendtalk.com/categories/offers — HTTP 200, настоящая страница
«Offers — LowEndTalk», 271 мс, но детектор возвращает `captcha` по признакам
`body_captcha` и `body_cf_challenge_platform`; bizprofile.net — HTTP 403,
«Just a moment...». Эти наблюдения переданы координатором, новых live-запросов
в M14a не выполнялось. Детектор и policy не менялись: успешный HTTP-ответ
LowEndTalk сам по себе не означает принятия страницы продуктом.

### После выкладки M14b

17.09.2026 на stand-host развёрнут release
`b31a36b10f57a21e4d2703e9de770e731d06950e`, образ `abg-runtime:b31a36b10f57`,
image ID `sha256:c0ee2abf4c14dc906092056d832983106ead0518fe3f054dff75565e30669bd0`.
AC-874 подтвердил healthy API и стабильный монитор. Оба прежних release,
их manifests и образы сохранены; непосредственный откат — `4409f8a…`,
конфигурация до выкладки — `compose.env.pre-m14b` (0600).

Улики первого прогона: `/home/user/.cache/abg-coord-20260917/m14b/`.
Таблица взята из `targets.json` (сохранена также точная копия
`targets-initial.json`) и архива `bizprofile-20260917T112640Z.json`.
`deploy-initial.json`, `profiles-initial.json`, `api-egress-initial.json`
сохраняют остальные исходные измерения перед машинной приёмкой.
Ступени записаны как **provider/status/challenge/elapsed_ms**; все попытки
в таблице — `egress_profile=direct`. Последний столбец — полное время API,
включая запуск провайдеров; его нельзя приравнивать к сумме elapsed попыток.
`null` означает отсутствие HTTP-статуса.

| Цель / страница | Провайдер успеха / исход | Лестница попыток | API elapsed, мс |
|---|---|---|---|
| `control-hqd` | `curl_cffi` | `curl_cffi/200/none/323` | 1078 |
| `control-static` | `curl_cffi` | `curl_cffi/200/none/210` | 926 |
| `cf-lowendtalk` | `curl_cffi` | `curl_cffi/200/captcha/208` | 939 |
| `cf-bizprofile` | `scrapling` | `curl_cffi/403/suspected/147` → `patchright/403/suspected/1223` → `scrapling/200/none/18406` | 23381 |
| `cf-spa-chatgpt-share` | нет: `timeout` | `curl_cffi/null/none/0` | 120385 |
| `login-instagram` | `patchright` | `curl_cffi/200/none/997` → `patchright/200/none/2273` | 5305 |
| bizprofile главная (без `expected_text`) | `scrapling` | `curl_cffi/403/suspected/173` → `patchright/403/suspected/1242` → `scrapling/200/none/17458` | 22780 |
| bizprofile Elevate Electric LLC (без `expected_text`) | `scrapling` | `curl_cffi/403/suspected/159` → `patchright/403/suspected/1352` → `scrapling/200/none/17777` | 22541 |

Итог матрицы — **5/6**, CLI: rc=0, `Example Domain` найден. Обе страницы
bizprofile без `expected_text` прошли через Scrapling с `challenge=none`,
`success=true`, `error_type=none`; локальные маркеры найдены. HTTP-ступень
каждой цели начинается с `curl_cffi/direct`; попыток `provider=curl` нет
ни в матрице, ни в указанном архиве bizprofile.

Egress измерен заново: все 15 профилей дали уникальные адреса, отличные от
direct, а запрос без авторизации — HTTP 407. Через deployed API подтверждена
ротация `ms1 → ms2 → ms3`: все три egress-попытки — `curl_cffi`, HTTP 200,
`success=true`; `rotation_proven=true` (AC-875 и AC-876).

Сравнение с `/home/user/.cache/abg-coord-20260917/m13c/targets.json`:

| Цель | Успех M13c | Исход M14b | Что изменилось |
|---|---|---|---|
| `control-hqd` | `curl` | `curl_cffi` | HTTP сразу успешен в обоих прогонах; браузер не понадобился |
| `control-static` | `curl` | `curl_cffi` | HTTP сразу успешен в обоих прогонах |
| `cf-lowendtalk` | `patchright` после `curl/403/suspected` | `curl_cffi/200/captcha` | Цель взята раньше браузера: 1 попытка вместо 2, полное время 939 против 4620 мс |
| `cf-bizprofile` | `scrapling` | `scrapling` | HTTP и patchright возвращают 403/suspected; curl_cffi браузер не заменил |
| `cf-spa-chatgpt-share` | `curl/200/none` | `timeout` | curl_cffi не получил HTTP-ответ; policy остановилась с retry_later, браузер не запускался |
| `login-instagram` | `patchright` | `patchright` | HTTP 200/none не содержит ожидаемого текста: content_missing ведёт в браузер |

LowEndTalk опроверг предположение спеки об обязательной эскалации из-за
`captcha`: детектор действительно записал этот challenge, однако матрица
передаёт `expected_text`. В текущем `gateway/product.py:accept_page` после
проверок транспорта, статуса и решающих challenge проверяется наличие этого
текста; запрет по `captcha` в этой ветке не применяется. Поэтому HTTP 200
с найденным текстом принят, несмотря на метку детектора. В прежнем прогоне
аналогичный `200/captcha` был принят у patchright. Это результат матрицы с
ожидаемым текстом, а не доказательство успеха LowEndTalk без `expected_text`.
Детектор и policy в M14b не менялись. Bizprofile остановлен на HTTP именно
403/suspected, Instagram требует содержимого, а отказ ChatGPT — таймаут,
не распознанный challenge (`status=null`, `challenge=none`).

У `cf-spa-chatgpt-share` единственная попытка завершилась `timeout`, её
`elapsed_ms=0` — записанное runner значение при отсутствии завершённого
измерения провайдера; полное время API — 120385 мс. Из этих улик точную
сетевую причину установить нельзя. Команда AC-878 вернула 0 (матрица, CLI
и проверки провайдеров выполнены), но по контракту M14b внешний отказ
отмечен **AC-878 fail**. Цель не повторяли ради успешного исхода; сервис
оставлен на новом release, откат не требовался.

## Лимит HTTP-ступени (M15a)

В M14b единственная попытка `curl_cffi/direct` на `cf-spa-chatgpt-share`
израсходовала весь бюджет 120 с, поэтому браузер не запускался. В M15a
ступени `http` и `egress` получают `min(remaining, 15000)` мс;
`entrance` и `browser` сохраняют весь остаток общего бюджета.
Если общий дедлайн ещё не достигнут, таймаут `http` ведёт к первой следующей
ступени `browser` или `egress`, а таймаут `egress` — к следующему egress-профилю.
Без подходящей ступени результат остаётся `timeout/retry_later`.
Общий дедлайн, остальные ошибки и таймауты `entrance`/`browser` не изменены.
Достаточность 15 с для обычных целей — предположение по замерам M14b;
в M15a политика проверяется офлайн, без live-запросов и выкладки.

### После выкладки M15b

17.09.2026 на stand-host развёрнут release
`58d3b738a808af71ebed84df261e87754747ee0a`, образ `abg-runtime:58d3b738a808`,
image ID `sha256:1acaf7967acbd0a436b5a01dd0a25ab4edee9e27dbcaba4a41361e48a8e53dd0`.
Повторные `abg-release prepare` и сборка завершились успешно; AC-934 подтвердил
healthy API, соответствие release/образа и стабильный монитор. Непосредственный
откат — `b31a36b10f57a21e4d2703e9de770e731d06950e`, конфигурация сохранена
байт-в-байт в `compose.env.pre-m15b` (0600). Все три предыдущих release,
их manifests и образы, а также прежние копии конфигурации сохранены.

Улики первого прогона: `/home/user/.cache/abg-coord-20260917/m15b/`.
Таблица взята из `targets.json` (точная сохранённая копия — `targets-initial.json`)
и неизменяемого архива `bizprofile-20260917T135932Z.json`.
`deploy-initial.json`, `profiles-initial.json`, `api-egress-initial.json`
сохраняют остальные исходные измерения перед повтором машинной приёмки.
Ступени записаны как **provider/status/challenge/elapsed_ms/next_step**;
все попытки восьми строк ниже — `egress_profile=direct`. `null` означает
отсутствие HTTP-статуса. Полное время API включает запуск и уборку контейнеров;
оно не равно сумме elapsed попыток.

| Цель / страница | Провайдер успеха | Лестница попыток | API elapsed, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` | `curl_cffi/200/none/328/stop` | 1131 |
| control-static | `curl_cffi` | `curl_cffi/200/none/87/stop` | 805 |
| cf-lowendtalk | `curl_cffi` | `curl_cffi/200/captcha/291/stop` | 1090 |
| cf-bizprofile | `scrapling` | `curl_cffi/403/suspected/153/browser` → `patchright/403/suspected/1313/browser` → `scrapling/200/none/18184/stop` | 23385 |
| cf-spa-chatgpt-share | `patchright` | `curl_cffi/null/none/0/browser` → `patchright/200/none/5344/stop` | 22031 |
| login-instagram | `patchright` | `curl_cffi/200/none/949/browser` → `patchright/200/none/2747/stop` | 5586 |
| bizprofile главная (без expected_text) | `scrapling` | `curl_cffi/403/suspected/584/browser` → `patchright/403/suspected/1357/browser` → `scrapling/200/none/18094/stop` | 23682 |
| bizprofile Elevate Electric LLC (без expected_text) | `scrapling` | `curl_cffi/403/suspected/163/browser` → `patchright/403/suspected/1396/browser` → `scrapling/200/none/7238/stop` | 12142 |

Матрица — **6/6**, CLI: rc=0, `Example Domain` найден. Обе страницы bizprofile
без `expected_text` успешны через Scrapling; последние попытки имеют
`success=true`, `challenge=none`, `error_type=none`, локальные маркеры найдены.
LowEndTalk, как в M14b, принят на HTTP при найденном `expected_text`, несмотря
на метку `captcha`; это не замер его проходимости без ожидаемого текста.

AC-935 заново подтвердил 15 уникальных рабочих egress-профилей, отличных от
direct, HTTP 407 без авторизации и ротацию API `ms1 → ms2 → ms3`.
Все 14 попыток `curl_cffi` в `api-egress-initial.json`, `targets-initial.json`
и указанном архиве bizprofile имеют записанный `elapsed_ms ≤ 20000` (максимум 949 мс).
Лестницы начинаются с `curl_cffi/direct`; попыток `curl` нет.

Сравнение с `/home/user/.cache/abg-coord-20260917/m14b/targets.json`
(точная копия базы сравнения — `m15b/m14b-targets-baseline.json`):

| Цель | M14b: исход / API мс | M15b: исход / API мс | Изменение времени, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` / 1078 | `curl_cffi` / 1131 | +53 |
| control-static | `curl_cffi` / 926 | `curl_cffi` / 805 | -121 |
| cf-lowendtalk | `curl_cffi` / 939 | `curl_cffi` / 1090 | +151 |
| cf-bizprofile | `scrapling` / 23381 | `scrapling` / 23385 | +4 |
| cf-spa-chatgpt-share | `timeout` / 120385 | `patchright` / 22031 | -98354 |
| login-instagram | `patchright` / 5305 | `patchright` / 5586 | +281 |

Пять прежних успешных исходов и их провайдеры сохранились. ChatGPT share
сменил отказ `timeout/retry_later` на успех через patchright; полное время
сократилось на 98354 мс, примерно на 81,7 %. Изменения времени остальных
целей — наблюдения одного прогона, а не статистическая оценка ускорения.

Для двух страниц bizprofile исход также сохранился: обе прошли через Scrapling.
Относительно текущего `m14b/bizprofile.json` (сохранён как
`m15b/m14b-bizprofile-baseline.json`) полное время главной изменилось
с 23326 до 23682 мс (+356), карточки — с 21122 до 12142 мс (−8980).

**Ветка таймаута задета вживую.** Единственная попытка `curl_cffi` с
`error_type=timeout` — direct на `cf-spa-chatgpt-share`:
`status=null`, `challenge=none`, `elapsed_ms=0`, `next_step=browser`.
Следующая попытка patchright дала HTTP 200, `success=true`, `challenge=none`,
`next_step=stop`; полное время запроса — 22031 мс. В M14b после аналогичного
HTTP-таймаута браузер не запускался, а запрос завершался за 120385 мс.
Таймаутов egress в этом прогоне не было.

Нулевой `elapsed_ms` у таймаута — служебное значение транспорта
`bench/runner/fetch.py`, когда провайдер не вернул завершённое измерение;
это **не нулевая длительность**. Поэтому JSON-проверка порога 20000 мс
подтверждает ограничение записанных значений, но не измеряет отдельно
реальное время этой оборванной попытки. Передачу управления браузеру
подтверждает сама последовательность attempts; лимит 15000 мс задан
неизменённым кодом BASE и проверен unit-тестами.

## Ложная captcha на 200 (M16a)

Замер координатора 18.09.2026: `lowendtalk.com/categories/offers` через
`abg-curl_cffi:m2` вернул HTTP 200, title «Offers — LowEndTalk» и 222 365 байт
настоящего форумного листинга. Детектор выдал `captcha` по меткам
`body_cf_challenge_platform` и `body_captcha`: служебный скрипт Cloudflare
`/cdn-cgi/challenge-platform/scripts/jsd/main.js` и невидимый reCAPTCHA v3
встретились на обычной странице. Без `expected_text` это вызывает лишнюю
эскалацию через `interactive_challenge`.

Прежде `captcha_confirmed` принимал любую одну решающую body-метку как
подтверждение captcha-атрибута. Теперь требуется `body_enough`: title
«just a moment» либо две решающие body-метки. Заголовок `cf-mitigated` и
статусы 403/429 остаются подтверждением; порядок вердиктов сохранён.
На подготовленной фикстуре `lowendtalk_200_grecaptcha.html` (7943 байта)
HTTP 200 теперь даёт `none`, сохраняя обе названные метки; HTTP 403 даёт
`captcha`, добавление второй решающей метки — `suspected`.
`body_captcha` остаётся `assumed`: наличие атрибута не доказывает челлендж.

В M16a выполнены только офлайн-проверки. Выигрыш на проде и предположение,
что остальные цели матрицы не затронуты, проверяются после выкладки в M16b.

### Интерактивный виджет (M16a-fix)

Ревью Codex обнаружило обратную сторону M16a: заслон на HTTP 200 с одной
меткой Cloudflare и интерактивным виджетом, обычным title и без `cf-mitigated`
получал `none`. Без `expected_text` продукт принимал его текст за целевой
контент. При этом `captcha` превращается в `interactive_challenge` и ведёт
прямо в `Step.human`, останавливая лестницу без попытки браузера;
`suspected` и `access_denied` ведут к браузеру.

Ключ различения — разметка: классы `g-recaptcha`, `h-captcha`, `cf-turnstile`,
атрибут `data-sitekey` или подключение `recaptcha/api.js` без параметра
`render=`. Они дают отдельную метку `body_captcha_interactive`, независимо
от прежней `body_captcha`. Невидимая reCAPTCHA v3 (`api.js?render=…`,
`grecaptcha.ready`, `grecaptcha.execute`) этой метки не даёт. В сохранённой
фикстуре lowendtalk есть только v3; интерактивных меток нет ни в одной из
четырёх существующих фикстур.

В M16a-fix2 уточнены три краевых случая: `render=explicit` обозначает
интерактивный рендер, в том числе вместе с `onload=` и при повторных
параметрах `render=`; остальные значения `render=` остаются невидимой v3.
Содержимое `<template>` инертно и не даёт интерактивной метки; вложенность
учитывается счётчиком, после закрытия шаблона распознавание возобновляется.

В M16a-fix3 устранён лимит Python в 4300 цифр при разборе десятичных
числовых сущностей: он учитывает и ведущие нули. Общий помощник снимает
ведущие нули, а ссылки с восемью и более оставшимися цифрами заменяет на
U+FFFD — их значения заведомо вне Unicode. Клипование стоит на всех трёх
маршрутах: в `detect_challenge` сразу после декодирования тела, в
`html_to_text` перед `feed` и в `_title` перед `unescape`. Ссылки без `;`
обрабатываются так же; шестнадцатеричные ссылки не затрагиваются, поскольку
их преобразование не ограничено этим лимитом. Сущности в тексте и атрибутах
больше не обрывают разбор: виджет после них распознаётся, статус и метки
сохраняются, извлечение текста продолжается до конца. Общий перехват
исключений вокруг `widget.feed` удалён, чтобы не скрывать будущие ошибки.
Самозакрытый `<template/>` открывает инертный шаблон до `</template>`, как
в HTML; самозакрытый `<div data-sitekey="k"/>` остаётся видимым виджетом.

В M16a-fix4 то же правило применяется в продуктовом форматтере
`gateway/format_html.py`: `Document.__init__` нормализует десятичные ссылки
перед `feed`, снимая ведущие нули и заменяя значения с восемью и более
оставшимися цифрами на U+FFFD, с сохранением необязательной `;` у остальных
ссылок и без изменений шестнадцатеричных ссылок. Это закрывает лимит 4300
цифр в тексте и атрибутах для `markdown`, `links` и `meta`, который после
успешного детекта превращал ответ страницы в HTTP 500 `internal_error`;
форматы `text` и `html` по-прежнему берутся из готового исхода. Помощник
осознанно дублируется: пробник монтируется в контейнер провайдера одним
самодостаточным файлом, без пакета `gateway`.

Теперь `captcha` требует интерактивной метки и подтверждения: хотя бы одной
решающей body-метки CF либо статуса 403/429. Заголовок и достаточный набор
body-меток по-прежнему определяют вердикт раньше этой ветки. Недостижимые
в ней подтверждения `header_names` и `body_enough` удалены.

| Вход | После M16a | После M16a-fix |
| --- | --- | --- |
| Фикстура lowendtalk, 200 | `none` + обе метки | Без изменений |
| Фикстура lowendtalk, 403 | `captcha` | `access_denied` |
| Одна метка CF + `<div class="g-recaptcha" data-sitekey=…>`, 200 | `none` | `captcha` |
| Тот же виджет без меток CF, 200 | `none` | `none` (обычная форма логина) |
| Интерактивный виджет без меток CF, 500 или 404 | `none` | `none` (подтверждают только 403/429) |
| Неинтерактивный captcha-атрибут, 403 | `captcha` | `access_denied` |
| Неинтерактивный captcha-атрибут, 429 | `captcha` | `rate_limited` |

Обе captcha-метки остаются `assumed`: разметка виджетов — предположение,
а не документированный контракт. Координатор воспроизвёл таблицу на
прототипе 18.09.2026; полнота распознавания реальных интерактивных виджетов
и результат в продукте проверяются после выкладки M16b.

### После выкладки M16b

18.09.2026 на stand-host развёрнут release
`ae72bfe1bae927a0297edfa273632df14ac89689`, образ `abg-runtime:ae72bfe1bae9`,
image ID `sha256:ada25963a6592dab44996b00c8fa9d5495631a00d2c920d73252765a64190b43`.
AC-942 подтвердил healthy API, соответствие release/образа и стабильный монитор.
Непосредственный откат — `58d3b738a808af71ebed84df261e87754747ee0a`;
исходный `compose.env` сохранён байт-в-байт в `compose.env.pre-m16b` (0600).
Четыре прежних release, их manifests и образы, прежние копии конфигурации
сохранены. Провайдерский `abg-curl_cffi:m2` не пересобирался: новый
`bench/providers/docker/probe.py` подключается из каталога release.

В этот же release входит правка продуктового форматтера **M16a-fix4**:
гигантские десятичные числовые ссылки больше не обрывают `markdown`, `links`
и `meta` с HTTP 500. Проверку 500 → 200 для этих трёх форматов координатор
выполнил на стенде до выкладки; на production враждебную страницу не
подкладывали и отдельную живую проверку форматтера не выполняли.

Улики первого прогона: `/home/user/.cache/abg-coord-20260918/m16b/`.
Таблица взята из `targets.json` (точная сохранённая копия —
`targets-initial.json`) и неизменяемого архива `bizprofile-20260918T090728Z.json`.
`deploy-initial.json`, `profiles-initial.json`, `api-egress-initial.json`
сохраняют исходные измерения перед повтором машинной приёмки.
Ступени: **provider/status/challenge/elapsed_ms/next_step**;
все попытки восьми строк ниже — `egress_profile=direct`.
Полное время API включает запуск и уборку контейнеров и не равно сумме
времён провайдеров.

| Цель / страница | Провайдер успеха | Лестница попыток | API elapsed, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` | `curl_cffi/200/none/344/stop` | 1190 |
| control-static | `curl_cffi` | `curl_cffi/200/none/174/stop` | 919 |
| cf-lowendtalk | `curl_cffi` | `curl_cffi/200/none/212/stop` | 1036 |
| cf-bizprofile | `scrapling` | `curl_cffi/403/suspected/179/browser` → `patchright/403/suspected/1135/browser` → `scrapling/200/none/15865/stop` | 20577 |
| cf-spa-chatgpt-share | `curl_cffi` | `curl_cffi/200/none/1422/stop` | 2759 |
| login-instagram | `patchright` | `curl_cffi/200/none/1155/browser` → `patchright/200/none/2573/stop` | 5639 |
| bizprofile главная (без expected_text) | `scrapling` | `curl_cffi/403/suspected/176/browser` → `patchright/403/suspected/1271/browser` → `scrapling/200/none/17600/stop` | 22404 |
| bizprofile Elevate Electric LLC (без expected_text) | `scrapling` | `curl_cffi/403/suspected/184/browser` → `patchright/403/suspected/1237/browser` → `scrapling/200/none/17135/stop` | 21703 |

Матрица — **6/6**, CLI: rc=0, `Example Domain` найден. Обе страницы bizprofile
без `expected_text` прошли через Scrapling: локальные маркеры найдены,
последние попытки имеют `success=true`, `challenge=none`, `error_type=none`.
Все шесть лестниц начинаются с `curl_cffi/direct`.
AC-944 подтвердил 15 уникальных рабочих egress-профилей, отличных от direct,
HTTP 407 без авторизации и ротацию API `ms1 → ms2 → ms3`.

**LowEndTalk без expected_text — до и после.** Отдельный запрос к
`https://lowendtalk.com/` выполнен ровно один раз через deployed API,
с `format=text`, `budget_ms=120000`, `allow_browser=true`, `max_age_hours=0`;
ключ `expected_text` отсутствовал. Полный ответ — `lowendtalk.json`,
параметры — `lowendtalk-request.json`, HTTP-статус API — `lowendtalk-http.json`.
Это отдельное измерение от строки `cf-lowendtalk` матрицы с ожидаемым текстом.

| Замер | Итог | Лестница provider/status/challenge/elapsed_ms/next_step | API elapsed, мс |
|---|---|---|---|
| До: координатор, 18.09, `58d3b73…` | `ok=false`, `interactive_challenge`, `step=human` | `curl_cffi/не указан/captcha/275/human` | не указан |
| После: M16b | `ok=true`, `error_type=none`, `step=stop` | `curl_cffi/200/none/213/stop` | 1110 |

В исходном замере координатора из спецификации HTTP-статус попытки и полное
время API не приведены; 275 мс — время единственной попытки. До фикса
лестница останавливалась сразу и браузер не пробовала. После фикса первая
попытка вернула HTTP 200 с `challenge=none`, результат принят без браузера;
сочетания `captcha` + `next_step=human` в ответе нет (AC-946).
Это подтверждение исчезновения ложной captcha на данном живом ответе,
а не проверка всех видов интерактивных челленджей.

**Сравнение матрицы с M15b.** База —
`/home/user/.cache/abg-coord-20260917/m15b/targets.json`, точная копия —
`m16b/m15b-targets-baseline.json`. Это последний сохранённый прогон M15b,
а не его первоначальная таблица выше.

| Цель | M15b: исход / API мс | M16b: исход / API мс | Изменение времени, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` / 1163 | `curl_cffi` / 1190 | +27 |
| control-static | `curl_cffi` / 932 | `curl_cffi` / 919 | -13 |
| cf-lowendtalk | `curl_cffi` / 1105 | `curl_cffi` / 1036 | -69 |
| cf-bizprofile | `scrapling` / 23974 | `scrapling` / 20577 | -3397 |
| cf-spa-chatgpt-share | `curl_cffi` / 2829 | `curl_cffi` / 2759 | -70 |
| login-instagram | `patchright` / 5356 | `patchright` / 5639 | +283 |

Все шесть успешных исходов и провайдеры успеха сохранились.
У `cf-lowendtalk` прежняя метка `captcha` сменилась на `none`; в M15b
страница принималась только благодаря совпавшему `expected_text`.
В выбранной базе M15b ChatGPT share уже проходил через `curl_cffi`;
HTTP-таймаут с переходом к браузеру из первоначального прогона M15b здесь не повторялся.
Разница времени — наблюдение единичных прогонов, не статистическая оценка
ускорения. Честных внешних отказов в первом прогоне M16b не было.

### Нормализация URL виджета (M16a-fix7)

Перед разбором фрагмента и query атрибут `src` нормализуется по правилу
WHATWG URL: сначала удаляются все табы, LF и CR (U+0009, U+000A, U+000D),
затем ведущие и замыкающие C0-управляющие и пробел (U+0000–U+0020).
Без этого детектор пропускал интерактивный виджет, который браузер загружает.
Координатор 18.09.2026 проверил в живом Chrome через
`new URL(src, 'https://example.test/')`: пробел после `render=explicit`,
пробел перед путём, LF в конце и таб внутри `exp\tlicit` нормализуются
до пути `/recaptcha/api.js` и `render=explicit`. Это замер парсера URL,
а не загрузки реального виджета. Пробел внутри значения значим:
`render= explicit` сохраняет его и остаётся невидимой v3 для детектора.
Значение параметра отдельно не обрезается; пробел перед `&` или `#`
также сохраняется. Источник замера — спецификация M16a-fix7;
`urllib.parse` не используется как эталон браузерной нормализации.

### Соответствие разбору браузера (M16a-fix8)

Детектор повторяет браузерный разбор в четырёх местах: NUL в значениях
атрибутов заменяется на U+FFFD до обработки URL; токены `class` разделяются
только ASCII-пробелами (SP, TAB, LF, FF, CR), поэтому NBSP и вертикальная
табуляция остаются внутри токена; обратный слэш в `src` заменяется на `/`,
как при разборе HTTP(S) URL; краевые C0 и пробел удаляются линейным
`str.strip`, после удаления TAB/LF/CR и замены слэшей, до разбора фрагмента
и query. Первые два расхождения давали ложную `captcha`, третье — ложный
`none`, а квадратичная обрезка расходовала бюджет запроса и мешала вовремя
получить вердикт. При `class="g-recaptcha foo"` на 403 остаются
`access_denied` и метки `body_captcha`, `status_403`: общее правило атрибутов
не меняется. Пробел внутри значения `render` по-прежнему значим.
Основание — [замеры координатора от 18.09.2026 в Chrome и Docker](../specs/m16a-fix8-browser-parity.md#зачем):
браузер проверялся через `createHTMLDocument`, `classList` и `new URL`;
обрезка регуляркой на 4000/8000/16000 внутренних пробелах занимала
0,092/0,382/1,235 с, а `str.strip` на том же входе — 0,000015 с.
Регрессионный тест ограничивает разбор 32000 внутренних пробелов двумя секундами.

В M16a-fix9 замена обратного слэша уточнена по схеме URL: она применяется
только к относительным значениям и special-схемам `http`, `https`, `ws`,
`wss`, `ftp`, `file` без учёта регистра. В `data:`, `blob:`, `javascript:`
обратный слэш сохраняется. Порядок обработки теперь: NUL → U+FFFD,
удаление TAB/LF/CR, обрезка краёв, определение схемы и условная замена
слэшей, затем разбор фрагмента и query. Из дублирующихся атрибутов
сохраняется первый: `class="foo" class="g-recaptcha"` не создаёт виджет,
а `src="one.js" src="recaptcha/api.js?render=explicit"` не подключает
reCAPTCHA. Основание — [замеры координатора в Chromium от 18.09.2026](../specs/m16a-fix9-scheme-and-duplicates.md#что-проверено-вживую-а-что-предположение)
в `abg-playwright:m2` (`new URL`, `classList`, `createHTMLDocument`,
provider_version 1.62.0, `--network none`).

### После выкладки M16c

18.09.2026 на stand-host развёрнут release
`db4fc359171c304470d7edae3d60cb13394e7881`, образ `abg-runtime:db4fc359171c`,
image ID `sha256:632f783a9b7cf0cd22f368314f1a2d71daaf8c02d0e503bd2bca733ccbc07485`.
Непосредственный откат — `ae72bfe1bae927a0297edfa273632df14ac89689`;
`compose.env.pre-m16c` хранит исходную конфигурацию байт-в-байт (0600).
В `compose.env` изменены только `ABG_RELEASE` и `ABG_RUNTIME_IMAGE`.
Прежние release, manifests, образы и копии конфигурации сохранены.
Провайдерский `abg-curl_cffi:m2` не пересобирался: детектор подключается
из каталога release, и его SHA-256 совпадает с файлом в BASE (AC-951).

**Что приехало.** Буквальный NUL в HTML-атрибуте заменяется на U+FFFD,
поэтому `render=explicit\x00` не становится интерактивным виджетом.
`class` разбивается только по ASCII-пробелам: NBSP внутри
`g-recaptcha<NBSP>foo` оставляет один токен. Обратный слэш в относительном
`src="recaptcha\api.js?render=explicit"` становится разделителем пути,
и виджет распознаётся. Краевая обрезка C0/пробелов использует линейный
`str.strip` вместо квадратичной регулярки. В BASE также уже включено
уточнение M16a-fix9: обратные слэши нормализуются с учётом схемы URL,
а из дублирующихся атрибутов сохраняется первый.

**Выложенный детектор, офлайн (AC-956).** Импортирован именно
`releases/db4fc359171c304470d7edae3d60cb13394e7881/bench/providers/docker/probe.py`.
Каждая фикстура обёрнута в HTML с `cf_chl_opt`, статус 200, заголовки пусты.
Улика — `detector-offline.json` в
`/home/user/.cache/abg-coord-20260918/m16c/`.

| Фикстура | Ожидание | Результат |
|---|---|---|
| `src="recaptcha/api.js?render=explicit\x00"`, буквальный NUL | `none` | `none` |
| `class="g-recaptcha<NBSP>foo"` | `none` | `none` |
| `class="g-recaptcha<TAB>foo"` | `captcha` | `captcha` |
| `src="recaptcha\api.js?render=explicit"` | `captcha` | `captcha` |

Разбор `render=` + 32 000 внутренних пробелов + `explicit` занял
0.001475468 с при лимите <2 с; результат — `none`. Это единичный
замер полного детектора, а не отдельного `str.strip`. Все четыре фикстуры
прошли. Синтетические страницы в production не подавались; живые проверки
ниже проверяют отсутствие регресса на прежних целях. Unit: 613 тестов, OK
(AC-950, закреплённый Python-образ, сеть отключена).

**Живые результаты.** AC-952 подтвердил healthy API, соответствие release/образа
и стабильный монитор. Улики — `/home/user/.cache/abg-coord-20260918/m16c/`.
Таблица взята из `targets-initial.json` (копия `targets.json`) и
`bizprofile-20260918T154152Z.json`. `deploy-initial.json`, `profiles-initial.json`,
`api-egress-initial.json` сохраняют первое измерение.
Ступени: **provider/status/challenge/elapsed_ms/next_step**;
все попытки восьми строк ниже — `egress_profile=direct`.
Время API включает запуск и уборку контейнеров.

| Цель / страница | Провайдер успеха | Лестница попыток | API elapsed, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` | `curl_cffi/200/none/378/stop` | 1330 |
| control-static | `curl_cffi` | `curl_cffi/200/none/165/stop` | 1010 |
| cf-lowendtalk | `curl_cffi` | `curl_cffi/200/none/318/stop` | 1261 |
| cf-bizprofile | `scrapling` | `curl_cffi/403/suspected/176/browser` → `patchright/403/suspected/1361/browser` → `scrapling/200/none/16471/stop` | 21976 |
| cf-spa-chatgpt-share | `curl_cffi` | `curl_cffi/200/none/1352/stop` | 2862 |
| login-instagram | `patchright` | `curl_cffi/200/none/922/browser` → `patchright/200/none/2250/stop` | 5357 |
| bizprofile главная (без expected_text) | `scrapling` | `curl_cffi/403/suspected/200/browser` → `patchright/403/suspected/1181/browser` → `scrapling/200/none/18156/stop` | 22974 |
| bizprofile Elevate Electric LLC (без expected_text) | `scrapling` | `curl_cffi/403/suspected/189/browser` → `patchright/403/suspected/1329/browser` → `scrapling/200/none/18587/stop` | 23723 |

Матрица — **6/6**, CLI rc=0, `Example Domain` найден. Обе страницы bizprofile
без `expected_text` прошли через Scrapling, локальные маркеры найдены;
последние попытки имеют `success=true`, `challenge=none`, `error_type=none`.
Все шесть лестниц начинаются с `curl_cffi/direct` (AC-955).

**LowEndTalk без expected_text (AC-957).** Выполнен ровно один отдельный запрос
через deployed API: `format=text`, `budget_ms=120000`, `allow_browser=true`,
`max_age_hours=0`, ключ `expected_text` отсутствует. Полный ответ сохранён
в `lowendtalk.json`, параметры — `lowendtalk-request.json`, HTTP-статус API —
`lowendtalk-http.json`. Повтора этого запроса нет.

| Замер | Итог | Лестница provider/status/challenge/elapsed_ms/next_step | API elapsed, мс |
|---|---|---|---|
| M16b: замер координатора из спеки | `ok=true`, `curl_cffi` | `curl_cffi/200/none/213/stop` | не указан |
| M16c | `ok=true`, `curl_cffi` | `curl_cffi/200/none/364/stop` | 1344 |

Регресса на этом ответе нет: HTTP 200, `challenge=none`, сочетание
`captcha` + `next_step=human` отсутствует. Отдельный замер не смешивается
со строкой `cf-lowendtalk` матрицы, где есть ожидаемый текст.

**Сравнение с M16b.** База — последний сохранённый
`/home/user/.cache/abg-coord-20260918/m16b/targets.json`, точная копия —
`m16b-targets-baseline.json`. Это иной прогон, чем первоначальная таблица M16b выше.

| Цель | M16b: исход / API мс | M16c: исход / API мс | Изменение времени, мс |
|---|---|---|---|
| control-hqd | `curl_cffi` / 1262 | `curl_cffi` / 1330 | +68 |
| control-static | `curl_cffi` / 981 | `curl_cffi` / 1010 | +29 |
| cf-lowendtalk | `curl_cffi` / 1288 | `curl_cffi` / 1261 | -27 |
| cf-bizprofile | `scrapling` / 22629 | `scrapling` / 21976 | -653 |
| cf-spa-chatgpt-share | `curl_cffi` / 4643 | `curl_cffi` / 2862 | -1781 |
| login-instagram | `patchright` / 5228 | `patchright` / 5357 | +129 |

Все шесть успешных исходов и провайдеры успеха сохранились. Разница времени
между единичными прогонами не доказывает ускорение или замедление.

**Незакрытый AC-954: ротация egress.** `--check-profiles` прошёл: 13 уникальных
рабочих адресов, отличных от direct; `ms3` и `ms14` дали `connection_error`;
без авторизации получен HTTP 407. Затем `--check-api-egress` завершился
rc=1 с `worker_internal_error`. В `api-egress-initial.json` сохранены:

| Запрос | Итог | Лестница provider/status/challenge/elapsed_ms/next_step | API elapsed, мс |
|---|---|---|---|
| anchor, direct → ms1 | `ok=true`, `none` | `curl_cffi/200/none/167/change_egress` → `curl_cffi/200/none/184/stop` | 1847 |
| required_success, direct → ms2 | `ok=true`, `none` | `curl_cffi/200/none/238/change_egress` → `curl_cffi/200/none/189/stop` | 1888 |
| intermediate, direct → ms3 | `ok=false`, `content_missing` | `curl_cffi/200/none/157/change_egress` → `curl_cffi/200/none/200/human` | 1856 |

`ms3` во время API-запроса уже вернул 200, но ожидаемый текст промежуточной
проверки отсутствовал. Следующий запрос (ожидался `ms4`) не сохранён:
runner скрыл причину ошибки worker и не записал его ответ. `rotation_proven`
отсутствует. По доступным уликам нельзя назвать этот сбой честным внешним
отказом или дефектом детектора. API остался healthy, контейнеры без
перезапусков, журнал API пуст (`rotation-failure-diagnostics.json`).
Повторы ради успешного исхода не выполнялись, runner и код не менялись.

Обязательные условия отката (`up`/AC-952, AC-956, ложная captcha на HTTP 200)
не сработали; сервис оставлен на `db4fc359171c304470d7edae3d60cb13394e7881`.

**Разбор координатора (18.09.2026, после сдачи панели).** `worker_internal_error`
— это метка `tests/deployed_m12b.py:212` на ЛЮБОЙ отказ воркер-контейнера
оснастки: под ней неразличимо лежат `worker_timeout`, `worker_connection` и
`worker_failure`, а в `worker_failure` попадает в том числе разбор ответа
шлюза — то есть HTTP 500 или неожиданная схема ответа дали бы ровно такой же
код. **Поэтому по этому сигналу нельзя ни доказать, ни исключить разовый отказ
шлюза; логи контейнеров пусты, других улик по тому запросу нет.** Первая
редакция этого раздела утверждала «ошибка оснастки, а не шлюза» — это было
сказано сильнее, чем позволяют улики (находка Codex 18.09.2026).
Что перепрогон действительно показывает:

| Проверка | Панель | Перепрогон координатора |
|---|---|---|
| `--check-profiles` | 13 рабочих, отвалились `ms3` и `ms14` | 14 рабочих, отвалился `ms7` |
| `--check-api-egress` | rc=1, `worker_internal_error` | **`ok=true`**: direct → `ms15` (`content_missing`) → `ms1` → `ms2`, ротация состоялась |

Отваливаются РАЗНЫЕ профили от прогона к прогону, а при повторе вся проверка
проходит на том же коде — то есть отказ не воспроизводится и с выложенным
кодом не связан жёстко. Это довод в пользу приёмки, но НЕ доказательство
невиновности шлюза: одиночный HTTP 500 тоже не воспроизвёлся бы. Кроме того,
ровно такой же одиночный отказ
`content_missing`/`human` на anchor-запросе был и в M16b, которую приняли.
Улики перепрогона — `/home/user/.cache/abg-coord-20260918/m16c-coord/`.
Дополнительно координатор проверил вживую: выложенный `probe.py` байт-в-байт
равен коду релиза (SHA256 `b87e4458…`), AC-956 прогнан ПРЯМО НА ВЫЛОЖЕННОМ
файле — rc=0, healthchecks `ai-browser-gateway-health` в статусе `up` без
падений. Выкладка принята при незакрытом AC-954: риск — один неразобранный
запрос, цена отката — потеря четырёх исправлений ложной `captcha`.

**Побочный ущерб от самой проверки (находка Codex 18.09.2026).** Команда AC-956
запускала `python3` на хосте и грузила выложенный `probe.py` через
`importlib`, поэтому Python записал `bench/providers/docker/__pycache__/probe.cpython-314.pyc`
ВНУТРЬ каталога боевого релиза. Файла нет в manifest, и `verify_release` начал
воспроизводимо падать с `release_integrity_failed` — то есть проверка целостности
релиза, которую AC-952 и AC-953 обязаны проходить, сломалась о собственную
проверку вехи. Координатор удалил каталог `__pycache__`; после этого
`verify_release` проходит для `db4fc35…` и для отката `ae72bfe…`. Урок для
будущих спек: проверка выложенного артефакта обязана быть только для чтения —
Docker с `-v …:ro`, `PYTHONDONTWRITEBYTECODE=1` либо `python3 -B`.

Долг оснастки на отдельную задачу: сохранять настоящую причину отказа воркера
(`worker_timeout` / `worker_connection` / `worker_failure` и текст ошибки),
иначе честный сбой прокси неотличим от дефекта продукта — как и вышло здесь.
