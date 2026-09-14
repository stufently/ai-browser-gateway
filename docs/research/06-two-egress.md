# M10 — два egress: direct vs ms1 на принятом fetch_page

Замер 14.09.2026. Провайдеры `curl`, `patchright`, `scrapling` на шести
действительных целях `bench/targets/targets.toml`. По одному холодному
запросу на клетку, `budget_ms=120000`, пауза к одному hostname ≥ 30 с.
Браузеры строго последовательно. Тот же код/образы/настройки на обоих
адресах. Успех — `evaluate()` принятого M9.

**Прямой ответ:** на текущих `192.0.2.10` (direct, stand-host/Hetzner) и
`198.51.100.21` (ms1, MassiveGRID) матрица покрытия совпала. Unique
scrapling на `cf-bizprofile` после 403 curl и patchright повторился на
обоих IP. Смена адреса на этой паре покрытия не добавила.

Сырьё — `docs/research/data/m10-egress.jsonl`.

# Отчёт прогона

## Окружение

| Поле | Наблюдения |
|---|---|
| date | 2026-09-14T21:41:19.201015+00:00 |
| kernel | 7.0.0-31-generic |
| docker_version | Docker version 29.8.0, build 88096ef |
| tree | f3c391371b8cf4d4718fad4013bd051b1e5874a2 |
| provider_version | curl: 7.88.1; patchright: 1.62.3; scrapling: 0.4.15 |
| image_version | curl: abg-curl:m2; patchright: abg-patchright:m2; scrapling: abg-scrapling:m8 |
| image_id | curl `sha256:1394d8086001b20885891660905119b8acb12f62d70239f3fb09d86dd2923438`; patchright `sha256:68c4a2c7e015695d310bed8dbebcd33b9c88f32194ffc357d8d84f3c22f0f124`; scrapling `sha256:49097cbdff09cc0ad5104948385c8825441f9b85cc31b4982c698aad80ff2cdd` |
| egress_profile | direct и ms1, по 18 попыток |

Echo до матрицы: direct `192.0.2.10`, ms1 `198.51.100.21`. ASN в JSONL
`unknown`; отдельный ipinfo после echo: AS24940 Hetzner / AS49683 MASSIVEGRID.

M8 был `198.51.100.30` AS206996 — другой адрес.

## Incremental coverage

Порядок `curl → patchright → scrapling`. Считано `bench.report.coverage`.

### direct `192.0.2.10`

| Провайдер | Взял | Incremental | Unique |
|---|---|---|---|
| curl | 3 | 3 | 0 |
| patchright | 5 | 2 | 0 |
| scrapling | 6 | 1 | 1 (`target:cf-bizprofile`) |

### ms1 `198.51.100.21`

| Провайдер | Взял | Incremental | Unique |
|---|---|---|---|
| curl | 3 | 3 | 0 |
| patchright | 5 | 2 | 0 |
| scrapling | 6 | 1 | 1 (`target:cf-bizprofile`) |

## Провайдер × цель

Успех — sentinel найден и ответ не отказ (`evaluate`). `challenge` — метаданные
детектора, они не отменяют найденный sentinel.

| Провайдер | Цель | direct успех | direct challenge | ms1 успех | ms1 challenge |
|---|---|---|---|---|---|
| curl | control-hqd | да | none | да | none |
| curl | control-static | да | none | да | none |
| curl | cf-lowendtalk | нет http_403 | suspected | нет http_403 | suspected |
| curl | cf-bizprofile | нет http_403 | suspected | нет http_403 | suspected |
| curl | cf-spa-chatgpt-share | да | none | да | none |
| curl | login-instagram | нет content_missing | none | нет content_missing | none |
| patchright | control-hqd | да | none | да | none |
| patchright | control-static | да | none | да | none |
| patchright | cf-lowendtalk | да | captcha | да | captcha |
| patchright | cf-bizprofile | нет http_403 | suspected | нет http_403 | suspected |
| patchright | cf-spa-chatgpt-share | да | none | да | none |
| patchright | login-instagram | да | none | да | none |
| scrapling | control-hqd | да | none | да | none |
| scrapling | control-static | да | none | да | none |
| scrapling | cf-lowendtalk | да | captcha | да | captcha |
| scrapling | cf-bizprofile | да | suspected | да | suspected |
| scrapling | cf-spa-chatgpt-share | да | none | да | none |
| scrapling | login-instagram | да | none | да | none |

## sentinel-found при challenge ≠ none

Продуктовый URL-only критерий (challenge none, без sentinel) не приравнивает
эти строки к бесспорному успеху. Под ним unique scrapling на bizprofile
пропадает: бесспорно scrapling и patchright берут одни и те же 4 цели.

| target | provider | egress | challenge | evaluate |
|---|---|---|---|---|
| cf-lowendtalk | patchright | direct, ms1 | captcha | успех |
| cf-lowendtalk | scrapling | direct, ms1 | captcha | успех |
| cf-bizprofile | scrapling | direct, ms1 | suspected | успех |

## Задержка и память

| Провайдер | Egress | Медиана, мс | p95, мс | Пиковый RSS, МиБ |
|---|---|---|---|---|
| curl | direct | 223 | 1297 | 77.79 |
| curl | ms1 | 243.5 | 1345 | 79.09 |
| patchright | direct | 2506.5 | 6441 | 2206.40 |
| patchright | ms1 | 2313 | 6705 | 2177.11 |
| scrapling | direct | 7024 | 18033 | 2153.42 |
| scrapling | ms1 | 6403 | 17453 | 2131.73 |

## Следствие для лестницы

На этой паре адресов 403 curl/patchright на bizprofile не лечится сменой
egress; лечится scrapling по evaluate. `next_step` на 403 по-прежнему
`change_egress` и scrapling не зовёт. Для product-меню: HTTP → patchright →
scrapling → затем egress. Один холодный запрос не гарантия стабильности.
Новых серий этот файл не предлагает.
