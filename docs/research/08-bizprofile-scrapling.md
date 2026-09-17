# Bizprofile: устаревший cf-mitigated после решённого challenge

Спецификация: [M13a](../specs/m13a-scrapling-headers.md).

## До правки: наблюдения координатора

17.09.2026, 04:55–05:10 UTC, работающий API. Эти данные взяты из
спецификации; исполнитель не повторял запросы к deployed-сервису.

| Запрос | expected_text | Результат и лестница | Время |
| --- | --- | --- | --- |
| Главная bizprofile.net | отсутствует | ok:false; curl 403 → patchright 403 → scrapling 200, suspected → curl через ms6 403 | точное суммарное время не записано |
| Главная bizprofile.net | задан | ok:true, scrapling | 21–24 с суммарно; 16,6–17,7 с Scrapling |
| Каталог /ny/albany | задан | ok:true, scrapling | тот же диапазон трёх замеров |
| Карточка /ny/albany/elevate-electric-llc | задан | ok:true, scrapling | тот же диапазон трёх замеров |

Спецификация приводит диапазоны, а не индивидуальные тайминги каждого URL.
`expected_text` позволяет продукту принять реальный контент при `suspected`;
без него `accept_page` возвращал `challenge_suspected` и продолжал лестницу.

## Причина и границы исправления

Прямой замер координатора в `abg-scrapling:m8`, UID 1002, дал для карточки
HTTP 200, настоящую страницу с заголовком «Elevate Electric LLC Albany, NY -
filing information» и один 307 в history. При этом Scrapling сохранил
`cf-mitigated: challenge` от challenge-ответа. В настоящей странице оставался
скрипт `/cdn-cgi/challenge-platform/scripts/jsd/main.js`.

| Вход детектора | Вердикт | Имена правил |
| --- | --- | --- |
| 200, заголовки Scrapling, тело страницы | suspected | header_cf_mitigated, body_cf_challenge_platform |
| 200, None, то же тело | none | body_cf_challenge_platform |

Теперь `ScraplingAdapter.navigate` удаляет только `cf-mitigated` из
нормализованного словаря, когда статус 2xx, вердикт детектора без заголовков —
`none` и все сработавшие правила входят в множество
{`body_cf_challenge_platform`, `body_noindex_nofollow`} (пустое множество тоже
допускает удаление). Если есть `body_cf_challenge_platform`, каждое вхождение
`/cdn-cgi/challenge-platform` должно продолжаться ровно `/scripts/jsd/`.
Проверка не учитывает регистр и декодирует тело так же, как детектор: UTF-8
с заменой ошибок. Путь `h/g/orchestrate/chl_page/v1`, в том числе рядом с jsd,
сохраняет заголовок. Любое другое правило, включая одиночные `body_cf_chl_opt`,
`body_cf_chl`, `body_cf_challenges_host` и `body_captcha`, сохраняет заголовок
и прежний вердикт. Остальные заголовки сохраняются, `None` остаётся
`None`, пустой словарь остаётся словарём. Не-2xx и interstitial сохраняют
заголовок и прежний вердикт. Общий детектор и политика продукта не менялись.

Остаточный риск принят владельцем 17.09.2026: при 2xx и устаревшем
`cf-mitigated` тело без CF-маркеров и с пустым набором правил, например
самописная форма captcha без атрибутов, распознаваемых `_CAPTCHA_ATTR`,
по-прежнему приводит к удалению заголовка. Эвристика тела не может отличить
такую произвольную форму от обычного контента без дополнительных признаков;
живой Cloudflare-челлендж всегда несёт CF-маркеры. Этот остаток намеренно
не закрывается в M13a-fix3.

Регрессионные тесты используют фейковый `scrapling.fetchers`, настоящий
адаптер и `run_probe` — путь расчёта `challenge`, используемый CLI. До правки
новые проверки падали на сохранённом заголовке; после правки проходят.

## После правки: live через продукт

Первый прогон `python3 tests/live_m13a_bizprofile.py` завершился с rc=0
17.09.2026 в 05:51 UTC. Оба запроса дали `ok:true`, provider `scrapling`,
HTTP 200 и `challenge=none` у успешной попытки.

| URL | Начало UTC | curl | patchright | scrapling | Продукт целиком |
| --- | --- | --- | --- | --- | --- |
| https://bizprofile.net/ | 05:50:05.131 | 403 / suspected, 129 мс | 403 / suspected, 1334 мс | 200 / none, 18255 мс | 23928 мс |
| https://www.bizprofile.net/ny/albany/elevate-electric-llc | 05:50:59.083 | 403 / suspected, 163 мс | 403 / suspected, 1167 мс | 200 / none, 16472 мс | 21250 мс |

Контент главной содержит «Comprehensive Directory of Registered Businesses»,
карточки — «Elevate Electric LLC». Проверено шесть попыток провайдеров,
все с direct egress. Между завершением первой страницы и началом второй —
30 с. Время попыток берётся из probe, общее время включает Docker-накладные
расходы. Скрипт печатает JSON только с результатами проверок и метаданными.

Продукт и assertions выполняются в Docker 1002:1002; только оркестратор
получает Docker socket. Используются существующие образы и `DockerLauncher`
с `probe.py` из клона. Запросы не задают `expected_text` и egress-профили,
разрешают браузер, имеют budget 120000 мс. Между страницами пауза 30 с;
не более шести запусков провайдеров, без повторного прогона при отказе.
