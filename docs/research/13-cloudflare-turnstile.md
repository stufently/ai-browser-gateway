# 13. Cloudflare Turnstile: почему лестница сдаётся (диагностика 24.11.2026)

Поручение владельца: `abg-fetch` падает на Cloudflare «везде»
(`challenge_suspected на шаге human`, ~20 с). Только диагностика, код не менялся.

## Вывод

**Обход работает, отказ ставит детектор шлюза.** На управляемом вызове
Cloudflare scrapling проходит страницу с этого хоста (настоящий контент,
`cf_clearance`), а шлюз её отвергает по двум ложным срабатываниям:

1. **Устаревший `cf-mitigated` у scrapling.** `StealthySession.fetch` отдаёт
   заголовки ПЕРВОГО ответа (403 вызова), а тело — уже пройденной страницы.
   `ScraplingAdapter.navigate` снимает такой заголовок, только если в теле нет
   ни одной строки из `_SCRAPLING_CHALLENGE_STRINGS` (`turnstile`, `recaptcha`,
   `hcaptcha`, `challenges.cloudflare.com`, …). Это вето (коммит `36ca2c6`,
   17.09.2026) срабатывает на любой странице с формой входа или виджетом
   капчи: заголовок остаётся, `detect_challenge` → `suspected`,
   `accept_page` → `challenge_suspected`, шаг egress → `human`.
2. **Пассивный JSD-скрипт считается признаком вызова.** На обычных страницах
   Cloudflare встраивает `/cdn-cgi/challenge-platform/scripts/jsd/main.js`.
   Вместе со встроенным в страницу Turnstile (`challenges.cloudflare.com/turnstile/v0/api.js`)
   это уже два «решающих» правила тела → `suspected` у всех трёх провайдеров,
   хотя страница настоящая (200, свой `<title>`).

Не регрессия: старый образ `0.1.5` (`sha256:9555a5bc7667…`) падает на той же
цели так же; между `0.1.5` и `0.1.6` поменялся только `curl_cffi`. Охват
«падает везде» объясняется тем, что ломаются именно страницы с формами и
виджетами (вход, регистрация, демо Turnstile), а страницы без них проходят.

## Замеры

Образ `ghcr.io/stufently/ai-browser-gateway-oneshot:0.1.6@sha256:bb1d5f08…`,
`--budget-ms 90000`, без кэша сессий, по одному запросу на хост.

| Цель | Голый curl | Итог шлюза | Попытки (провайдер, статус, вердикт, мс) |
|---|---|---|---|
| bizprofile.net | 403 «Just a moment» | ok | curl_cffi 200 none 714 |
| lowendtalk.com/categories/offers | — | ok | curl_cffi 200 none 268 |
| medium.com | 403 «Just a moment» | ok | curl_cffi 200 none 154 |
| steamdb.info | 403 | ok, 18,9 с | curl_cffi 403 → patchright 403 (0,98 с) → scrapling 200 none 15,2 с |
| patreon.com | 403 «Just a moment» | ok, 19,0 с | curl_cffi 403 → patchright 403 → scrapling 200 none 15,9 с |
| gitlab.com/users/sign_in | 403 «Just a moment» | **отказ**, 19,2 с | … → scrapling 200 **suspected** 15,9 с |
| scrapingcourse.com/cloudflare-challenge | 403 «Just a moment» | **отказ**, 27,8 с | … → scrapling 200 **suspected** 24,9 с |
| nowsecure.nl | 200, настоящая страница | **отказ**, 6,7 с | все три: 200 **suspected** |

Разбор двух отказов прямым запуском scrapling 0.4.15 в том же образе
(`xvfb-run`, `docker run --init`, скриншот):

- gitlab: лог `The turnstile version discovered is "managed"` → `Cloudflare
  captcha is solved`, итог 200, `<title>Sign in · GitLab</title>`, cookie
  `cf_clearance`. `detect_challenge(200, None, тело)` = `none`; с заголовком
  `cf-mitigated: challenge` = `suspected`; вето сработало на `recaptcha`.
- scrapingcourse: два круга «didn't disappear after 10s», третий проходит;
  на скриншоте страница об успешном прохождении, есть `cf_clearance`, а в
  `r.headers` всё ещё `cf-mitigated: challenge`. Без заголовка вердикт `none`
  (одно правило `body_cf_challenges_host`), с ним — `suspected`; вето — на
  `turnstile` и `challenges.cloudflare.com`.
- nowsecure.nl: правила `body_cf_challenges_host` + `body_cf_challenge_platform`
  (путь только `/scripts/jsd/`) + `body_captcha_interactive` (виджет с
  тестовым ключом). Фикстура `cf_interstitial_200body_403.html` при этом даёт
  пять решающих правил, включая заголовок «Just a moment» и `cf_chl_opt`.

### Прочие причины, проверенные и отброшенные

- **Репутация датацентрового IP.** Не причина: scrapling с этого хоста проходит
  4 управляемых вызова из 4 (gitlab, scrapingcourse, steamdb, patreon).
- **Patchright.** Отдаёт 403 за ~1 с: CF-интерстишл он не ждёт (ожидание
  есть только для `javascript_required`). Отдельный прогон headful patchright с
  ожиданием до 30 с: steamdb и scrapingcourse остаются на «Verify you are
  human» с чекбоксом, cookie нет — без клика ожидание не помогает.
- **Клик по Turnstile.** Scrapling кликает и проходит; патчрайтовая ступень не
  кликает вовсе.
- **cf_clearance не переиспользуется.** Кэш сессий сохраняет cookies только
  после успеха, а здесь успеха нет — поэтому каждый запрос заново идёт через
  браузер. После исправления п. 1 кэш заработает сам.
- **Бюджет.** В one-shot (90 с) хватает. Дефолт `ProductRequest.budget_ms` —
  30 с, а scrapling тратит 15–25 с плюс две предыдущие ступени; у сервиса с
  дефолтным бюджетом запас почти нулевой (предположение, не замерено).

## Версии (24.11.2026)

| Компонент | В образе 0.1.6 | Последняя | Источник |
|---|---|---|---|
| curl_cffi | 0.17.0 | 0.17.0 (26.10) | PyPI |
| patchright | 1.62.3 | 1.64.4 (02.11) | PyPI |
| playwright | 1.62.0 | 1.65.2 (14.11) | PyPI |
| scrapling | 0.4.15 | 0.5.1 (04.11), мажорные изменения API | PyPI |
| Google Chrome | 156.0.8078.47 | 158.0.8127.88 stable | versionhistory.googleapis.com |

Scrapling 0.5: «Improved Cloudflare solving with delayed-widget detection,
fewer unnecessary waits, and bounded passive-challenge and hidden-frame retry
loops» (issues #468, #509). На наш дефект (заголовки первого ответа) это не
влияет — его закрывает только шлюз.

## Как решают другие (исходники и issues, ноябрь 2026)

| Проект | Как понимает «прошли» | Как кликает | Состояние по issues |
|---|---|---|---|
| FlareSolverr 3.5.2 | заголовок `Just a moment...`/`DDoS-Guard` и селекторы интерстишла (`#challenge-spinner`, `.ray_id`, `#turnstile-wrapper`…) пропали | TAB×n + SPACE, затем кнопка «Verify you are human»; токен в `input[name=cf-turnstile-response]` | свежие жалобы — на процессы и диск, не на CF |
| Byparr | `detect_cloudflare_challenge(page, "interstitial")` из playwright-captcha, дважды с паузой 0,25 с | контейнер `input[name=cf-turnstile-response]` (предок 1–4, 40×20–120 px), клик в x+25, середина; пауза 4 с; не кликать, если токен уже есть | свежие — утечки памяти и IO |
| Scrapling 0.4.15/0.5.1 | `cType: '…'` в DOM исчез | клик мышью по iframe `challenges.cloudflare.com` (+26, +25) | #525 (виджет на любой странице считался «embedded») закрыт в 0.5 |
| SeleniumBase 4.58.3 UC/CDP | селекторы и заголовок | `uc_gui_click_captcha` — клик PyAutoGUI на уровне ОС (Xvfb) | #4567 (клик до рендера interaction-only) закрыт 19.11; #4426 — под xvfb хуже |
| CloakBrowser | — (браузер, не решатель) | `humanize` | #646, 16.11: вызовы зависали; фикс только в preview-сборке Chromium 156.…47.7; совет — не делать долгий `sleep` после `goto`, ждать шагами по `context.cookies()` |
| camoufox | решателя нет | — | по CF свежих жалоб нет, но и встроенного решения нет |
| nodriver / zendriver | `verify_cf()` по шаблону картинки | клик по координатам | zendriver #233 «not working» открыт, #270 починен 08.2026; nodriver #31 клик детектится |
| botasaurus | ожидание и смена Ray ID | `bypass_cloudflare=True` | #305, #282, #276 открыты — обход не работает на Linux |

Общее у всех, кто работает: «прошли» решается **по состоянию живой страницы**
(заголовок, селекторы интерстишла, токен Turnstile, `cf_clearance`), а не по
заголовкам первого ответа и не по встречаемости слов «turnstile»/«captcha» в
пройденном HTML.

## Варианты исправления (по убыванию отдачи)

1. **Заголовки финального документа в ScraplingAdapter.** Брать статус и
   заголовки последнего ответа главного фрейма (в 0.4.15 — подписка
   `page.on("response")` через `page_action`/контекст; в 0.5 —
   `record_requests=True`) либо снимать `cf-mitigated`, когда
   `detect_challenge(status, None, body) == "none"` и в контексте есть
   `cf_clearance`; вето по словам убрать. Довод: замерено — на gitlab и
   scrapingcourse вердикт без заголовка `none`. Работа маленькая (одна ветка
   адаптера, тесты на фикстурах из этого разбора). Риск: принять ещё не
   пройденную страницу — закрыт тем, что интерстишл сам по телу даёт ≥2
   решающих правил (фикстура — 5).
2. **JSD не решающее правило.** `body_cf_challenge_platform` засчитывать,
   только если после маркера не `/scripts/jsd/`; встроенный Turnstile на 200 с
   собственным заголовком — не `suspected`. Довод: замерено на nowsecure.nl
   (три провайдера отдали настоящую страницу и все отвергнуты). Работа
   маленькая. Риск: виджет-капча, которая реально закрывает контент, пройдёт
   как успех — смягчается `expected_text`.
3. **Апгрейд scrapling 0.5.1 + Chrome 158 + patchright 1.64.4.** Довод —
   предположение: ограниченные циклы и обнаружение отложенного виджета должны
   срезать 15–25 с решения (сейчас по два круга «didn't disappear after
   10s»). Работа средняя: в 0.5 ломающие изменения API, нужен замер серии
   перед выпуском. Риск: регрессия других целей.
4. **Patchright: ждать и кликать по образцу Byparr или не тратить ступень.**
   Сейчас ступень бесплатна (~1 с) и бесполезна на CF. Клик по контейнеру
   `cf-turnstile-response` — предположение, не замерен; ожидание без клика
   замерено и не помогает. Работа средняя, риск — второй решатель в коде.
5. **Бюджет сервиса.** Поднять дефолт выше 30 с или давать scrapling весь
   остаток, если сервисные вызовы тоже сдаются по `timeout`. Предположение.

Не рекомендуется: смена IP или резидентный прокси (IP не причина),
CloakBrowser (проприетарный, свежие CF-поломки чинятся только в preview),
nodriver/zendriver/botasaurus (открытые issues о неработающем обходе).
