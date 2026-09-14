# M10 — контракт продуктового входа (для подготовки probe)

Координаторская спецификация; автор реализации cx, независимый probe Grok.
Реализация запрещена до заморозки probe и полной execution-спеки.
Код M9 принят; менять старое ядро M7/модели/evaluate/escalate/старые тесты нельзя.
Вся реализация и проверки — Docker UID1002:1002. Никаких новых зависимостей.

## Измеренное основание

Принятый M9 на f3c3913; исправленная разведка m10-recon-result.md SHA256
0dca8623a2aaa13e3b2f8f7478d4540184738b3bb62842cd3b78987e429b48fc.
Два egress на том же коде: direct192.0.2.10 и ms1 198.51.100.21,
36 cold запросов, budget120000, промежуток на hostname>=30с.
На каждом IP curl3/6, patchright5/6, scrapling6/6 по evaluate/sentinel.
Curl403→patchright полезен на lowendtalk; patchright403→Scrapling полезен
на bizprofile. Смена IP покрытия не добавила. При найденном ожидании
lowendtalk всё ещё captcha, bizprofile suspected. Поэтому новый URL-only
критерий не может автоматически объявить обе страницы подтверждёнными.

Решение: по умолчанию проверяем доставку без ожидания; необязательный
expected_text задаёт КЛИЕНТ. Никаких скрытых ожиданий по имени цели и fake
sentinel. Вопрос владельцу вернул пустой ответ; выбран рекомендованный
вариант необязательного ожидания. Challenge никогда не затирается в trace.
Старые M7/evaluate/next_step остаются неизменны, новый автомат отдельный.

## Публичные границы

1. bench.runner.execute.fetch_content(provider, *, url, budget_ms,
   launcher=None, egress=None, entrance_url=None, network=None)
   -> tuple[FetchResult, float|None]. Реализация может быть в runner/fetch.py.
2. gateway.fetch.ProductFetcher(url, *, entrances=None, profiles=None,
   launcher=None, network=None), callable(step:PlanStep,budget_ms:int)
   -> ProviderReply. Сигнатура и копии maps как BenchFetcher, без sentinel.
3. gateway.product.ProductRequest — frozen dataclass:
   url, max_age_hours=0.0, allow_browser=True, egress_profiles=(),
   budget_ms=30000, expected_text=None.
4. gateway.product.accept_page(result:FetchResult, expected_text=None)
   -> tuple[bool,FailureReason].
5. gateway.product.plan_product(request)->tuple[PlanStep,...].
6. gateway.product.run_product(request,fetcher,*,clock=<monotonic ms>)
   -> существующий GatewayOutcome. Часы подставляются как в M7.

Ни форматирования, ни API, ни сервиса здесь нет. expected_text используется
только продуктовой проверкой полученного результата; fetch_content и
ProductFetcher его не требуют. Старый fetch_page/BenchFetcher по-прежнему
требуют непустой sentinel. Вызов legacy с None/empty не отключает проверку.

## Транспорт

Явный content_only=False в probe.run_probe и registry.build_argv, CLI
--content-only. Только этот флаг разрешает отсутствие positional sentinel;
старый CLI без флага сохраняет отказ пустого ожидания. Default off.
В content-only sentinel_found=false; не вычислять успех через подставную
строку и не вызывать evaluate. Реальные html/text и metrics обязательны.
Новый fetch_content использует данный режим, не fetch_page(sentinel=None).
Приватный общий транспорт допустим. Старые benchmark defaults и JSONL без
страниц неизменны, строгий frozen probe M9 проходит без правок.

Все гарантии M9 сохраняются: один cold запуск, остаток deadline через startup,
дробный Docker timeout budget_ms/1000, реальный body/final_url/age, строгие
типы протокола, нормализованные ошибки, отсутствие body при транспортном
сбое. Провайдеру монтируется только текущий probe.py RO. Proxy через env
subprocess по имени ABG_PROXY, не в argv, без изменения os.environ; direct
не наследует proxy, разные конкурентные вызовы не делят секреты.
ProductFetcher копирует maps. Неизвестный profile не становится direct.
Отсутствующий RSS entrance или URL именованного профиля -> not_measured
без Docker. Wayback без отдельного входа использует исходный URL как M9.
Не менять UA/headers/stealth/версии/образы или делать дополнительные retries.

## Валидация

До первого fetch/Docker: url только str, непустой http/https с hostname,
корректным port, без userinfo, ASCII control и внешних пробелов;
budget int от1 до180000 включительно, кромеbool; max_age_hours конечное число>=0 кромеbool;
allow_browser толькоbool; egress_profiles tuple непустыхstr, direct запрещён
как имя профиля; expected_text None или непустая послеstrip строка.
Дубликаты имён допустимы во входе, но одну пару не повторяют.
Невалидное -> ValueError со статическим сообщением без входных значений.
JSONnumber/bool/list/dict/null вместоURL не должны дать AttributeError/TypeError.
Transport самостоятельно проверяет URL/budget/provider доDocker; новый fetch_content имеет тот же предел180000ms. Допустимо
исправить нормализацию legacy invalid URL доValueError, валидный путь неизменен.

## Проверка страницы (точный приоритет)

1. error_type!=none -> отказ с этой причиной.
2. status403 -> http_403;429 -> http_429;5xx -> http_5xx;
   прочие4xx и не2xx -> content_mismatch. statusNone/некорректный тип ->provider_error.
3. challenge interactive ->interactive_challenge; rate_limited->http_429;
   access_denied->http_403; javascript_required->javascript_required.
   Эти признаки expected_text не отменяет.
4. При expected_text: точная подстрока в реальных html ИЛИ text обязательна.
   Нет совпадения ->content_missing. Совпадение допускает challenge none,
   suspected или captcha (как измеренные случаи); метка остаётся в trace.
5. Без expected_text: suspected->challenge_suspected;
   captcha->interactive_challenge; none допускается.
6. В любом случае text.strip должен быть непустым, иначе content_missing.
7. После всех условий успех ->(True,FailureReason.none).

Не использовать sentinel_found из протокола как замену проверки тела.
Произвольный порог длины/слова Loading не вводить. URL-only не доказывает
смысловое соответствие и может принять короткий JS-shell с видимым текстом.
expected_text — явная ответственность клиента, не скрытая настройка целей.

## План и переходы

Меню: если max_age>0 — rss/direct/entrance, wayback/direct/entrance;
затем curl/direct/http; при allow_browser — patchright/direct/browser,
scrapling/direct/browser; затем curl/<каждый профиль>/egress.
На одном запросе максимум один реально измеренный changed-egress curl;
недоступные not_measured профили можно пропускать к следующему.

Входы: принять только успешную страницу с finite age>=0 и <=max_age.
None/NaN/inf/отрицательный/протухший возраст ->content_mismatch в trace,
затем следующий вход/HTTP. Любой отказ входа, включая not_measured,
записать и продолжить; next_step=None. Direct age не выдумывать.

Для не-входов после accept_page:
| Причина | Действие |
|---|---|
| none/успех | stop, вернуть страницу |
| not_measured | записать с next_step=None и перейти вперёд; не считать сменой egress |
| timeout/connection_error/dns_error/tls_error/http_5xx | retry_later |
| provider_error/environment_error | investigate |
| content_mismatch | give_up |
| interactive_challenge (в т.ч. captcha без ожидаемого текста) | human |
| http_429 | следующий egress без браузеров; после фактической смены human |
| http_403/challenge_suspected/content_missing/javascript_required | следующий ещё не вызванный direct-browser; затем egress; после фактической смены human |

Если браузеры запрещены/исчерпаны — переходить к egress. Если требуемого
следующего шага нет — human с исходной причиной, не вызывать несуществующий
провайдер. Если исчерпаны только not_measured профили — human/not_measured.
Дубликаты(provider,profile) не исполнять. После первой измеренной попытки на
changed-egress новые адреса/браузеры в этом запросе не перебирать.

Trace содержит ровно вызовы fetcher в порядке исполнения, причины/статус/
challenge/elapsed/age/решение; skipped из-за allow_browser не выдумывать.
Сведения успешного результата берутся из реального ответа. Провал очищает
html/text outcome; исходный URL сохраняется, тело interstitial не возвращать.
clock стартует после валидации; before/after каждогоfetch проверять общий
budget. Поздний успех отклонить как timeout/retry_later, в trace successfalse;
следующийfetch получает оставшийся бюджет, без перезапуска полного.
Исключения нарушившего контракт fakefetcher не маскировать под успех.

## Обязательная живая проверка

Новый tests/live_m10_product.py: host толькоDocker-оркестрация, весь продукт
и assertions вDocker1002:1002. Свой временныйHTTPstand, реальный
ProductFetcher+run_product, неfakefetcher. Уникальный маркер в HTML И text.
Сценарии: directcurl; реальная цепочкаcurl→patchright→Scrapling на стенде,
который первымдвум навигациям одного уникальногоURL даёт пустойtext, третьей
реальнуюстраницу;403несчиталсяуспехом;timeoutcleanup. Провайдеры подтверждены
trace и счётчиком толькоURLсценария, безfavicon. Браузеры последовательно.
Отдельные deterministic unit/probe кейсы покрывают expected_text и
сохранениеchallenge, возраст/skipprofiles/валидацию/позднийответ/proxyизоляцию.
Никаких внешних целей в перезапускаемомlive, общиеimagesнеперезаписывать,
удалятьтолькоресурсыровноэтогопрогона. Socketтолькооркестратору.

## Независимый probe до реализации

Grok пишет unittest-модуль tests/probe_m10_product.py в отдельномклоне.
BASEredпо отсутствиюAPI, ДВА правильноустроенныхэталонаgreen,
обходыredна своихassertions (неimport/syntax/error), полныйпакеткоманд/cwd/rc/
логов/SHA. Заморозить SHA передcx. Старый frozen tests/probe_m9_transport.py
SHA4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190
тоже остаётся и будет выполнен. Пробник проверяет внешнийконтракт, не
приватные детали/исходныйтекст. Эталоны в продукт не переносить.
