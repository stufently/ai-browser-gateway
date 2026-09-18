# Рабочий журнал `ai-browser-gateway`

Единственный источник правды по статусу работ. Изменения кода/поведения — в
`CHANGELOG.md`, сюда не дублируются. Записи старше ~30–60 дней уезжают в
`docs/worklog-archive/YYYY-MM.md`.

## За владельцем (я сам сделать не могу)

- [x] **Поддомен под свой CF-стенд — выкачен (14.09.2026).** Токен CF не нужен:
  октodns-репо `~/gitlab/9qw/octodns` держит `CF_API_TOKEN` в CI, apply идёт сам
  на push в `main`. Добавил `abg-cf.example.net` A `192.0.2.10` (stand-host), `proxied:
  true` — `dump/example.net.yaml`, коммит `1d92667`. Цель `own-cf-stand` включена в
  `targets.toml` (`valid=false` до настройки). ОСТАЁТСЯ (executor): сервис на
  stand-host:443 под этот хост + WAF-правило Managed Challenge и Turnstile на тестовых
  ключах — тогда стенд даёт воспроизводимость, которой у чужих целей нет.
- [x] **Cloudflare Browser Run — снят (14.09.2026).** Владелец: «кажется тебе это
  не надо». Провайдер CF Browser Run из меню и из замера фазы 1 исключается,
  строка «не измерено» больше не висит.
- [x] **Второй egress для фазы 1 — решено (14.09.2026).** GoldProxy снят с
  повестки владельцем («больше нет и не будет»). Штатный второй egress — пул
  прокси `ms1-15.example.net` (инфраструктура владельца, кредов ждать не надо). Это
  закрывает вопрос «отличить „инструмент не справился“ от „адрес не пустили“»:
  хост сидит на хостинговом ASN без репутации (`AS206996 ZAP-Hosting`), теперь
  есть с чем сравнить. Остаток — НА НАШЕЙ стороне: завести пул в прокси-слой
  bench (M5 уже умеет прокси) и прогнать сравнительный замер тем же образом и
  отпечатком с обоих адресов.
- [x] **Живой рилс для `login-instagram` — выдан (14.09.2026).** Владелец дал
  `https://www.instagram.com/reels/DdJ-MY6OITt/`. Прописан в `targets.toml`,
  `valid=true`. Отдельно: проверить инструменты именно на этом рилсе (доберётся
  ли до контента за стеной логина) — задача для executor.
- [ ] **Какие ещё боевые цели из рабочих проектов добавить.** Сейчас взяты
  `bizprofile.net` (снят с мониторинга check-sites из-за CF, возврат намечен на
  12.09.2026), `instagram.com` (три задачи бэклога упираются в стену логина) и
  магазины hqd как контроль «чистый nginx».

## Готовность к использованию — поручение 14.09.2026

- [x] **Разведка перед M9.** Исходная база `0f800ed20162394079484b64df483114ad598e75`.
  Задание владельца прочитано целиком:
  `/home/user/gitlab/9qw/tg-claude-userbot/tmp/abg-coord-task-20260914.md`.
  Задание Grok сохранено в `docs/specs/m9-recon.md` (копия запуска:
  `/home/user/.cache/abg-coord-20260914/recon.md`);
  отдельный клон: `/home/user/exec-clones/abg-ready-recon-20260914`,
  push в origin отключён. Первый запуск отклонён журналом: оба слота `gk`
  заняты (`t-5885192dfe77-a01`, `t-f4f31014a661-a01`). После освобождения
  слота разведка выполнена Grok на `4af46c5`, чистый клон. Результат:
  `/home/user/.cache/abg-coord-20260914/recon-result.md`, SHA256
  `bcddcd468c76d3bc792f9deab9a1accb7575052daf3e59203e77feaded988b21`.
  Панель `gk-abg-ready-recon-20260914` закрыта, подготовка принята
  (`t-08a931001841-a01`); продуктовая веха этим не принимается.
  На момент разведки остатки окон 5h/weekly были неизвестны, quota error не получен.
- [x] **M9 — реальный транспорт страницы принят (14.09.2026).**
  Исполнитель Grok; принятый FINAL_SHA
  `bab00353adbbfc9484a1b5ab6ea63705d5aa99e1` из клона
  `/home/user/exec-clones/abg-m9-real-fetcher-20260914`, ветка `m9-real-fetcher`.
  Спеки: `docs/specs/m9-real-fetcher.md`, `m9-acceptance-fixes.md`,
  `m9-live-html-assertions.md`; последняя SHA256
  `7dd243f1b9203951b846ab4f968e9cacfdbc73803219bdd3113f415dff6c517e`.
  Координатор прочитал полный дифф и замороженный probe, проверил SHA/логи
  всей цепочки Codex/Gemini, инварианты ядра и исторических измерений.
  Собственный гейт `accept_run.py --timeout 3600`:6/6 pass на FINAL_SHA,
  включая385 unittest,21 независимый probe, реальный live curl/patchright/
  scrapling/gateway (13s),105 исторических мутаций (126s). Отдельный повтор
  этих же сьютов не нужен. Лог `m9/coordinator-final-gate.log` в cache ниже.
  Live проверяет уникальный маркер в HTML и text, Unicode, отказ403,
  бюджет800ms и отсутствие своих контейнеров после timeout. Пример лога
  исполнителя: curl19ms, patchright932ms, scrapling2174ms, timeout wall1025ms;
  это локальный стенд, не сравнительный замер внешних целей.

  Независимый автор probe и мутаций — явный cx, разрешённый постановщиком
  после исчерпания Spark. Probe-коммит `842ed6b`, неизменный SHA256
  `4391024b03139e508978d86244cc27a81d386d5fbeea9d3c543fb1e424719190`.
  Финальные мутации на том же `bab0035`:17/17 activated assertion kills,
  0survived/invalid, baseline53, restore/source SHA и git-чистота подтверждены.
  `m9/mutations-cx/final-result.md`, SHA256
  `3af6fb17ac212b2b4170306542836d09c7cb75f155aa595fb074d81058b28b12`;
  harness SHA256 `fcbf76cc95412dc72196f1a2fa061e8f5a9bedd7891df9ba1466c6227027bf9a`.
  Автор кода мутации не подменял. Старые подготовительные прогоны08a5da9/
  4775917 сохранены в `m9/mutations-cx/runs/`; текущий индекс отчёта обновляемый.

  Все пакеты: `/home/user/.cache/abg-coord-20260914/m9/`.
  Итоговый полный комплект Grok: `live-html-final/`, все56 хешей проверены.
  Квитанции вне клона: `~/.cache/tg-claude/review-journal/`, run_id
  `abg-m9-real-fetcher-20260914-` + BASE prefix `72b7ce87713a`,
  `08a5da91e68d`, `724d75894fe3`; собственные сверки квитанций в cache.
  Первый пакет08a5da9 был отклонён из-за Unicode framing, HTML-границ и
  неполной проверки cleanup; пакет724d758 возвращён за потерю двух HTML
  assertions в live. Все подтверждённые дефекты закрыты тем же Grok.
  Неполные технические ответы сохранены, валидные неизменные ревью не
  дублировались. Точный ход исправлений также в коммитах b1ca817/e036849.
  Попытки `t-40a7319057d6-a01` и `t-ccc17d852776-a01` failed; финальная
  `t-598f793acd1c-a01` accepted. Финальный cx `t-4e820c66d73d-a01` accepted.
  Все наши панели/сторожа M9 закрыты после завершения, фоновых тестов нет.

  **Политика квот:** Spark исчерпан до20.09.2026 15:59 (часовой пояс в ошибке
  не указан); лог `m9/spark-quota.log`. Не запускать Spark/auto до reset.
  Постановщик явно разрешил gk/cx. Последний фактический Grok weekly —5%,
  5h/reset неизвестны; окна обычного cx неизвестны. Остатки не придумывать.

- [x] **Read-only подготовка egress:** параллельно M9 выполнена Grok
  `gk-abg-egress-recon-20260914` в собственном клоне
  `/home/user/exec-clones/abg-egress-recon-20260914`. Только лёгкая проверка
  direct и ms1/ms8/ms15 с безопасной передачей существующих creds; без
  браузеров, создания profiles.toml или изменений чужих сервисов.
  Результат `egress-readiness-result.md` в `/home/user/.cache/abg-coord-20260914/`,
  SHA256 `9589adf46257b758f0279f3025e6b0fd0f8be15a1c1cd0b3e6a40b70792c04fd`.
  Доступ с существующими creds подтверждён у трёх представителей; direct и
  прокси-IP различаются; no-auth контроль 407. Все хеши артефактов сверены.
  Профили ещё не созданы, остальные 12 хостов и цели не измерены.
  Подготовка принята (`t-6bad4a7ec5c2-a01`), панель и сторож закрыты.

- [x] **M10 — разведка продуктового входа/API/CLI принята.** M9 опубликована merge
  `f3c391371b8cf4d4718fad4013bd051b1e5874a2`; code в main совпадает с принятым
  `bab0035`, кроме координаторских TASKS/CHANGELOG. Запущен read-only Grok
  в `/home/user/exec-clones/abg-m10-recon-20260914`, BASE_SHA=f3c3913,
  push отключён. Задание `docs/specs/m10-recon.md`, копия запуска
  `/home/user/.cache/abg-coord-20260914/m10-recon.md`.
  Попытка `t-16fd450836dd-a01` accepted; исправленный пакет
  `m10-recon-result.md`, SHA256
  `0dca8623a2aaa13e3b2f8f7478d4540184738b3bb62842cd3b78987e429b48fc`.
  Первый пакет вернулся за импорт продукта на host и неполную матрицу;
  старая улика сохранена как noncompliant. Повторены 24 наблюдения в Docker
  1002:1002, rc=0, исходники RO; скрипт/argv/логи и все16 хешей проверены.
  Приняты факты, не все рекомендации: новый явный fetch_content сохранит
  строгость M9, продукт отдельно от M7; API внутри Docker, host CLI — обёртка.
  Без sentinel нет проверки смыслового соответствия страницы; произвольный
  порог «Loading» не вводится. Полные сьюты M9 не повторялись.

- [x] **M10 — обязательное сравнение двух egress принято.**
  Задание `docs/specs/m10-egress-measurement.md`; Grok в том же чистом клоне
  на f3c3913, попытка `t-505a5d41b116-a01` accepted.
  Панель `gk-abg-m10-recon-20260914` закрыта после пакета;
  лог наблюдения `m10-recon-watch.log` в cache.
  Ровно36 холодных попыток:6 valid целей × curl/patchright/scrapling ×
  direct/ms1, одинаковые образы/отпечаток, budget120s, пауза30s на hostname.
  Секреты программно из существующего источника, только env по имени;
  production profiles не созданы. Пакет `m10-egress-result.md` в cache,
  SHA256 `39d5bc019b564324bb2b3e70781735920a517ec70a8ef3dc141cef2806467409`.
  Старый полезный результат Scrapling был с другого IP; новый замер нужен
  для выбора перехода после403. Запрос выбора вернул пустой ответ — выбран
  рекомендованный обязательный замер, без новой блокировки на вопросе.
  Координатор прочитал полный отчёт, готовый research, весь inner_fetch.py
  и host run_measure.py; echo-helper совпал с ранее принятым SHA.
  Проверены35 хешей,36 уникальных клеток, фактический min-gap30.000022s,
  SHA кода/образов, rc0 полного прогона и пустой scoped Docker ps с rc0.
  37 launcher calls в summary —36 провайдеров + docker --version, не retry.
  Уточнены только три формулировки отчёта, исходные данные не переписывались.
  На обоих IP curl3/6, patchright5/6, scrapling6/6; unique Scrapling —
  bizprofile после403. Смена direct→ms1 покрытия не добавила. Шесть успешных
  по sentinel строк всё ещё имеют captcha/suspected; URL-only этого не доказывает.
  Авторские готовые файлы перенесены координатором без правок:
  `docs/research/06-two-egress.md` SHA619f59873546e60e5b97dd9d77708da7a6218f9550ec06c89552a57d004f8fc0,
  `docs/research/data/m10-egress.jsonl` SHAbaf4fdf1f7310993ec30ed0c83dc559d3a90f17a740b6267e246859aedac5550.
  Это отдельная приёмка готового исследования, не реализация M10.

- [x] **M10 — продуктовая лестница принята (15.09.2026).**
  Автор cx, `gpt-6-astra high`; FINAL
  `ebb852410c3c218b41acae068b11bda653ee0dc4`, клон
  `/home/user/exec-clones/abg-m10-product-20260914`, ветка `m10-product`.
  Исходный BASE `b303ecce7812f1a2cd4cb7a3cffdf4c0aabce2cf`, REVIEW
  `4810e22f7a8b9427f112723b5e2b56d7fcbfece6`.
  Спека `docs/specs/m10-product.md`, SHA256
  `5e4f56226e3aa91a121ae6e7d5266f799f17050da529f21da60cd128d749e820`;
  контракт `m10-product-contract.md`, SHA256
  `01b9df3ffb99559883d3438b7fe8727c4ba0ccefd8e9591363a6bfb3d068ea84`.
  Новый URL-only вход использует явный content-only транспорт, общий deadline,
  RSS/Wayback по свежести, curl → patchright → Scrapling → egress → human.
  Необязательный `expected_text` клиента подтверждает suspected/captcha по
  реальному телу; HTTP/interactive/ошибки не отменяет, challenge остаётся в trace.
  Вопрос о вариантах вернул пустой ответ, выбран рекомендованный optional режим.

  Независимый probe Grok: commit `25335c9dcbd7ddffa09587518f0209309f6603df`,
  SHA256 `699d66eb29233728518d176c3dcc01bd1fb5c6fc29cc4860e80f56fdbf7fc013`,
  49687 байт, 55 тестов. Два различных эталона green, 13 обходов assertion-red;
  точный BASE автора red по отсутствию API. Исправлены лишние ограничения
  первого probe и пробелы dedup/port/concurrency/cwd; старый пакет в `probe/round1`.
  Подготовка `t-96ef542a62d6-a01` accepted; report SHA256
  `6804a94095e5b778765fe25f0c9a0d2570e617556106fcaec23d3bef30fafcec`.

  Полный diff и delta прочитаны координатором; frozen probe прочитан при
  подготовке и проверен по SHA. Initial Grok+Gemini и отдельный Codex приняли;
  после исправления теста те же verification-рецензенты приняли полный delta.
  Первый Grok-ответ без точки в «Находок нет.» не зачтён, единственный технический
  повтор rc=0. Initial неизменного кода не повторялись, квитанции не правились.
  Журнал `~/.cache/tg-claude/review-journal/abg-m10-product-20260914-b303ecce7812/`.
  Проверены SHA входов/raw, границы BASE/REVIEW/FINAL и полный контракт в контекстах.
  Initial full.diff 99861 байт SHA
  `cf242f393f4206f4ff1dc3c1e8301cc5099603ed922a25bcf2fa2764f4c55cac`;
  delta 1115 байт SHA
  `cb76cff81e266a7822ee8ab99bccf2f450ebd8cdf3daa012ee47f22c6e4e1b1d`.
  Накопленный полный diff 100043 байта SHA
  `ff739df240cc4184c82074a1ef9ce24d9aa14591db1b59de6fd96911f3a548d3`:
  все изменения покрыты полными initial+verification, обрезки нет.

  Один дефект приёмки исправлен тем же cx: assertion внутри adapter_factory
  проглатывался `run_probe`, и его текст давал ложный pass. Теперь callback
  нормально возвращает Adapter, а вызов проверяется внешним assertion.
  Общей дыры покрытия не было: frozen probe ловил тот же мутант раньше.
  Задание `cache/m10-test-guard-fix.md`, SHA256
  `80ebf6fa521fc41bd48e1baed5f61396dfd1615d094bf594e5ef2b91b8cbad3d`.
  Производственный код после REVIEW не менялся, исправлен только новый тест.

  Авторский полный gate и собственный gate координатора на FINAL: 6/6, rc=0.
  Свой лог `m10/coordinator-test-guard-gate.log`: unittest 3s, 76 frozen probes
  1s, live 17s, 105 исторических мутаций 133s, invariants/clean 0s.
  Live доказывает реальные JS-маркеры patchright/Scrapling в HTML и text,
  exact trace/count, отказ403, timeout и scoped cleanup. Отдельный повтор не нужен.
  Старый неудачный historical run на фоне ревью сохранён, источник пересечения
  не установлен; последовательный повтор и оба финальных гейта прошли.

  Независимые мутации Grok на FINAL: baseline 68, 14 activated assertion kills,
  0 survived/invalid, source/HEAD/status и finally restore проверены. M03 теперь
  убит именно внешним assertion исправленного авторского теста (`['curl'] != []`).
  Прочитан весь harness/run/test_runner, проверены patches/активация/логи/SHA.
  Harness SHA256 `f44454aac94d03344ca3afd4e9456935c1721690d1e5c5160007745ce757ac7e`.
  Итоговый пакет в `/home/user/.cache/abg-coord-20260914/m10/test-guard-final-package/`,
  все 646 хешей сверены; `final-result.md` SHA256
  `24ce3e9ec5f6d3177cda1bc65a2af6a150cd3aa9109ada53cfebf95f59eee067`.
  Старые пакеты `readme-followup`, `final-package` и `mutations-gk/archive-4810`
  сохранены. Отчёт исправления SHA256
  `164382506b1db3df9458edd02a96fda933d82fc08c15fa86e5fa6d9b13277030`.
  Попытки автора `t-810ca7584d29-a01` и мутаций `t-3d10b8113041-a01` accepted.
  Основной бот готовую приёмку M10 не повторяет. Хронология подготовки и
  возвратов сохранена в TASKS.md коммита `6c65d04` и исходных пакетах.

- [x] **M11 — HTTP API и CLI принята владельцем и влита (15.09.2026).**
  Merge `e5fd99752f23c35f5d0ba2bdafde7aa80deee867` переносит точный FINAL
  `e6f7f0c844ebf9fa3d6d1194d921302e8ab1d211` из `m11-author-tests-20260915`.
  Слияние без конфликтов; дерево совпадает с FINAL, кроме TASKS.md.
  Прежняя приёмка сохранена; gate/reviews/tests повторно не запускались
  согласно решению владельца. Оснастка не менялась.
  **Решение 15.09 (владелец через координатора tg-claude-userbot):** машинный gate `accept_run` v2 не
  применяется к возврату исполнителю после verify — протокол cross-review-v1 такого перехода не имеет
  (`VERIFY_ONLY → FIX_ONCE` запрещён), оснастку под него не строим. M11 принимается по уже собранным
  доказательствам на FINAL `e6f7f0c` (6 AC green, 413 unit/94 frozen/live, Codex+Gemini приняли код и
  test-only дельту, мутации Grok 21/21, native verify Grok accepted/0 findings).
  Решение о слиянии исполнено; следующий этап — M12.
  Впредь возврат после verify = НОВАЯ веха: новый клон от прежнего FINAL, BASE = прежний FINAL.
  Ниже — история до решения, как была. Token auth,
  URL/свежесть/budget/expected_text, content+trace, пять режимов cf-fetch,
  общий лимит браузеров с ожиданием внутри бюджета. Runtime в Docker1002.
  Контракт `docs/specs/m11-api-cli-contract.md` зафиксирован; execution-спека
  `docs/specs/m11-api-cli.md` заморожена после принятого probe, preflight pass.
  SHA256 execution-спеки
  0cdcd0feda30c6d90ce0b5abe662c59b51098ef9718c156b83a3ddd1def50f58.
  **Последний handoff15.09, около05:08UTC:** FINAL
  `e6f7f0c844ebf9fa3d6d1194d921302e8ab1d211`;6AC green (413unit/94frozen/live),
  Codex+Gemini приняли код/исправления и новую test-onlyдельту. Независимый
  Grokmutation gate принят21/21qualified author kills, M13excluded отдельно.
  Grok verify завершён04:58:21UTC: nativeverify-grok-1.json rc0/accepted/0findings,
  точный REVIEW909ed88..FINALe6f7f0c22244bytes;46manifest entries/receipt/input
  сверены. Авторский пакет `cache/m11/grok-verify/`, manifestSHA
  a6b95a35dd55f55f088a972184bdb3e16deece697c9f2339855e1156d93b4de7.
  Собственный финальный accept_run координатора05:02:35UTC на exactFINAL:
  **rc3 «invalid: verify-agy-1.json: устаревший snapshot_sha/range»**, AC не
  стартовали. `cache/m11/coordinator-final-gate-e6f7f0c/`; toolSHA
  689f36bd9ef67f39d6bdae006c743a54a4043714fdd43ca646bab69a4d2d2369.
  Чужая оснастка не менялась; BASE/контракт/квитанции сохранены. Нужна поддержка
  аудируемых разрешённых возвратов с новой границейverify при неизменномBASE,
  без удаления истории и ослабленияSHA/time/input/backend checks.
  Точный технический handoff: `cache/m11-review-journal-blocker-e6f7f0c.md`.
  Ограничения дополнительных Grokreviews сохранены: strictindependence initial
  не подтверждена; rawverify не содержитtoolcalls и не доказывает соблюдение
  read-only/no-runtime. Фактический запуск кода также не установлен. Это не
  скрыто/не выдано за новые доказанные productfindings; validreviews не повторялись.
  Grok собрал окончательный `cache/m11/final-handoff-e6f7f0c/HANDOFF.md`,
  SHAe803ed2eaed6b8ce709a6f2910cfd4a6a1004650e6656743489bdb72e920a072.
  Полные копии безsymlinks:1403datahashes/2820проверок исходных копий pass,
  manifestSHA2f65dfc0788d12167be01d5461fd6c50efcd76072fb2f714e16539f6ebb23eb7;
  `cache/m11/coordinator-final-handoff-check.json`. Все оригиналы остаются.
  t-5dc975739851-a01 accepted (мутации/сборка); t-1b0cdfbaed75-a01 blocked
  (общий gate). Обе завершённые собственные панели закрыты после пустого ввода
  и завершения фоновой работы. Авторские коммиты/резервнаяветка/bundle сохранены,
  непринятый код не пушился. **M11 не слита, M12 не начата.** До изменения оснастки
  нового разрешённого исполнительского шага нет; coordinator handoff сохранён,
  завершить без новых вопросов, возобновить по новой разрешённой задаче.
  Ниже — сохранённая история работы и точные основания.
  **Возобновлено по решению владельца 15.09: «Второй Codex на подготовку».**
  Подготовка probe + два эталона — отдельная новая cx-панель в указанном
  ниже клоне probes, без контекста и чтения клона автора. Автор — другая
  cx-панель, только после принятия/freeze probe. **Независимость снижена:
  одна модель**, изоляция контекста не заменяет независимость backend.
  **15.09 около03:40UTC: владелец подтвердил reset недельной квоты Grok
  через координатора tg-claude-userbot; квотный блокер снят.** Точные остатки
  weekly/5h неизвестны. Одна обычная попытка после reset запущена явным gk:
  `gk-abg-m11-mutations-20260915`, attempt `t-5dc975739851-a01` running,
  наблюдаемая модель Grok4.6 high. Задача прочитана, модель приступила к работе.
  Отдельный клон `/home/user/exec-clones/abg-m11-mutations-20260915`, ветка
  m11-mutations, исходный FINAL7c424f9, push отключён. Задание `cache/m11-mutations-gk.md`,
  watcher `cache/m11-mutations-watch.log`, output `cache/m11/mutations-gk/`.
  Авторский пакет/SHA перед запуском неизменны. Мутации до M12; выжившие
  assertions возвращаются автору cx. Повторный quota error не циклировать.
  Первый Grok run035516-458082: baseline29/postbaseline rc0,12killed/5invalid,
  0survived не означает pass. Исходники/HEAD/restore неизменны. Координатор
  прочитал весь harness/run/test_runner и17patches; возврат тому же Grok
  `cache/m11-mutations-first-return.md`: tracing не видит дочерний copied CLI;
  M07 падает на normal release до exception, M13 неверно назван/может быть
  эквивалентен контракту. Проверить probe-only на авторских tests и добавить
  мутации global browser N/wrapper args/options. Первый пакет сохранён.
  Return run041242-843367:10killed/1survived/0invalid, baseline/postgreen.
  M13 raw survived сохранён, но представленное поведение не нарушает контракт:
  CLI не обязан отсеивать userinfo до HTTP, сервер отклоняет запрос до factory.
  Этот сценарий исключён из квалифицированных мутаций, не переименован в kill.
  M13r отдельно проверяет допустимый response href. Подтверждены пять пробелов
  авторских tests: M03 duplicateJSON, M16 redirect receiver, M18 browserN2,
  M19 token в Docker argv, M20 expected_text/options. Возврат тому же cx
  `cache/m11-mutation-test-fixes.md`; создан test-only e6f7f0c844ebf9fa3d6d1194d921302e8ab1d211,
  предварительно10targetedgreen и пять неизменных Grokpatches red/green.
  На e6f7f0c прошли6AC:413unit/94frozen/live, оба параллельных Codex+Gemini
  reviews нового полного test-delta13851bytes приняты без находок. SHA delta
  3619d038f6eda3bfbc3459aa39d570972d9368d89857242a99294f827a01c972,
  contextSHA e73ddbaea352e5511f86cc24fc7425a2542e686131047651b0b9125207fd5196.
  Координатор прочитал весь delta и REPORT, сверил6команд со спекой, логи,
  canonicaldiff и122manifest entries: `cache/m11/author-test-fixes/`, manifestSHA
  4694cdcbfde05ca64d4118e310bc74f723a2b34cb4cd70c71535246cd3efd387.
  Резервная локальная ветка m11-author-tests-20260915 и проверенный полный
  bundle `cache/m11-author-e6f7f0c.bundle`, SHA256
  d22bb59a7b7f442244de3fb203bdb8f86b9a85e224a9dbb71aee13276b963f27.
  Авторская панель ожидает финальных мутаций перед Grok verify.
  Координатор прочитал return-harness69/204/1012строк, проверил manifests
  16/664/193/244 и source/restore SHA: `cache/m11/coordinator-mutation-return-check.json`.
  До финального независимого прогона Grok исправляет изоляцию child trace-dir
  и добавляет парный instrumentation-on green baseline:
  `cache/m11-mutation-trace-controls.md`. Первый829-строчный harness не был
  сохранён автором до замены; это явно отмечено. На новом FINAL требуется
  полная свежая серия с заранее сохранённым harness, без подмены истории.
  Подготовленный harness/controls разобраны:3instrumentedgreen на исходном
  7c424f9,5harness+104control hashes совпали; childSHA/invocation корректны.
  Оставшаяся правка перед запуском: strict invocation безNone/empty fallback
  и запрет повторного trace-dir. В mutation-клон доставлен чистый e6f7f0c;
  около04:37UTC Grok получил `cache/m11-mutations-final-e6f7f0c.md` на полную
  свежую серию, включая прямые kills пяти новых авторских assertions.
  **Итог на e6f7f0c: независимые Grok-мутации приняты координатором.**
  Полный run044141-1284080:20killed/1M13equivalent/1M19invalid. M19 пойман
  более ранним содержательным запретом token value в argv, harness ожидал
  следующийassertion. Возврат `cache/m11-final-m19-return.md` меняет только
  binding; адресный run044454-1336322 дал1killed, raw первого не переписан.
  Объединение: **21/21 qualified kills, все primary author tests**, 0remaining
  survived/invalid; M13excluded отдельно, один ID не посчитан дважды.
  Baseline/post33green, каждый original baseline с instrumentation-on,
  отдельные trace-dir, exactSHA/invocation/activation/AssertionError/restore.
  Проверены517+50run hashes,5+5harness и9top; всеpatches byte-identical ранее
  прочитанным рецептам, все assertion frames разобраны,71coordinatorcheck pass:
  `cache/m11/coordinator-final-mutation-check.json`. Пакет
  `cache/m11/final-package-e6f7f0c/final-result.md`, SHA256
  2cb1922af4d0cd8fdaddf4db58be018ca63a9ec9d158c74b52f546c4ebe617f0.
  Автор cx получил разрешение на единственный недостающий Grok verify:
  `cache/m11-grok-verify-queued.md`, REVIEW909ed88..FINALe6f7f0c,
  canonical22244bytes SHA77a6ac29e8856a4eec7f516439be1de1e9bb8e1b29a95dc165f91973b0dd079c.
  Новый output `cache/m11/grok-verify/`. Продукт/тесты/BASE не меняются;
  Codex/Gemini и AC не повторяются. Grok mutation-панель idle до финальной сборки.
  Старый объединённый пакет заморожен с раскрытыми symlinks в
  `cache/m11/history/mutation-package-7c424f9-before-author-test-fixes/`.
  Параллельно автор cx был возобновлён для недостающего Grok initial на
  неизменном историческом REVIEW909ed88: задача `cache/m11-grok-initial-only.md`,
  attempt `t-1b0cdfbaed75-a01` running, панель cx-abg-m11-api-cli-20260915,
  модель gpt-6-astra high. Output `cache/m11/grok-initial/`, watcher
  `cache/m11-grok-initial-author-watch.log`. Initial завершён04:18UTC, rc0,
  полный отрицательный вердикт: две находки, обе уже fixed вdb83793/7c424f9.
  Канонический input99844bytes SHAd1ac722a8a6c783cc3083d4b9f0c24180eb9e77b358fb23b9d4e62409316ba9c;
  manifest52entries проверен. Оговорка: raw упоминает поздние commits и прежние
  Codex reviews, строгая независимость initial не подтверждена. Receipt/raw
  и оговорка сохранены; успешный historical initial не повторяется.
  Эта же cx-панель закрыла пять test-gaps и выполняет Grok verify после
  принятия независимых мутаций. Продукт неизменен.
  Контракт/BASE и остальные требования приёмки неизменны. Блокер машинной
  оснастки всё ещё воспроизводим по текущему исходнику; чужие scripts не менять.
  Дополнительная зависимость машинного gate: accept_run.py:300 требует
  пару agy+grok для executor.backend=codex. После результата мутаций завершить
  оставшиеся reviews на точных снимках, не повторяя валидные Codex/Gemini.
  Сохранить готовую реализацию/доступные проверки, затем завершить оставшиеся
  квитанции и полный gate после исправления оснастки. Подмена backend/квитанций запрещена.
  BASE обоих клонов f336f266e22b5b5c6a31b3c30806c617f6fd3276. Подготовка:
  `/home/user/exec-clones/abg-m11-probes-20260915`, ветка m11-probes,
  `gk-abg-m11-probes-20260915`, attempt t-a8c73d0e9e83-a01 blocked.
  Первый модельный запрос отклонён: `You hit your weekly limit.` Повтора нет;
  launcher rc0 означает только открытие TUI. Grok weekly=0, reset/5h неизвестны.
  Панель закрыта после сохранения ошибки; клон чист, probe/эталонов ещё нет.
  Сырой лог `cache/m11-grok-quota.log`, SHA256
  632689b46fcfdf68e347d76f09724437c359598ded7014521ce249d5e9caafab;
  точный handoff `cache/m11-probe-quota-blocked.md`.
  Задание `cache/m11-probe-preparation.md`, пакет `cache/m11/probe/`,
  watcher `cache/m11-probes-watch.log`. Клон автора заранее создан:
  `/home/user/exec-clones/abg-m11-api-cli-20260915`, ветка m11-api-cli;
  подготовка принята; автор запущен отдельной панелью
  `cx-abg-m11-api-cli-20260915`, attempt t-4b15b59fa8c8-a01 blocked.
  Watcher `cache/m11-author-watch.log`; пакет автора `cache/m11/author/`.
  Первый пакет3685bdc54644918d820cbecdef14617ab2b11bcc возвращён:
  403unit/94frozen/live+6AC rc0, но reviews ещё не вызваны — full.diff102280
  байт (SHA2b91f1b85095c4d49575a004255310ad5d5a5ef0555733db55a7113c0f49044e),
  выше100k. Gate4 на metadata, не повторялAC. Все36artifacthashes совпали.
  Координатор прочитал весь новый код/tests/live/README/измененияспеки;
  обнаружены canonical безhref и чрезмерная requestвалидация link.href вCLI.
  Единый возврат тому же cx: `cache/m11-author-first-return.md`, исправить
  двадефекта и сократить новый README/полныйdiff безослабления, затем доступные
  Codex+Gemini reviews. Первыйпакет сохранён `cache/m11/initial-blocked-3685/`.
  Коммит дополнительно сохранён локально в m11-author-work-20260915;
  НЕ принят, не слит/не отправлен вorigin. Grok gate/мутации всёещё pending.
  Исправления первого возврата закоммичены в909ed88c7aacfaeae489968d022d86831dff6df9;
  полный initial diff99844bytes, SHAd1ac722a8a6c783cc3083d4b9f0c24180eb9e77b358fb23b9d4e62409316ba9c.
  Координатор прочитал весь delta; сокращённый live сохраняет assertions и
  использует существующий JS-стенд M10. Gemini initial rc0/no findings;
  Codex initial нашёл три дефекта Markdown, автор воспроизвёл их в Docker.
  Исправления db83793c8415e5e267bfe2f3d784ea34b1919115: глубокий HTML,
  implicit head и экранирование видимого текста. Полный delta прочитан;
  доступный verify завершён; его находка закрыта возвратом ниже.
  Заметки `cache/m11-review-progress.md`; отложенный mutation task подготовлен
  в `cache/m11-mutations-draft.md` (DRAFT, без launch до reset/final SHA).

  **Итоговый handoff 15.09, около03:37UTC.** Автор FINAL
  `7c424f9aaf484e6132319a4d09da6d75d3128fcf`, initial REVIEW
  `909ed88c7aacfaeae489968d022d86831dff6df9`; BASE сохранён. Подтверждённые
  дефекты закрыты тем же cx: canonical, response URLs, глубокий HTML,
  implicit head, Markdown literal/alt/equals и destinations. Координатор
  прочитал полный initial и все последующие delta; продукт сам не правил.
  Все6авторских AC на FINAL rc0:409unit,94frozen, live CLI→API→реальный
  ProductFetcher→JS patchright, wrongtoken/okfalse и scoped cleanup.
  Codex принял новый полный delta; Gemini принял его прямым штатным ask-agy,
  rc0/no findings. Доступные ревью завершены, повторять их на том же коде не надо.
  Initial99844bytes, исправленный delta8960bytes — полные, без усечения.

  Пакет `cache/m11/author/`, report SHA256
  be64ad3c7196f1fc524f0239018346555c11f0311bc2c635fd13e6053ba0ddb3;
  manifest148entries, SHA5218b9f11ffa46b0440655d91cedc16100691f586acdcaa006554693b32fdb78.
  Все148хешей, ACcommands/logs, metadata и оригинальные receipts сверены;
  `cache/m11-coordinator-packet-check.json`. История `cache/m11/author-history/`.
  Коммиты сохранены в авторском клоне, локальной m11-author-work-20260915 и
  проверенном bundle `cache/m11-author-7c424f9.bundle`, SHA256
  7c3f524f2ee8320dcb6bd3aa42e54a6ac7e5ceeed68884d33af44e864f9f8e48.
  Код НЕ принят/не слит/не отправлен в origin. Завершённая авторская панель
  закрыта после проверки пустого ввода, фоновых исполнительских задач нет.

  **Исторические блокеры на03:37UTC (квотный снят сообщением выше):** (1) Grok weekly0: после reset независимые reviews
  и мутации новых M11 tests на FINAL; очередь `cache/m11-mutations-queued.md`,
  запуск только явный gk после подтверждённого reset, без quota retry цикла.
  (2) За владельцем оснастки tg-claude-userbot: поддержать явный возврат приёмки
  на неизменном BASE. review_run отверг новый verify rc2 из-за старой успешной
  фазы; accept_run на FINAL rc3 «verify-agy-1.json: устаревший snapshot_sha/range».
  Гейт остановился на metadata, AC он не повторял. Старые receipts сохранены
  на исходных местах; прямой Gemini не выдан за machine receipt. Разбор и
  требования: `cache/m11-review-journal-blocker.md`; чужие scripts не менялись.
  После снятия обоих блокеров — полный пакет Grok и одна финальная независимая
  приёмка координатора с accept_run/сквозным сценарием. Собственный финальный
  gate ещё не запускался на неполном пакете. **До этого M12 не начинать.**
  В обоих клонах origin push отключён.
  Окончательный контракт SHA256
  80248e5768bd165f0e8ea4e0686e704f0c381b74030e4008b87569e3ec2a59ce.
  Старое Grok-задание сохранено как история; новое задание подготовки:
  `cache/m11-probe-preparation-cx.md`. Запущена новая панель
  `cx-abg-m11-probes-20260915`, attempt t-4106a3e48244-a01 accepted.
  Панель закрыта после готового пакета; watcher `cache/m11-probes-cx-watch.log`.
  Принятый probe commit f2ef5633bf9f574772fca9d4ee44d2ff010971bf,
  дополнительно опубликован в origin/accepted-m11-probes-20260915,
  SHA509d765167bd322d0b2f5c40127a95ed977760af8bd4a35c03a830267dc10997,
  40049bytes,18methods. Координатор прочитал весьprobe/обаэталона/скрипты;
  319hashes проверены, BASEred и обаcorrectrefgreen обоимиentrypoints,
  16/16 assertionkills на одномSHA. Пакет `cache/m11/probe/preparation-result.md`,
  SHAa93c5ff6a18231d14269e50207f92353053078f390bea0ce698e0e1456b280b5.
  Обе серии замечаний закрыты: APIoptions/N2, header/default overspec,
  MarkdownURLs, nav/headerlinks/meta, URLvalidationB. История сохранена.
  Автору передан byte-identical probe и короткий `cache/m11/author/probe-baseline.md`,
  без временных эталонов/обходов/контекста подготовительной панели. После reset Grok — одна
  обычная попытка независимых мутаций, quotaerror не циклировать.
  Окончательная копия execution-спеки `cache/m11-api-cli-frozen.md`;
  placeholders удалены, в клон автора доставлена, preflight pass6критериев.
  Ранние draft-файлы больше не являются заданиями.
  BASE и контракт задним числом не менять. После принятой M11 продолжить M12.
  Транспорт M10 не переписывать; `cf-fetch` и потребителей не переключать.

- [ ] **M16 — IN_PROGRESS 18.09.2026: ложная `captcha` на честном HTTP 200.**
  Корень: `detect_challenge` объявляет `captcha`, когда в теле есть ЛЮБАЯ одна
  решающая метка. На lowendtalk.com это `/cdn-cgi/challenge-platform/.../jsd/main.js`
  (Cloudflare вставляет его в обычные страницы) плюс невидимая reCAPTCHA v3
  `recaptcha/api.js?render=…`. Замер на проде до фикса: без `expected_text`
  ответ `ok=False, error_type=interactive_challenge, step=human`, одна попытка
  `curl_cffi/interactive_challenge/captcha/275/human` — лестница отказывается
  и браузер не пробует.
  - M16a `docs/specs/m16a-captcha-false-positive.md`: `captcha` требует
    достаточной улики в теле (title «just a moment» или ≥2 решающих меток);
    заголовок `cf-mitigated` и 403/429 остаются подтверждением. Первая попытка —
    blocked на AC-111: мутант 27 в оснастке указывал на код `execute.py`,
    переписанный вехой M13. Оснастка починена на main (`1fd9761`, 105/105 убиты),
    спека пересажена на новый BASE, веха перезапущена и влита (`6b21e6f`):
    machine_pass 8/8, agy — принято, независимые мутации Grok 21 kill / 2 survivor /
    3 equivalent (откат правки убивается; выжили `status >= 400` вместо
    `in (403, 429)` и регистр body-игл — обе дыры закрывает M16a-fix).
  - M16a-fix (решение владельца 18.09.2026 на находку Codex «не принимать»):
    правка ослабила детектор для страницы-заслона с ИНТЕРАКТИВНЫМ виджетом на
    HTTP 200. Различаем по разметке: невидимая reCAPTCHA v3 (`api.js?render=`,
    `grecaptcha.execute`) уликой не считается, видимый виджет (`g-recaptcha`,
    `data-sitekey`, `h-captcha`, `cf-turnstile`) — считается. Заодно закрыть оба
    выживших мутанта и убрать из `captcha_confirmed` два недостижимых дизъюнкта.
  - M16a-fix2 `docs/specs/m16a-fix2-widget-edges.md` (на находки Codex по
    M16a-fix): `render=explicit` — интерактивный виджет, разбор разметки
    `HTMLParser`ом, содержимое `<template>` инертно. machine_pass 7/7,
    agy — принято без находок.
  - M16a-fix3 `docs/specs/m16a-fix3-charrefs-and-template.md` (на четыре
    находки Codex по fix2, все воспроизведены координатором): `html.unescape`
    падает с `ValueError` на числовой сущности длиннее 4300 цифр — на трёх
    маршрутах (`_title`, `html_to_text`, `feed`), а самозакрытый `<template/>`
    через `handle_startendtag` не считался открывающим и давал ложную
    `captcha`. Клипуем out-of-range сущности в U+FFFD на входе, снимаем
    `try/except` вокруг `feed`, переопределяем `handle_startendtag`.
    ПРИНЯТА и влита в main 18.09.2026 (merge `00959e2`, цепочка fix+fix2+fix3):
    machine_pass 8/8, 569 unit + 125 frozen probes, дифф прочитан
    координатором; независимые мутации Grok 23 kill / 2 survivor / 5
    equivalent / 0 invalid, все пять обязательных откатов убиты; agy сломался
    (вместо вердикта стена нулей) — soft-fail.
    Живой стенд (улики в `/home/user/.cache/abg-coord-20260918/m16a-fix3-live/`):
    lowendtalk.com теперь `ok=true`, `curl_cffi` 200 `challenge=none` 201 мс,
    `step=stop` — против `ok=false`/`interactive_challenge`/`human` на проде;
    bizprofile.net обе цели `ok=true` через scrapling.
  - M16a-fix4 `docs/specs/m16a-fix4-format-charrefs.md` (находка Codex по fix3,
    воспроизведена координатором): тот же лимит 4300 цифр остался в ПРОДУКТЕ —
    `gateway/format_html.py` кормит сырое тело `HTMLParser` с
    `convert_charrefs=True`, и форматы `markdown`/`links`/`meta` отвечают
    HTTP 500. Путь открыла именно fix3 (раньше страница роняла детектор и до
    форматтера не доходила), поэтому чиним ДО деплоя M16b.
  - M16a-fix5 (черновик) — только тесты: шесть выживших мутантов из
    независимого прогона Grok по fix2, все covered-but-not-asserted.
  - M16b — выкладка фикса детектора на stand-host (детектор бинд-маунтится из релиза,
    пересборка провайдерского образа не нужна).

- [x] **M15 — COMPLETED 17.09.2026 (release `58d3b73` выкачен), решение владельца 17.09.2026** («Лимит + переход
  дальше» — закрывает открытый риск M14: зависшая HTTP-ступень съедала весь бюджет).
  - M15a `docs/specs/m15a-http-timeout.md`: http/egress-ступень ограничена 15 с,
    её `timeout` ведёт к браузеру/следующему egress. machine_pass 7/7, Codex и
    agy — ПРИНЯТО без находок, мутации координатора 10/10 убиты (не Grok).
    Влито в main.
  - M15b `docs/specs/m15b-deploy.md`: первая попытка — blocked на дефекте спеки
    (не было `--check-profiles` перед `--check-api-egress`), прод не тронут.
    Вторая: сервис на `58d3b73`, откат на `b31a36b` (`compose.env.pre-m15b`).
    machine_pass 9/9, Codex — ПРИНЯТО, healthchecks up без флипов. Таймаут-ветка
    задета вживую: chatgpt share `curl_cffi timeout → patchright` 22 с (в M14b —
    `timeout` за 120 с); на перепрогоне chatgpt взят curl_cffi за 2,8 с. 6/6 целей.

- [x] **M14 — COMPLETED 17.09.2026 (release `b31a36b` выкачен), решение владельца 17.09.2026** («Сразу curl_cffi в
  лестницу» — на вопрос, почему продукт не использует curl_cffi для простых блоков).
  - M14a `docs/specs/m14a-curl-cffi-ladder.md` (`7e49529`) → Codex: таймаут
    curl_cffi = provider_error, live-тесты ждут curl. M14a-fix (`78b0c8f`):
    таймаут проверен вживую (10.255.255.1 → `timeout`), Codex и agy — ПРИНЯТО.
    Обратные мутации http/egress убиты (28/14). Влито в main.
  - Известное: lowendtalk через curl_cffi отдаёт настоящую страницу, но
    детектор `body_captcha` → эскалация в браузер (детектор не менялся).
  - M14b `docs/specs/m14b-deploy.md`: сервис на `b31a36b`. Исполнитель 8/10:
    AC-875 (no-auth → connection_error при повторе) и AC-878 (chatgpt timeout
    120 с) — разовые; перепрогон координатора на живом сервисе: 6/6 целей
    (chatgpt curl_cffi 4,1 с, lowendtalk curl_cffi 1,0 с), 407 ok, 15 профилей,
    ротация ms1→ms2→ms3 на curl_cffi, healthchecks без пропусков. Codex — ПРИНЯТО.
  - Открытый риск (не в работе): зависшая HTTP-ступень съедает весь бюджет, а
    `timeout` останавливает лестницу без браузера (так было и с curl).

- [x] **M13 — COMPLETED 17.09.2026 (влито в main, release `4409f8a` выкачен), директива владельца 17.09.2026** («доделывай всё до
  конца», проверить bizprofile.net через продукт; выбраны: уборка поздних
  контейнеров, bizprofile без expected_text, запись замера).
  Замер координатора через deployed API: с `expected_text` главная, `/ny/albany`
  и карточка компании — `ok:true` через scrapling (≈17 с на попытку); без него —
  `ok:false`. Корень: Scrapling после решения challenge отдаёт status 200 и
  настоящее тело, но заголовки challenge-ответа с `cf-mitigated: challenge` →
  детектор `suspected`. Правка в адаптере, не в policy M10 (frozen probe M10
  требует отвергать suspected без подтверждения).
  - M13a `docs/specs/m13a-scrapling-headers.md`: FINAL `c0a6f17`, machine_pass
    (live bizprofile без expected_text: scrapling 200/none, 21–24 с). Codex
    result review: НЕ ПРИНИМАТЬ — 200 + cf-mitigated + captcha-атрибут в теле
    после удаления заголовка → `none` (подтверждено вызовом детектора);
    `tests/mutation_gate_scrapling.py` ссылается на удалённый тест. agy — без
    находок. Мутации по `c0a6f17` остановлены (abandoned).
  - M13a-fix `docs/specs/m13a-fix.md`: FINAL `c32da3c`, machine_pass (6/6
    перезапущено). Codex: одиночный решающий CF-маркер (`cf_chl_opt`) без
    заголовка → `none`. agy — без находок. Мутации по `c32da3c` остановлены.
  - M13a-fix2 `docs/specs/m13a-fix2.md`: FINAL `375bdbf`, machine_pass (6/6,
    live зелёный). Codex: `challenge-platform` ловит и `orchestrate/chl_page`;
    тело без CF-маркеров (самописная captcha) теряет заголовок. Выбор владельца
    17.09: сузить до `/scripts/jsd/`, остаток принять и записать в research 08.
  - M13a-fix3 (`647b193`, только пассивный jsd-путь) → Codex: Turnstile и
    прочие CF-строки не дают правил детектора. M13a-fix4 (`5b604c9`): заголовок
    сохраняется при любой CF-строке вне jsd-пути. Codex — ПРИНЯТО, agy — без
    находок. Мутации (38): 28 kill, 9 equivalent с доказательством, выжил M25
    (смешанный регистр jsd-пути). M13a-fix5 (`027f1f8`, только тест): убивает
    M25 (перепроверено координатором на копии), machine_pass 6/6.
  - M13b probe принят и влит (`3a55167`): BASE red 2/6 на позднем контейнере,
    эталоны name/label green с frozen M9/M12 (перепроверено координатором).
  - M13b-fix `docs/specs/m13b-fix.md`: FINAL `858fd85`, machine_pass (5/5).
    Codex: при заполненном cidfile и уже удалённом контейнере `rm` крутится все
    30 с (бюджет 1 с → 31 с, держит LaunchGate). agy — без находок. Мутации
    `docs/specs/m13b-mutations.md` по `858fd85` остановлены.
  - M13b-fix2 (`498c4d3`) → agy: горячий цикл повторного rm. M13b-fix3
    (`49a876f`, пауза между rm) → Codex: короткие ID из `docker ps`. M13b-fix4
    (`9c23c17`, `--no-trunc`): Codex — единственная находка отклонена (нужен
    доступ к Docker-сокету = root), agy — без находок. Мутации (30): 28 kill,
    выжили M03 (ловит только frozen probe) и M28 (лишняя пауза) → M13b-fix5
    (`48f4c96`, тесты): убивает оба (перепроверено координатором), Codex —
    ПРИНЯТО.
  - M13a-fix5 и M13b-fix5 влиты в main (`5139bb6`, `3285539`): 520 unit и 125
    frozen probe зелёные.
  - M13c `docs/specs/m13c-deploy.md` (план через Codex, 4 исправления): FINAL
    `123bffe`, сервис на `4409f8a`, откат `929bded` цел. 8/8 AC перезапущены
    координатором; bizprofile без expected_text зелёный в трёх замерах и
    через CLI (карточка, 23 с); 6 целей ok; healthchecks — пинги раз в 60 с
    без пропуска на перезапуске. Codex и agy — ПРИНЯТО. Мутации (40): 39 kill,
    выжил M37 (нет проверки Authorization) → M13c-fix (`eec0287`, тест, убивает
    M37 — перепроверено). Влито в main (`341c6be`).

- [x] **M12 — COMPLETED 17.09.2026 (M12a и M12b влиты в main, сервис выкачен).**
  Владелец: «доделай оставшиеся задачи через кодекс». Выбор владельца: ВСЁ
  через cx (probe/мутации и исправление — разные cx-панели, разные клоны),
  объём — M12a до приёмки и M12b деплой. Это заменяет «возврат M12a — Grok».
  Клон подготовки пересоздан на `62de539` (прежний удалён), базовая линия
  6 авторских tests green. Спека подготовки дополнена директивой, SHA256
  `0851322f147deb88ca5ed38fcf78436eb0d41714e6cfcf051516ac2cec5e6d81`;
  запущена панель `cx-abg-m12a-shutdown-probes-20260915`.

  **17.09 02:15 UTC — подготовка принята, исправление запущено.** Пакет
  `~/.cache/abg-coord-20260915/m12/shutdown-probe/`: probe
  `tests/probe_m12_service_regressions.py` SHA256 `f7ab236f…ecad` (коммит
  `06c2a3f`, ветка `m12a-shutdown-probes` забрана в репо). Координатор
  перепроверил в Docker: BASE assertion-red 5/5, reference-1/2 green, эталоны
  меняют только `service.py` и `abg-release`. Мутации авторских tests:
  8 kills / 15 survivors / 1 equivalent; live с пассивным monitor прошёл rc=0
  (дыра F006 подтверждена). Спека `docs/specs/m12a-fix.md` (`fffee6b`):
  plan-review Codex — 2 находки по AC-404, обе приняты; agy — «находок нет».
  Клон `abg-m12a-fix-20260917` (ветка m12a-fix, push DISABLED), панель
  `cx-abg-m12a-fix-20260917` busy.

  **17.09 03:00 UTC — M12a-fix сдана, приёмка идёт.** FINAL `aaf5ca7` (ветка
  `m12a-fix` забрана). Координатор перезапустил все AC: 452 unit OK, frozen
  probes OK, live rc=0 (sidecar-пинги из Compose, egress alpha/beta), дифф
  прочитан целиком. accept_run невыполним для этой попытки: диапазон
  BASE..REVIEW 124578 Б > 100000 из-за frozen-входов и в спеке была неверная
  пара ревьюеров (для cx нужны agy+grok) — ошибка спеки, попытка закрыта
  `blocked`. Ревью кода f58075b..aaf5ca7: agy — «находок нет»; Codex — одна
  находка (таймаут клиента до записи cidfile → поздний контейнер после
  финального sweep), подтверждена, но корень во frozen
  `bench/runner/execute.py` и был до M12 → бэклог. Мутации (отдельная cx):
  32 → 29 kill / 3 survivor (M03 strip токена, M29 stop в обработчике,
  M30 порядок финального sweep); frozen probes их тоже не ловят. Запущена
  веха только тестов `docs/specs/m12a-tests.md` от `aaf5ca7`, панель
  `cx-abg-m12a-tests-20260917`.

  **17.09 03:15 UTC — M12a ПРИНЯТА и влита в main merge `929bded`.** Веха
  тестов `m12a-tests` FINAL `b51a7ae`: M03/M29/M30 убиты assertion, accept_run
  координатора machine_pass (agy+grok receipts), 455 unit OK на main. Продукт
  с `aaf5ca7` не менялся — live координатора rc=0 на нём остаётся в силе.
  Healthchecks-чек `ai-browser-gateway-health` (timeout 120/grace 60) создан
  координатором, ping URL только в `services/ai-browser-gateway/secrets/hc-ping`
  (0600). Спека M12b `docs/specs/m12b-deploy.md`: plan-review Codex 6 и agy 5
  находок — все приняты и внесены.

  **17.09 04:30 UTC — M12b выкачена, приёмка идёт.** Сервис
  `/home/user/services/ai-browser-gateway` (Compose-проект
  `ai-browser-gateway`, instance `stand-host`, 127.0.0.1:8765, release `929bded`,
  образ `abg-runtime:929bded313e3`) работает. Ветка `m12b-deploy` FINAL
  `25dfa5c` забрана, не влита. accept_run координатора: 8/8 AC machine_pass
  (15 прокси с разными IP, 407 без auth, ротация через API ms6→ms7→ms8, 6/6
  целей ok, CLI ok). Healthchecks: автоматические success каждые 60 с;
  stop api 04:05:54 → fail 04:06:25, start 04:06:27 → success 04:07:26.
  Result-review: agy «находок нет»; Codex 3 подтверждённые (check_deploy
  пишет через abg-release prepare, parse_api терпит неизвестные значения,
  README откат перекрывается экспортом). Мутации runner-тестов: 28 → 23 kill
  / 5 survivor (M07, M09, M10, M11, M21). Всё ушло в веху
  `docs/specs/m12b-fix.md` от `25dfa5c`, панель `cx-abg-m12b-fix-20260917`.

  **17.09 05:05 UTC — M12b ПРИНЯТА и влита в main merge `ecac586`.** Цепочка
  `m12b-deploy` `25dfa5c` → `m12b-fix` `895bc83` (read-only сверка release,
  строгая схема API, README откат через `env -u`) → `m12b-fix2` `d789e22`
  (окно 150 с для ошибок доставки monitor; прежний сбой — единственный
  URLError от намеренной остановки api координатором). Мутации новых тестов
  36/36 kill. accept_run fix2 machine_pass; координатор на финальном коде
  перезапустил no-write, egress (ms11→ms12→ms13) и 6/6 целей — rc=0; 495 unit
  OK на main. Сервис работает, healthchecks `up`.

  **Бэклог M12:** DockerLauncher — уборка контейнера, созданного демоном после
  таймаута клиента без cidfile (поиск по `abg.request`-label).

  **История — остановка финишной директивой владельца 15.09.2026.**
  **Актуальный handoff, 11:54 UTC:** завершить сессию; новых исполнителей,
  вех и разведок НЕ запускать. Это отменяет прежнее «форсируй все задачи»,
  в том числе историческое разрешение в подготовленных спеках. Автозапуск
  отменён, дальнейшая работа — только после новой директивы владельца.

  **Что сохранено за сессию:** M11 влита merge `e5fd997` из FINAL `e6f7f0c`,
  статус опубликован `92d8ad5`. Разведка M12 и независимый исходный probe
  приняты (`a3e79c0`, `0d29285`); сам probe опубликован отдельной веткой ниже.
  Контракт — `89a7c95`, execution-спека — `2612e21`, принятый baseline и старт
  Grok — `241b1e8`. Возобновление — `7ca38c1`; подготовка возврата, полный
  разбор и очередь — `c45cbbb`, `7417bdd`, `d1ecbbc`. Все эти коммиты в
  origin/main. В M12 в main менялась документация; код сервиса туда не влит.

  **Состояние реализации M12a:** пакет Grok сохранён;
  `t-4d3f90646502-a01` завершена blocked, idle-панель закрыта.
  Собственный полный разбор: `docs/specs/m12a-return-findings.md` — shutdown,
  незакрытый sidecar live, Unicode URL и symlink manifest, пробелы tests/live.
  REVIEW `53ca5f95babb157885bb44d0ae0a428360aa6704`, FINAL
  `62de539f586b95e6aeb971c3ab1f51e6f7080260`, handoff_status=needs_owner.
  verify-codex-1:F001: ожидающий browser semaphore обработчик может создать
  provider после последнего sweep при shutdown. Sleep0.2 и повторная уборка
  гонку не закрывают. Код НЕ принят/НЕ влит/НЕ опубликован; M12b ещё не начата.
  По действующему правилу исправление пойдёт новой вехой BASE=этот FINAL.
  Чтобы собрать единый список, подготовлено независимое задание
  `docs/specs/m12a-shutdown-probes.md`: мутации шести новых авторских unit-tests
  и frozen regression probe shutdown/URL/manifest с двумя эталонами/обходами;
  отдельно один live-мутант выключенного Compose-sidecar.
  Клон `/home/user/exec-clones/abg-m12a-shutdown-probes-20260915`, branch
  m12a-shutdown-probes, BASE=62de539, push DISABLED. Задание НЕ запускалось:
  сначала мешали общие/cx слоты; до освобождения слота владелец отменил запуск.
  Нового `tests/probe_m12_service_regressions.py` и пакета подготовки ещё нет.
  Ожидаемый каталог будущего пакета — `m12/shutdown-probe/` в cache ниже.

  **Отмена очереди:** собственный capacity watcher PID `3401269` завершён;
  `/proc/3401269` отсутствует. В `/home/user/.cache/abg-coord-20260915/m12/`
  `cx-queued-launch.json` записан как `cancelled_by_owner`, `auto_launch=false`,
  `prior_launch=null`; до отмены файл результата запуска отсутствовал.
  Маркер `cx-capacity.cancelled` содержит время отмены. Скрипт переименован в
  `cx-capacity-watch.py.disabled`, PID-файл — в `cx-capacity.pid.stopped`;
  журнал `cx-capacity.log` сохранён. Действующего автозапуска нет.
  Журнал проекта вернул `attempts=[]`, `undelivered=[]`; своих исполнительских
  панелей нет. Сессия координатора — `cxc-ai-browser-gateway`, её закрытие
  остаётся управляющей сессии после этого handoff. Чужие панели не трогались.

  **Точные команды продолжения — выполнять только по новой директиве.**
  Сначала проверить текущее состояние и свободные слоты, не восстанавливать
  отменённый capacity watcher и не повторять принятые подготовительные прогоны:

  ```bash
  cd /home/user/github/ai-browser-gateway
  git pull --rebase
  git status --short --branch
  python3 /home/user/.claude/skills/executor-milestone/scripts/run_journal.py list --json
  git -C /home/user/exec-clones/abg-m12a-shutdown-probes-20260915 status --short --branch
  git -C /home/user/exec-clones/abg-m12a-shutdown-probes-20260915 rev-parse HEAD
  git -C /home/user/exec-clones/abg-m12a-shutdown-probes-20260915 remote get-url --push origin
  sha256sum docs/specs/m12a-shutdown-probes.md
  ```

  Ожидается чистый клон на полном FINAL выше, push URL `DISABLED`.
  SHA256 подготовленной спеки:
  `edb4d4d8c200a6748a72eed8d435232633e2a2f8a964e275d66f69d91ad2139f`.
  Затем один ручной запуск подготовленного независимого задания:

  ```bash
  EXECUTOR_OWNER_SESSION=cxc-ai-browser-gateway \
    bash /home/user/.claude/skills/executor-milestone/scripts/launch_executor.sh cx \
    /home/user/exec-clones/abg-m12a-shutdown-probes-20260915 \
    --task-file /home/user/github/ai-browser-gateway/docs/specs/m12a-shutdown-probes.md
  ```

  Только после успешного запуска — свой сторож вне каталога пакета:

  ```bash
  nohup setsid bash /home/user/.claude/skills/executor-milestone/scripts/watch_executor_panes.sh \
    cx-abg-m12a-shutdown-probes-20260915 \
    > /home/user/.cache/abg-coord-20260915/m12/watch-shutdown-probe.log 2>&1 < /dev/null &
  echo "$!" > /home/user/.cache/abg-coord-20260915/m12/watch-shutdown-probe.pid
  ```

  После приёмки подготовки — новая execution-спека и новый клон от FINAL
  `62de539` для Grok, закрывающие единый список дефектов. Эта новая execution-
  спека ещё НЕ составлена. Старую `m12a-service.md` повторно не запускать.
  `cx` здесь только независимый проверяющий; реализация остаётся у Grok с
  учётом последних фактических квот. Лимиты/квоты не обходить.

  Execution-спека `docs/specs/m12a-service.md`, SHA256
  `5acfb7e415b6e23d636537877caed13a3bcf54d9ee7575ab90199169695faeb9`.
  Клон `/home/user/exec-clones/abg-m12a-service-20260915`, ветка m12a-service,
  BASE `7ca38c1aa62174a0a1de1a7685fee268c2ba2042`, origin push DISABLED.
  Static preflight pass6критериев. Baseline-подготовка `t-706cc296943e-a01`
  принята; исходные413unit green, прежние94frozen green, новые20probe red
  ровно по отсутствующим API. AC-303/305 red по отсутствующей реализации,
  AC-304/306 green; все6команд посимвольно совпали, HEAD/spec/probe unchanged.
  Пакет `/home/user/.cache/abg-coord-20260915/m12/preflight/result.md`, SHA256
  `692c24b2b5dcf64de4c5c1efe3d6da786b75ed98d457ba404482128276f83408`;
  manifest `cada547aa215be330660d4ef12d42576c774fef364e5e7c1e43170ff3e2474ab`,
  21хеш проверен. Свои test-containers отсутствуют, добавившиеся MCPsidecars
  отделены по образам/времени; чужие контейнеры не трогались. Подготовительная
  панель закрыта idle с пустым вводом, реализация запущена отдельным заданием.
  Пакет автора в `m12/author/`:46datahashes совпали, одна самоссылка manifest
  некорректна и отдельно учтена; полный diff/review inputs/response hashes
  сверены. Подробные SHA и локальный bundle — в return-findings. При упаковке
  автор пересоздал каталог и удалил прежние watch.log/watch.pid; новых
  сторожей держать снаружи пакета. Панель закрыта idle, своих provider labels
  не осталось. Старый preflight-сторож завершён по проверенному собственному
  PID. Следующий шаг — независимая
  подготовка, затем новая спека/клон/Grok для исправления после verify.
  Полная приёмка/diff/reviews/v2gate/live и merge — после закрытия дефектов.
  План следующего этапа `docs/specs/m12b-deployment-plan.md` ещё НЕ execution-
  спека; production deployment возможен после приёмки M12a и возобновления.
  Production-сервис, credentials, внешние цели и healthchecks в этой части
  сессии не менялись; сервис пока не готов.
  **История предыдущего handoff, до реализации M12a:**
  `cx-abg-m12a-probes-20260915` завершён,
  подготовка принята; панель закрыта после пустого ввода, отсутствия фоновых
  команд и своих Docker-контейнеров. Попытка `t-32c88bfc1f12-a01` accepted.
  На момент прежнего handoff реализация ещё не начиналась; текущий статус выше.

  Принятый probe: commit `6b54caf5ecf6687958fda86a07d88f87152e824a`,
  опубликован в `origin/accepted-m12a-probes-20260915`, в main не влит:
  он проверяет ещё отсутствующий M12service. Единственный новый файл
  `tests/probe_m12_service.py`, 36067bytes,20testmethods, SHA256
  `2b5713ea3d3b743a6c469bd26bd893cb343f132b83deb7eadc6182e007ad71e0`.
  Клон `/home/user/exec-clones/abg-m12a-probes-20260915`, BASE
  `89a7c9535ffcdc461a7f10707a679e13a08300ae`, clean, origin push DISABLED.
  Исполнитель cx/gpt-6-astra high; код сервиса он не писал.

  Пакет `/home/user/.cache/abg-coord-20260915/m12/probe/preparation-result.md`,
  SHA256 `e3051b4cec6182f35123b646ac244266a9e22ec35928ed256184d288538a0298`.
  Manifest `c1a4d5d7194ad4c2046214ee3426883c8acf87681b0499224e449e97f3c7cd3e`:
  795datahashes/modes/size совпали;2самоссылочные записи отдельно (797entries).
  Координатор прочитал весьprobe, обаэталона, runner/mutations/audit/package;
  проверил36семантических отказов (18вариантов ×2эталона), source/restoreSHA,
  строкиassertions, неизменностьprobe/контракта и378metadata-checks.
  Собственный Docker1002:1002 replay: BASE rc1,20missing-APIassertions/0errors;
  эталонA20/20rc0 (35.401s), эталонB20/20rc0 (35.210s). Все мутации —
  содержательныеassertion-red,0survivors/fixtureerrors; эталоны восстановлены.
  Логи/команды/rc: `m12/acceptance/{replay.json,base.log,reference-a.log,
  reference-b.log,evidence-check.json,scoped-containers.json}` вcacheвыше.

  Это приёмка независимого probe, НЕ реализации/деплоя M12a. Машинный v2gate
  и продуктовые Codex/Gemini reviews здесь не заявлены: подготовительное
  задание их не требовало. Пробник использует PythonCLI и fakegit archive;
  настоящий git/runtime/Compose/labels/cleanup/browser/live остаются будущей
  приёмке. Новые авторскиеtests будущего продукта потребуют чужихмутаций.
  Эталоны/обходы/контекст подготовки НЕ передавать автору продукта; только
  byte-identicalprobe и `m12/probe/probe-baseline.md` после нового разрешения.
  Дополнительный полный bundle `m12/accepted-m12a-probes.bundle`, проверен,
  SHA256 `6af7f93c0c59c151425705fcd6be7bbacb9d505679ae7a0ef8bf44a29dc3ab26`.

  Разведка M12 Grok ранее принята (`t-8f6a9317325f-a01`), панель закрыта:
  `m12/recon-result.md` SHA256
  `ceaf2f6efcad8cb8027fef695bd5903de2ad3140e3e3cc21491eb408ac9543e7`,
  manifest `d664cf0247deff90aede572b187a0703a34c36e1cc70fc98fd01f5c872450b22`,
  78hashes pass; round1/unknown historicalrc сохранены. Service-dir отсутствовал,
  8765свободен, socketgid983, registry Python3.14.7/DockerCLI29.8.0 проверены.
  Контракт `docs/specs/m12a-service-contract.md` вmain (`89a7c95`), SHA256
  `9231045abeef2a7eef8722ac655f4121d824bdec883d50f421654917b88b58df`.
  Черновик `m12/m12a-execution-draft.md` вcache имеет HOLD/placeholders,
  устарел после опубликованной execution-спеки и не разрешён к запуску.
  Текущая точка продолжения — возврат от FINAL выше, затем приёмка M12a
  и M12b deployment/15proxy/6targets по отдельной будущей execution-спеке.
  Разрез на два этапа выбран при пустом ответе на вопрос, скоуп не снят.
  Compose в
  `/home/user/services/ai-browser-gateway/`, только loopback-публикация,
  Docker1002, проверенные registry pins, healthcheck и настоящий периодический
  healthchecks-пинг. Пул `ms1-15.example.net`, credentials только программно из
  существующего источника; все профили проверить, секреты не выводить.
  Прогон всех valid=true целей через развёрнутый API, числа в research,
  README с примерами. Заметки `cache/service-monitoring-notes.md` основаны
  на прочитанном skill healthchecks-monitoring. Предложен versioned RO release
  на одинаковом абсолютном пути host/API, как в live M9, без изменения probe-bind.
  DNS, публичный443/WAF и чужие сервисы — за владельцем; свой CF-стенд после
  работающего основного пути. MCP добавлять только при пользе сверх CLI.

  **Последние известные квоты для будущего продолжения:** Spark исчерпан
  до20.09.2026 15:59 (timezone неизвестен). Это не разрешение запускать сейчас.
  При прежнем остатке Spark и auto не запускать. Последний факт:
  владелец подтвердил reset weekly Grok15.09, обычный mutation-запуск работает.
  Точные остатки weekly/5h неизвестны. Прежний quota error00:21UTC сохранён
  как история. Обычный cx — окна неизвестны, ради статуса не вызывался.
  Получена заметка Claude о4% из `gk-abg-m10-probes-20260914`: источник —
  прежняя подготовка M10, эта панель уже закрыта. Время самого наблюдения4%
  не указано. Эта старая заметка не была подтверждением reset; новое явное
  подтверждение владельца15.09 позволило состоявшийся запуск Grok.
  Финишная директива запрещает новые запуски независимо от квоты.
  Для новой реализации действует текущий AGENTS: auto Grok/Spark только при
  доступности обоих, при исчерпании одного — явный другой; обычный cx вне
  random pool. Возврат M12a остаётся Grok. M10 уже принята, её не повторять.
  M11 принята владельцем, влита; технический journal/gate-блокер закрыт
  решением15.09, оснастку не менять. Разведка и подготовка probe M12a
  приняты; дальнейшие запуски остановлены финишной директивой владельца.
  Проект ещё НЕ готов к использованию: M9–M11 приняты, развёрнутый сервис
  и итоговый deployed-прогон остаются в M12.

## Остальной бэклог

- [ ] **Инструменты из рилса `DdJ-MY6OITt` — что ещё взять в проект.** Рилс
  (`zhilnikov_it`, 11.09.2026) целиком про Scrapling: «выглядит как настоящий
  браузер», «чинит себя сам при смене вёрстки», «подключается к Claude Code и
  Codex». Первое замерено вехой M8 и встроено в продуктовую лестницу M10 после
  сравнительного замера двух egress. Остальное по `scrapling==0.4.15`:
  1. **Готово: Scrapling после patchright в M10.** Решение опирается на
     принятый сравнительный замер direct/ms1; код принят15.09.2026.
  2. **MCP-сервер `scrapling[ai]`** (`mcp>=2.0.0`) — сравнить с нашим
     `cf-fetch` для агентов; вероятнее, что шлюзу нужен свой MCP поверх
     лестницы, а не чужой поверх одного инструмента.
  3. **Адаптивные селекторы (`auto_save` / `adaptive=True`)** — слой извлечения
     данных, шлюз отдаёт страницу, а не поля. Для шлюза вне скоупа; оценить для
     проектов-потребителей (скраперы магазинов, мониторинги).
  4. Spiders / AutoThrottle / ротация прокси — краулинг-фреймворк, нам не нужен,
     записано, чтобы не разбирать повторно.
  5. **Разбор 18.09.2026 по второму указателю владельца на тот же репозиторий.**
     Мы уже на `0.4.15` — ровно на релизе, который рекламирует пост, так что
     обновлять нечего, а «улучшенный решатель Cloudflare» у нас уже работает.
     Из нового в 0.4.15: переиспользование вкладок нам ничего не даёт (адаптер
     и так держит `StealthySession`, а платим мы за холодный старт контейнера,
     а не браузера — это епархия M13); `SiteToMarkdownSpider` отпадает по
     пункту 4. Единственный живой кандидат — `Response.markdown()` из экстры
     `rag` как формат выдачи для потребителей; минус в том, что он был бы
     только у одного провайдера из лестницы, поэтому своя конверсия поверх
     общего HTML честнее. Решать не сейчас.

## DONE

Вехи M1–M8 и подготовка (06.09–14.09.2026) вынесены в
[docs/worklog-archive/2026-09.md](docs/worklog-archive/2026-09.md).
