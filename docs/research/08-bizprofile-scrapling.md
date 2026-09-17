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

M13a-fix4 дополнительно сохраняет заголовок, если после удаления всех
`/cdn-cgi/challenge-platform/scripts/jsd/` (UTF-8 с заменой ошибок, без учёта
регистра) остаётся любая подстрока: `turnstile`, `cf-chl`, `cf_chl`,
`challenge-platform`, `challenges.cloudflare.com`, `cf-challenge`, `cf-captcha`,
`hcaptcha`, `recaptcha`, `g-recaptcha`, `h-captcha`, `/cdn-cgi/challenge`.
Принятый остаток — только тело без этих строк вне разрешённых JSD-префиксов.

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

## После выкладки M13c

17.09.2026 на stand-host развёрнут release
`4409f8a5197f7a9f464263e15b362c00548399e2`.
Runtime image `abg-runtime:4409f8a5197f`, image ID:
`sha256:c7a84ef4061f3d2d6ae7f763718ea96c070f99092751f44dbe96f2a58acd032b`.

Источник таблицы — неперезаписываемый файл
`bizprofile-20260917T091502Z.json` в
`/home/user/.cache/abg-coord-20260917/m13c/`.
Проверка выполнена через deployed API на `127.0.0.1:8765`:
`allow_browser=true`, `budget_ms=120000`, `format=text`,
`max_age_hours=0`; ключ `expected_text` отсутствовал. Маркеры проверял
runner после `parse_api`, без передачи маркера в API.

| Страница | Provider | Попытки лестницы (HTTP / challenge / elapsed) | Последний challenge | Всего, мс | Маркер |
| --- | --- | --- | --- | --- | --- |
| Главная bizprofile.net | scrapling | curl 403 / suspected / 170 мс → patchright 403 / suspected / 1164 мс → scrapling 200 / none / 6403 мс | none | 11245 | найден |
| Карточка Elevate Electric LLC | scrapling | curl 403 / suspected / 138 мс → patchright 403 / suspected / 1054 мс → scrapling 200 / none / 17550 мс | none | 22047 | найден |

Обе страницы: `ok=true`; последняя попытка — `scrapling`, `success=true`,
`challenge=none`, `error_type=none`. Все попытки использовали `direct`.
Найдены «Comprehensive Directory of Registered Businesses» и
«Elevate Electric LLC». Запросы шли последовательно, с интервалом между
началами не менее 30 с, без повторов. Улики содержат только `api_evidence`
и `marker_found` для каждой страницы с идентификатором; content и URL
страниц в них отсутствуют. Повтор приёмки создаёт отдельный архив, поэтому
этот замер остаётся доступен независимо от нового `bizprofile.json`.

AC-893 подтвердил release/manifest, image ID, healthy API и отсутствие
ошибок в последних логах монитора после 130 с работы. Старый release
`929bded313e371808b0747fd9a400696a36638aa`, его manifest и образ
`abg-runtime:929bded313e3` сохранены для отката. Исходный `compose.env`
сохранён байт-в-байт в `compose.env.pre-m13c` (`0600`); в рабочем файле
изменены только `ABG_RELEASE` и `ABG_RUNTIME_IMAGE`.
