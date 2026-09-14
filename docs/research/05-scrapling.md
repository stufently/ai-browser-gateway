# M8 — Scrapling: добавляет ли он хоть одну цель к patchright

Замер 14.09.2026. Провайдер `scrapling` (StealthySession, `solve_cloudflare=True`,
настоящий Chrome headful под Xvfb, таймаут 120 с) против `patchright` и `curl`
на шести действительных целях `bench/targets/targets.toml`. По одному холодному
запросу на пару, пауза к одному хосту ≥ 30 с.

**Прямой ответ:** да. `scrapling` взял `cf-bizprofile`, которую `patchright`
на этом же прогоне получил `403` / `http_403`. Incremental coverage, посчитанный
боевым кодом `bench.report.coverage` / `keep_set` при порядке
`curl → patchright → scrapling`: **incremental 1, unique 1**.

Таблицы ниже — вывод `python3 -m bench report docs/research/data/m8-scrapling.jsonl --order curl patchright scrapling`.
Сырьё — `docs/research/data/m8-scrapling.jsonl`.

# Отчёт прогона

## Окружение

| Поле | Наблюдения |
|---|---|
| date | 2026-09-14T07:36:46.276690+00:00 |
| kernel | 7.0.0-31-generic |
| docker_version | Docker version 29.8.0, build 88096ef |
| egress_ip | 198.51.100.30 |
| asn | AS206996 ZAP-Hosting GmbH |
| provider_version | curl: 7.88.1; patchright: 1.62.3; scrapling: 0.4.15 |
| image_version | curl: abg-curl:m2; patchright: abg-patchright:m2; scrapling: abg-scrapling:m8 |
| egress_profile | direct |

## Провайдер × ячейка

Успешных / измеренных попыток; пропуски — не измерено.

| Провайдер | target:cf-bizprofile | target:cf-lowendtalk | target:cf-spa-chatgpt-share | target:control-hqd | target:control-static | target:login-instagram |
|---|---|---|---|---|---|---|
| curl | 0/1 | 0/1 | 1/1 | 1/1 | 1/1 | 0/1 |
| patchright | 0/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| scrapling | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |

## Задержка и память

Метрики всех измеренных попыток, включая HTTP-отказы. p95: ближайший ранг ceil(0.95 × n).
Нулевые заглушки метрик при отказе запуска/протокола исключены; покрытие включает измеренные попытки.

| Провайдер | Режим | Измерений | Медиана, мс | p95, мс | Пиковый RSS, МиБ |
|---|---|---|---|---|---|
| curl | cold | 6 | 238.00 | 2600.00 | 76.15 |
| patchright | cold | 6 | 2048.50 | 6275.00 | 2213.98 |
| scrapling | cold | 6 | 6451.50 | 17632.00 | 2160.02 |

## Incremental coverage

| Провайдер | Взял | Incremental | Unique | Решение | Измерение |
|---|---|---|---|---|---|
| curl | 3 | 3 | 0 | оставить: клетка `target:cf-spa-chatgpt-share`; клетка `target:control-hqd`; клетка `target:control-static` | покрытие |
| patchright | 5 | 2 | 0 | оставить: клетка `target:cf-lowendtalk`; клетка `target:login-instagram` | покрытие |
| scrapling | 6 | 1 | 1 | оставить: клетка `target:cf-bizprofile` | покрытие |

## Провайдер × цель: время и пиковый RSS

| Провайдер | Цель | Успех | elapsed_ms | peak_rss_mb | error_type | challenge |
|---|---|---|---|---|---|---|
| scrapling | control-hqd | да | 7007 | 1818.891 | none | none |
| scrapling | control-static | да | 2184 | 1508.738 | none | none |
| scrapling | cf-lowendtalk | да | 5612 | 2108.727 | none | captcha |
| scrapling | cf-bizprofile | да | 17632 | 2160.016 | none | suspected |
| scrapling | cf-spa-chatgpt-share | да | 8840 | 2082.109 | none | none |
| scrapling | login-instagram | да | 5896 | 1852.215 | none | none |
| patchright | control-hqd | да | 1462 | 1766.117 | none | none |
| patchright | control-static | да | 1033 | 1561.410 | none | none |
| patchright | cf-lowendtalk | да | 1899 | 2149.645 | none | captcha |
| patchright | cf-bizprofile | нет | 6275 | 2213.984 | http_403 | suspected |
| patchright | cf-spa-chatgpt-share | да | 4389 | 2023.004 | none | captcha |
| patchright | login-instagram | да | 2198 | 1854.656 | none | captcha |
| curl | control-hqd | да | 334 | 47.648 | none | none |
| curl | control-static | да | 84 | 47.223 | none | none |
| curl | cf-lowendtalk | нет | 142 | 47.277 | http_403 | suspected |
| curl | cf-bizprofile | нет | 142 | 47.520 | http_403 | suspected |
| curl | cf-spa-chatgpt-share | да | 2600 | 76.152 | none | none |
| curl | login-instagram | нет | 469 | 48.000 | content_missing | none |

Успех — sentinel из `expect` найден и ответ не отказ. `challenge` — метаданные
детектора, они не отменяют найденный sentinel (как на стенде A). На
`cf-bizprofile` у scrapling детектор всё ещё видит `suspected`, но строка
ожидания в теле есть; у patchright той же строки нет и статус 403.

## Цена образа и RSS

| Образ | Размер слоя | Пиковый RSS этого прогона |
|---|---|---|
| `abg-scrapling:m8` | 2076.9 МиБ | 2160.02 МиБ |
| `abg-patchright:m2` | 1811.1 МиБ | 2213.98 МиБ |
| `abg-curl:m2` | 183.2 МиБ | 76.15 МиБ |

Scrapling тяжелее patchright на **~266 МиБ образа** при сопоставимом пиковом RSS
(в этом прогоне даже чуть ниже: 2160 против 2214). У patchright в замере раннера
M2 пик был 1773 МиБ — здесь оба браузера сели выше, на Instagram/CF-целях.

## `login-instagram`

Строка возвращена в строй: живой рилс
`https://www.instagram.com/reel/DdJ-MY6OITt/`,
`expect = "Кирилл Жильников on Instagram"`. Браузеры (`scrapling`, `patchright`)
нашли подпись; `curl` получил HTTP 200 без sentinel (`content_missing`). Это
первая цель набора, где браузер обходит HTTP-клиент. Меряется доступ к подписи
и мета-разметке, не к видео: видео остаётся за стеной логина.

## Оговорка про один egress

Все 18 запросов ушли с `198.51.100.30`, `AS206996 ZAP-Hosting GmbH`. Пока
второго адреса нет, «инструмент не справился» и «адрес не пустили»
неразличимы. Успех scrapling на `bizprofile.net` — это успех **с этого
адреса в этот прогон**, не доказательство, что обработчик челленджа всегда
пробьёт Cloudflare.
