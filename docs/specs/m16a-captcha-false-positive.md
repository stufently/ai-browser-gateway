# M16a — ложная метка captcha на настоящей странице за Cloudflare

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 18.09.2026.
BASE_SHA `a4b61f97d6fa895b827992dda9aed73a22693374` — main после принятой и выкаченной M15.
Клон /home/user/exec-clones/abg-m16a-captcha-20260918, ветка m16a-captcha,
origin push DISABLED. Исполнитель — cx (директива владельца 18.09.2026:
«доделывай все через кодекс»).

Сервис `ai-browser-gateway` (127.0.0.1:8765) и `/home/user/services/**` НЕ
трогать: выкладка — отдельная веха M16b. Push/merge запрещены. Тесты и
импорт — только Docker 1002:1002; host — git/файлы/оркестрация. Провайдерские
образы не пересобирать: раннер монтирует `probe.py` из релиза
(`bench/runner/fetch.py`, `PROBE_FILE`), поэтому правка детектора едет обычной
выкладкой. Live-запросы не нужны и запрещены.

## Задача

Детектор ставит `captcha` настоящей странице. Замер координатора 18.09.2026:
`lowendtalk.com/categories/offers` через `abg-curl_cffi:m2` отдаёт HTTP 200,
title «Offers — LowEndTalk», 222 365 байт настоящего форумного листинга, а
`detect_challenge` возвращает `captcha` по двум меткам:
`body_cf_challenge_platform` (Cloudflare сам дописывает
`/cdn-cgi/challenge-platform/scripts/jsd/main.js` в конец ОБЫЧНОЙ страницы) и
`body_captcha` (на странице подключён невидимый reCAPTCHA v3:
`<script src="https://www.google.com/recaptcha/api.js?render=…">`, слово
`recaptcha` попадает под правило `_CAPTCHA_ATTR`). Для продукта это стоит
лишней эскалации: без `expected_text` `accept_page` превращает `captcha` в
`interactive_challenge`, и лестница уходит в браузер там, где HTTP-ступень уже
принесла страницу.

В `bench/providers/docker/probe.py`, `detect_challenge`, ужесточить ровно одно
условие: `captcha_confirmed` должен требовать `body_enough` (то есть title
«just a moment» либо ДВЕ решающие body-метки) вместо любой одной решающей
метки. Заголовок `cf-mitigated` и статусы 403/429 как подтверждение остаются.
Ничего другого в детекторе не менять: набор правил `_BODY_RULES`,
`_SUPPORTING_BODY_RULES`, регулярку `_CAPTCHA_ATTR`, `RULE_PROVENANCE`
(`body_captcha` остаётся `assumed`), порядок вердиктов и состав возвращаемых
меток НЕ трогать. Метки `body_cf_challenge_platform` и `body_captcha`
по-прежнему называются в ответе — меняется только вердикт.

Фикстура. Скопировать байт-в-байт
`/home/user/.cache/abg-coord-20260918/lowendtalk_200_grecaptcha.html`
(SHA256 `26df951816a14b269ea64b551e7535fda7a57280ac06cd640b42152ffd7dc808`,
7939 байт) в `tests/fixtures/lowendtalk_200_grecaptcha.html` и добавить строку
в таблицу `tests/fixtures/README.md`: настоящая страница 200 с невидимым
reCAPTCHA и служебным скриптом Cloudflare, источник
`lowendtalk.com/categories/offers`, снято 18.09.2026, sitekey и параметры
`__CF$cv$params` затёрты координатором. Файл не редактировать.

Тесты `tests/test_detect.py`: тест
`test_captcha_plus_one_body_marker_is_captcha` описывает отменяемую политику —
заменить его тестом, что та же пара (одна решающая метка плюс captcha-атрибут
на 200) даёт `none` при обеих названных метках. Добавить тесты на новой
фикстуре: 200 → `none`, метки `body_cf_challenge_platform` и `body_captcha`
названы; тот же байт-в-байт текст фикстуры с 403 → `captcha`; тот же текст с
дописанной второй решающей меткой (например `cf_chl_opt`) → `suspected`.
Прежние тесты про 403, 429, одинокий атрибут и заглушку Cloudflare остаются
зелёными без правок. `tests/mutation_gate.py` править, только если мутант
перестал ложиться или его тест переименован; менять «old» ради прохода
запрещено.

Документ: в `docs/research/04-phase1-verdict.md` новый короткий раздел
«Ложная captcha на 200 (M16a)»: замер выше, правило до и после, что
`body_captcha` остаётся `assumed`, и что выигрыш на проде измеряется в M16b.

## Что проверено вживую, а что предположение

Проверено координатором 18.09.2026 запуском `abg-curl_cffi:m2` с текущим
`probe.py` (bind, `--content-only`): статус 200, вердикт `captcha`, метки
`('body_cf_challenge_platform', 'body_captcha')`; в теле нет ни
`challenges.cloudflare.com`, ни `cf_chl_opt`, ни `__cf_chl`, title не «just a
moment». На подготовленной фикстуре текущий код даёт тот же вердикт `captcha`,
а заглушка `cf_interstitial_200body_403.html` остаётся `suspected`.

Предположение: других целей матрицы правка не касается (в M15b bizprofile
давал `suspected`/403, остальные `none`); проверяется выкладкой M16b.

## Разрешения

Правка `bench/providers/docker/probe.py` (только строка `captcha_confirmed`),
`tests/test_detect.py`, `tests/fixtures/` (новый файл и README),
`tests/mutation_gate.py` по условию выше, раздел в
`docs/research/04-phase1-verdict.md`. Commit в клоне.

## Не трогать

Остальной `bench/**`, `gateway/**`, `scripts/**`, `deploy/**`,
`tests/probe_m9_transport.py`, `tests/probe_m10_product.py`,
`tests/probe_m11_api_cli.py`, `tests/probe_m12_service.py`,
`tests/probe_m12_service_regressions.py`, `tests/probe_m13_late_container.py`,
`tests/deployed_m12b.py`, `tests/test_deployed_m12b.py`, другие фикстуры,
другие specs, TASKS.md, CHANGELOG.md, `/home/user/services/**`, `secrets/**`.
Сначала закоммитить эту спеку byte-identical
(`docs/specs/m16a-captcha-false-positive.md`).

## Критерии приёмки

- **AC-107.** Unit и frozen probes зелёные:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t . && docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.probe_m9_transport tests.probe_m10_product tests.probe_m11_api_cli tests.probe_m12_service tests.probe_m12_service_regressions tests.probe_m13_late_container'`
- **AC-108.** Фикстура скопирована байт-в-байт и описана:
  `bash -c 'printf "%s  %s\n" 26df951816a14b269ea64b551e7535fda7a57280ac06cd640b42152ffd7dc808 tests/fixtures/lowendtalk_200_grecaptcha.html | sha256sum -c --quiet - && grep -q lowendtalk_200_grecaptcha.html tests/fixtures/README.md && git ls-files --error-unmatch tests/fixtures/lowendtalk_200_grecaptcha.html >/dev/null'`
- **AC-109.** Настоящая страница больше не captcha, метки названы:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); b=open(\"tests/fixtures/lowendtalk_200_grecaptcha.html\",encoding=\"utf-8\").read(); v,n=m.detect_challenge(200,{},b); assert v==\"none\", v; assert \"body_captcha\" in n and \"body_cf_challenge_platform\" in n, n"'`
- **AC-110.** Настоящие челленджи не ослаблены:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -c "import importlib.util,sys; s=importlib.util.spec_from_file_location(\"p\",\"bench/providers/docker/probe.py\"); m=importlib.util.module_from_spec(s); sys.modules[\"p\"]=m; s.loader.exec_module(m); b=open(\"tests/fixtures/lowendtalk_200_grecaptcha.html\",encoding=\"utf-8\").read(); i=open(\"tests/fixtures/cf_interstitial_200body_403.html\",encoding=\"utf-8\").read(); assert m.detect_challenge(403,{},b)[0]==\"captcha\"; assert m.detect_challenge(429,{},b)[0]==\"captcha\"; assert m.detect_challenge(403,{},i)[0]==\"suspected\"; assert m.detect_challenge(200,{\"cf-mitigated\":\"challenge\"},b)[0]==\"suspected\"; assert m.detect_challenge(200,{},b+\"<div class=cf_chl_opt></div>\")[0]==\"suspected\"; assert m.RULE_PROVENANCE[\"body_captcha\"]==\"assumed\""'`
- **AC-111.** Мутационные ворота проходят на своей команде:
  `bash -c 'docker run --rm --network none --user 1002:1002 -v "$PWD":/work -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 tests/mutation_gate.py'`
- **AC-112.** Детектор изменён одной строкой условия, правила и регулярка целы:
  `bash -c 'test "$(git diff a4b61f97d6fa895b827992dda9aed73a22693374 HEAD -- bench/providers/docker/probe.py | grep -c "^[-+][^-+]")" -le 6 && git diff --exit-code a4b61f97d6fa895b827992dda9aed73a22693374 HEAD -- bench ":(exclude)bench/providers/docker/probe.py" gateway scripts deploy && git grep -q "_CAPTCHA_ATTR = re.compile" -- bench/providers/docker/probe.py && git grep -q "\"body_captcha\": ASSUMED," -- bench/providers/docker/probe.py'`
- **AC-113.** Research дополнен:
  `bash -c 'grep -q "Ложная captcha на 200 (M16a)" docs/research/04-phase1-verdict.md && grep -q lowendtalk docs/research/04-phase1-verdict.md'`
- **AC-114.** Вне разрешённых путей ничего не изменено, дерево чистое:
  `bash -c 'git diff --exit-code a4b61f97d6fa895b827992dda9aed73a22693374 HEAD -- . ":(exclude)bench/providers/docker/probe.py" ":(exclude)tests/test_detect.py" ":(exclude)tests/mutation_gate.py" ":(exclude)tests/fixtures" ":(exclude)docs/research/04-phase1-verdict.md" ":(exclude)docs/specs/m16a-captcha-false-positive.md" && git ls-files --error-unmatch docs/specs/m16a-captcha-false-positive.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base a4b61f97d6fa895b827992dda9aed73a22693374 --range a4b61f97d6fa895b827992dda9aed73a22693374..<REVIEW_SHA> --context "<эта спека; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 8 записей AC-107…AC-114,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"a4b61f97d6fa895b827992dda9aed73a22693374","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-107","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m16a-captcha-20260918 --spec /home/user/exec-clones/abg-m16a-captcha-20260918/docs/specs/m16a-captcha-false-positive.md --timeout 1800`.

## Контракт на невыполнимое

Остановиться с blocker в `report-blocked.md`, если: правка условия ломает
frozen probe или тест, который спека оставляет зелёным (назвать тест и строку);
мутационные ворота требуют правки «old» существующего мутанта; фикстура не
даёт заявленного вердикта до правки. Спеку, AC, BASE и оснастку не менять,
rc не выдумывать, чужое не трогать.
