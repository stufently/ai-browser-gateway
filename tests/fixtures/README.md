# Фикстуры: настоящие тела страниц, не выдуманные

Здесь лежат **реальные** ответы, снятые с боевых целей 06.09.2026. Они нужны для
одной конкретной задачи: научиться отличать **страницу-заглушку** от **страницы,
которая пришла пустой, потому что контент дорисовывает JS**. Обе приходят с
непустым телом, и на выдуманном `<div>` эта разница не воспроизводится.

| Файл | Что это | Откуда |
|---|---|---|
| `cf_interstitial_200body_403.html` | заглушка Cloudflare Managed Challenge | `bizprofile.net`, ответ `403 cf-mitigated: challenge` |
| `js_shell_200.html` | ответ `200`, sentinel дорисовывает скрипт | сценарий `/js` стенда A |
| `real_page_head.html` | начало настоящей страницы | `lowendtalk.com/categories/offers`, `200` |
| `qrator_loader_401.html` | JS-загрузчик Qrator: пустая страница со `<script src="/__qrator/…">` | `rbc.ru`, `401`, снято 09.10.2026 |
| `perimeterx_block_429.html` | блок-страница PerimeterX; браузеру тот же сайт сразу отдаёт `200` | `wayfair.com`, `429` curl_cffi, снято 09.10.2026 |
| `akamai_access_denied_403.html` | краевой отказ Akamai «Access Denied»: бан адреса, оба браузера получают тот же `403` | `homedepot.com`, `403`, снято 09.10.2026 |
| `lowendtalk_200_grecaptcha.html` | настоящая страница `200` с невидимым reCAPTCHA и служебным скриптом Cloudflare; sitekey и параметры `__CF$cv$params` затёрты координатором | `lowendtalk.com/categories/offers`, снято 18.09.2026 |
| `cf_managed_interstitial_403.html` | заглушка Managed Challenge (`cType: 'managed'`, «Just a moment...»), тело ответа `403 cf-mitigated: challenge` | `bizprofile.net`, снято 24.11.2026 |
| `cf_passed_gitlab_signin_200.html` | страница входа ПОСЛЕ пройденного вызова (scrapling, есть `cf_clearance`); содержит слово `recaptcha`; значения `csrf-token`/`authenticity_token` затёрты | `gitlab.com/users/sign_in`, `200`, снято 24.11.2026 |
| `cf_passed_scrapingcourse_200.html` | страница ПОСЛЕ пройденного вызова; встроенный `turnstile/v0/api.js` | `scrapingcourse.com/cloudflare-challenge`, `200`, снято 24.11.2026 |
| `cf_jsd_turnstile_widget_200.html` | обычная страница `200`: пассивный JSD-скрипт и встроенный виджет Turnstile с тестовым ключом | `nowsecure.nl`, `200`, снято 24.11.2026 |

Ray ID в заглушках и в JSD-пути заменён на `RAYREDACTED0000`; ничего секретного в файлах нет.

## Почему длины текста НЕ хватает

Измерено на этих самых файлах:

| Файл | Байт | Видимого текста |
|---|---|---|
| заглушка Cloudflare | 5829 | **58** |
| JS-шелл | 162 | **8** |
| настоящая страница | 12000 | 1504 |

У заглушки и у JS-шелла видимого текста одинаково мало. **Порог по длине их не
разделяет** — он объявит блоком любую SPA, и раннер будет уходить в браузер на
каждом отказе, теряя ровно тот выигрыш, ради которого фаза 1 и мерилась.

## Что разделяет

Положительные маркеры челленджа, а не отсутствие контента. Проверено на этих
файлах: у заглушки срабатывают три, у остальных двух — **ноль**.

- `<title>Just a moment...</title>` (и родня: `Attention Required`,
  `Checking your browser`, `Verify you are human`)
- ссылка на `challenges.cloudflare.com`
- идентификаторы `cf-chl*`
- `<meta name="robots" content="noindex,nofollow">`
- заголовок ответа `cf-mitigated` — авторитетнее всего перечисленного

Отсюда правило, на котором держится вся экономия фазы 1:

> **`content_missing` (эскалируем в браузер) ставится только когда маркеров
> челленджа НЕТ.** Есть маркеры — это `challenge_suspected`, и браузер тут не
> поможет: измерено, что `bizprofile.net` не взял ни один из пяти движков.
