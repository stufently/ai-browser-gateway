# Приёмы конкурентов, которых у нас нет (2026-10-09)

Разбор по исходникам (ветки по умолчанию на 09.10.2026), не по маркетингу.
Ничего не замерено на наших целях: это список гипотез для следующих вех,
а не доказанная польза. Уже отвергнутое (camoufox, pydoll, primp, nodriver,
CloakBrowser, r.jina.ai, Common Crawl, платные скраперы) сюда не входит.

## Лицензии источников

| Проект | Лицензия | Что можно брать |
|---|---|---|
| Scrapling, FlareSolverr, SeleniumBase, botasaurus, Spider, defuddle, markdowner | BSD-3 / MIT | код |
| Crawlee, fingerprint-suite, got-scraping, steel-browser, Jina Reader | Apache-2.0 | код |
| Crawl4AI | Apache-2.0 + пункт об атрибуции | код с видной атрибуцией или переписать |
| ftr-site-config (FiveFilters) | CC0 | всё |
| Firecrawl, germondai/trawl | AGPL-3.0 | только идеи |
| Byparr | GPL-3.0 | только идеи; зависимости `invisible-playwright`, `playwright-captcha` — MIT |
| browserless | SSPL | ничего: stealth в открытой части нет |

## A. Детект: что именно нас остановило

Сейчас лестница распознаёт Cloudflare и Qrator. Остальные защиты выглядят
как обычный 403 или «пустой» 200.

1. **Детектор по вендорам.** Заголовки и тело для Cloudflare
   (`cf-mitigated`, `_cf_chl_opt`; `__CF$cv$params` — вызов только при теле
   < 3000 байт, иначе это пассивная телеметрия), AWS WAF (202/405 +
   `x-amzn-waf-action`), DataDome (`captcha-delivery.com`, поле `rt` i/c,
   `t=bv` — жёсткий бан IP), DDoS-Guard (`/.well-known/ddos-guard/`), Imperva
   (`x-iinfo`, `_Incapsula_Resource`, `reese84`), Akamai (`/_sec/cp_challenge/`,
   `Reference #`), PerimeterX (`_pxAppId`), Kasada (`KPSDK`), Vercel Checkpoint,
   Wordfence, Sucuri. Источники: trawl `packages/tiers/src/utils/detect.ts`
   (идеи), Spider `spider/src/utils/mod.rs` `detect_anti_bot_from_*` (MIT),
   Crawl4AI `crawl4ai/antibot_detector.py`.
   Польза: ошибка делится на «бан IP → нужен egress» и «решаемый вызов →
   нужен браузер», и ступень выбирается по вендору, а не перебором.
2. **«Пустая оболочка» при 200** (Crawl4AI): < 50 КБ, видимого текста
   < 50 символов, мало `<p>/<h*>/<li>`; JSON/XML исключены. Плюс оценка
   «нужен ли JS» по статическому HTML (Spider `page.rs`: `<noscript>` с
   «enable javascript», `history.pushState`, `window.__NUXT__`).
3. **Тип вызова CF по `cType`** (Scrapling `_detect_cloudflare`):
   non-interactive / managed / interactive / embedded — в `attempts`.
4. **Кука защиты ≠ решение** (trawl `snapshotChallengeCookies`): AWS WAF
   и DataDome ставят куку уже на странице блока; сравнивать до/после.

## B. Сессии: не решать один и тот же вызов дважды

5. **Кэш решённой сессии по домену** — главный недостающий кусок. trawl
   хранит `session:<domain>` с TTL и переигрывает куки с тем же
   отпечатком; при новой стене сессию сносит. Значения Crawlee:
   `maxAgeSecs=3000`, `maxUsageCount=50`, ретайр на 401/403/429.
   Для отдачи `cf_clearance`/`__ddg*` в curl_cffi нужен совпадающий UA и
   impersonate той же мажорной версии Chromium; `Headless` из UA вырезать
   (FlareSolverr `get_user_agent`). Касается сервиса, не one-shot.
6. **Запросы через `window.fetch` решённой вкладки** (botasaurus-driver
   `requests.py`): TLS, куки и UA настоящие, согласовывать нечего.
   Альтернатива п. 5 при тёплой вкладке на домен.
7. **Память ступени по домену** (идея Firecrawl `engpicker.ts`, у них с
   LLM-оценкой): запоминать, на какой ступени домен прошёл, и начинать с неё.

## C. Ожидание и клик

8. **DDoS-Guard** (trawl `ddosGuardWait.ts`): ждать `__ddg2_`/`__ddg5_`,
   через 8 с перейти на URL заново, до 2 повторов; стена осталась →
   `ip-blocked`, а не таймаут.
9. **Смена Ray ID = клик отвергнут** (botasaurus
   `wait_till_cloudflare_leaves`): сдаваться за ~12 с, не жечь весь бюджет.
10. **Клик по Turnstile** (Byparr `challenge.py`): от
    `input[name=cf-turnstile-response]` вверх на 1–4 предка, рамка шире 40
    и высотой 20–120, клик в (x+25, середина), пауза 4 с, не кликать при
    заполненном токене. SeleniumBase `__click_captcha` — ~18 селекторов
    нестандартных обёрток.
11. **Стратегии ожидания** (Jina `RESPOND_TIMING`): mutation-idle,
    visible-content, network-idle. Прямо про ожидание после JS-челленджа.
12. **Xvfb и клик на уровне ОС** (SeleniumBase, FlareSolverr; trawl держит
    Xvfb-пул только для DataDome). Только если появятся цели на DataDome.

## D. Связка HTTP и браузера, egress

13. **Side-load** (Jina `puppeteer.ts`): документ качает curl_cffi, браузер
    получает его через перехват (`route.fulfill`) и исполняет JS. Для сайтов,
    где режут TLS-отпечаток Chromium, но рендер нужен.
14. **Браузер через прокси** (Firecrawl `scrapeURL/index.ts`: 401/403/429
    → лестница заново с прокси). У нас прокси — только для curl.
15. **Часовой пояс и локаль от IP прокси** (steel-browser
    `timezone-fetcher.service.ts`, Byparr): гео-запрос через сам прокси,
    `Accept-Language` = `navigator.language`.
16. **Порог текста как триггер прокси** (Jina: < 42 токенов или не 200).

## E. Извлечение

17. **JSON-LD `articleBody`** (trafilatura, graby, newspaper4k): полный текст
    часто в HTML даже под оверлеем. Дёшево.
18. **ftr-site-config** (CC0, ~1970 доменов): XPath `body`/`title`/`strip`,
    `single_page_link`. Брать только XPath-часть: ~24 правила подставляют
    UA Googlebot и ~32 — cookie обхода пейволла, это против Responsible use.
19. **WordPress REST** `/wp-json/wp/v2/posts?slug=…` — дешёвый вход.
20. **Снятие cookie-баннеров** (Crawl4AI `remove_consent_popups.js`: OneTrust,
    Cookiebot, Didomi, Quantcast, Sourcepoint…), shadow DOM и iframe в HTML
    (`flatten_shadow_dom.js`, `process_iframes`), прокрутка для lazy-load.
21. **Экстракторы под сайты** (defuddle, MIT): Reddit через old.reddit/Atom,
    YouTube-субтитры, X через oEmbed/fxtwitter, HN, GitHub; Wikipedia через
    MediaWiki API (Firecrawl). PDF/офис (Jina: pdfjs, soffice).
22. **Main content**: Readability (Jina), pruning-фильтр `fit_markdown`
    (Crawl4AI). `__NEXT_DATA__` как источник текста не использует никто.

## Что сознательно не брать

- Подмена UA на Googlebot/Bingbot, referer t.co, cookie обхода пейволлов
  (Bypass Paywalls Clean, 13ft): против Responsible use; крупные сайты
  сверяют бота по rDNS (wsj.com — 401 на оба UA).
- archive.today: нестабильные домены, в 2026 Википедия объявила его
  deprecated (использование браузеров посетителей для DDoS).
- Кэши Google (снят 02.2024) и Bing (12.2024), AMP-кэш (на bbc.com —
  meta-refresh на оригинал).
- Гонка движков параллельно (Spider): ускоряет, но множит браузеры;
  на нашей памяти не окупится без замера.

## Предлагаемый порядок

1. A1–A4 + C8/C9: детект вендоров и ранний отказ. Дёшево, меняет
   классификацию ошибок.
2. B5/B7: кэш сессии и памяти ступени по домену в сервисе.
3. E17/E19: JSON-LD и WP REST.
4. D13/D14/D15: side-load и браузер через egress с гео-согласованием.

## Замер с нашего хоста: как лестница 0.1.3 встречает вендоров (2026-10-09)

curl_cffi (`impersonate="chrome"`), затем ручной patchright (headful, Xvfb)
с ожиданием 25 с, затем сам one-shot 0.1.3 с `--budget-ms 90000`.
По одному запросу на сайт.

| Сайт, защита | curl_cffi | Браузер, 25 с | Лестница 0.1.3 |
|---|---|---|---|
| wayfair, PerimeterX (`_pxhd`) | 429 | **сразу 200, настоящая страница** | `http_429` → `human`, браузер не пробовала |
| priceline, PerimeterX | 403 | «Access to this page has been denied» | 403 → оба браузера → `human` |
| hyatt, Kasada (`KPSDK`) | 429 | остаётся 429 | `http_429` → `human` |
| etsy, tripadvisor, g2, DataDome (`rt:'i'`) | 403 | остаётся на `captcha-delivery` | 403 → оба браузера впустую (~5 с) → `human` |
| homedepot, cnbc, Akamai «Access Denied» | 403 | — | 403 → оба браузера впустую → `human`; это бан IP |
| ticketmaster, своя стена | 403 | «Your Browsing Activity Has Been Paused» | 403 → оба браузера → `human` |
| avito, Qrator | **439** | 429 «Доступ ограничен: проблема с IP» | не замерено |
| glassdoor, CF | 401 «Authenticating...» | «Just a moment...» через 25 с | не замерено |

Вывод для вехи детекта: 429 от PerimeterX — не rate limit, такой ответ надо
вести в браузер (wayfair откроется). Akamai «Access Denied» и Qrator «проблема
с IP» — бан адреса: такой ответ надо вести сразу в egress. DataDome с этого IP
браузером не проходится. В теле ticketmaster стоит IP клиента: перед тем как
класть его в фикстуру, вычистить.

## Замеры после 0.1.4 (2026-10-09)

### Браузер через egress-прокси (D14)

`patchright` и `scrapling` из образа 0.1.4 с `ABG_PROXY` = egress-прокси
хоста, по одному запуску:

| Сайт, защита | patchright | scrapling |
|---|---|---|
| etsy, tripadvisor, g2 — DataDome | 403 | 403 |
| hyatt — Kasada | 429 | 429 |
| homedepot — Akamai | 403 `ip_blocked` | 403 `ip_blocked` |
| ticketmaster | 200 | 200 |

Ticketmaster лестница уже берёт шагом `curl_cffi` через тот же прокси.
Цели, где браузер через прокси добавил бы что-то, нет, поэтому ступень **не
добавлена**. DataDome и Kasada с этого прокси браузерами не проходятся.

### Повтор cookies браузера в curl_cffi (B5)

Браузер решает вызов, затем `curl_cffi` (`impersonate="chrome"` и
`chrome136`) повторяет запрос с его cookies и UA:

| Сайт | Браузер | curl_cffi без cookies | с cookies и UA |
|---|---|---|---|
| rbc.ru — Qrator | patchright 200 | 401 | **200**, полная страница |
| bizprofile.net — CF | scrapling 200, `cf_clearance` | 403 «Just a moment» | **200**, полная страница |
| glassdoor.com — CF | scrapling 200 (редирект на `.de`) | 401 | 401 |

Кэш решённой сессии по домену окупается на Qrator и на Cloudflare
(bizprofile: ~25 с scrapling против одного HTTP-запроса). Это отдельная веха.

### Извлечение текста (E17, E19)

Выборка из 20 RSS-лент, по две статьи (32 строки), `curl_cffi`:
видимый текст уже есть почти везде (2–13 тыс. символов);
JSON-LD `articleBody` — в 4 строках (verge, wired×2, vox), WordPress REST —
у techcrunch (2), и все они и без того читаются. nytimes отдаёт 403, и
JSON-LD там нет. Прирост охвата **0**, поэтому экстракторы не внедряются.
Пригодятся, только если понадобится формат «только текст статьи», а это
изменение контракта, не обход.
