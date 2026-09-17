# M12b — выкладка сервиса на stand-host и deployed-прогон

## Шапка и где работать

Репозиторий /home/user/github/ai-browser-gateway, 17.09.2026.
BASE_SHA `RELEASE_SHA` — main после слияния принятой M12a (+ M12a-tests).
Клон /home/user/exec-clones/abg-m12b-deploy-20260917, ветка m12b-deploy,
origin push DISABLED. Исполнитель — cx (директива владельца 17.09.2026:
«доделывай всё, используя кодекс»). План координатора, на котором стоит эта
спека: `docs/specs/m12b-deployment-plan.md` (прочитать целиком).

Это production-выкладка на ЭТОМ хосте в ТВОЙ каталог
`/home/user/services/ai-browser-gateway/`. Разрешено создавать и менять
только его содержимое (кроме `secrets/hc-ping`, см. ниже), свой Compose-проект
`ai-browser-gateway`, свой образ `abg-runtime:<первые 12 символов RELEASE_SHA>`,
`~/.config/abg/client-token` (ссылка на свой token) и файлы клона. Чужие
сервисы, compose-проекты, контейнеры, сети и `.env` не трогать и не читать.
Единственное исключение — `/home/user/services/3proxy/.env`: его читает
только `scripts/abg-provision` внутри Docker с RO-монтированием этого одного
файла (шаг 2); ты сам его не открываешь.
Push/merge в репозиторий запрещены: работу заберёт координатор.

## Задача

1. **Release.** `scripts/abg-release prepare --repo <клон> --sha RELEASE_SHA
   --root /home/user/services/ai-browser-gateway` хостовым python3, как это
   делает `tests/live_m12_service.py` (скрипту нужен host git; в slim-образе
   git нет). Образ собрать из
   `releases/RELEASE_SHA/deploy/Dockerfile`; записать image ID.
2. **Секреты** в `/home/user/services/ai-browser-gateway/secrets/` (каталог
   0700): `token` — 32 случайных байта hex, сгенерировать программно в Docker,
   0600, НИКОГДА не печатать; `proxies.toml` — `scripts/abg-provision --source
   /home/user/services/3proxy/.env --output …` в Docker с source-файлом,
   смонтированным RO (скрипт берёт только PROXY_LOGIN/PROXY_PASSWORD). Файл
   `.env` не source-ить, не cat-ить, не копировать. Существующие секреты не
   перезаписывать: если файл уже есть — использовать как есть.
   `secrets/hc-ping` (0600) создаёт КООРДИНАТОР до запуска; ты его только
   монтируешь, не читаешь и не пингуешь вручную.
   `~/.config/abg/client-token` — симлинк на `secrets/token` (CLI поддерживает).
3. **Compose.** Не-секретный `compose.env` в корне сервиса: ABG_RELEASE,
   ABG_TOKEN_FILE, ABG_PROFILES_FILE, ABG_PING_FILE, ABG_INSTANCE=stand-host,
   ABG_RUNTIME_IMAGE, ABG_DOCKER_GID (по stat сокета), ABG_HOST_PORT=8765,
   ABG_COMPOSE_PROJECT=ai-browser-gateway. ABG_PROVIDER_NETWORK НЕ задавать:
   по контракту он только для собственного стенда, провайдеры в production
   идут в сеть Docker по умолчанию. Запуск только так:
   `docker compose --env-file /home/user/services/ai-browser-gateway/compose.env -f /home/user/services/ai-browser-gateway/releases/RELEASE_SHA/deploy/compose.yaml -p ai-browser-gateway up -d`.
   ДО запуска проверить: порт 8765 свободен; Compose-проекта
   `ai-browser-gateway` нет (`docker compose ls -a`); нет контейнеров с label
   `abg.instance=stand-host` и контейнеров с именем на `ai-browser-gateway-`. Любое
   из этого занято ЧУЖИМ — blocker, ничего не пересоздавать. Если это твой
   проект `ai-browser-gateway` из того же `releases/RELEASE_SHA` (повторный
   прогон) — не пересоздавать, продолжить проверки.
4. **Runner** `tests/deployed_m12b.py` (новый файл, stdlib, Docker-only для
   сетевых проверок, как `tests/live_m12_service.py`). Режимы — ровно команды
   AC ниже. Логика классификации и редакции вынесена в функции и покрыта
   `tests/test_deployed_m12b.py` с фейковыми Docker/HTTP (без сети и секретов):
   внутренняя ошибка vs внешний исход, редакция userinfo/token/ping, разбор
   attempts, предсказание ротации. Эти unit-тесты зелёные и закоммичены ДО
   любых production-действий (release, секреты, up, внешние запросы); после
   сдачи их мутирует независимая панель. Пишет JSON-улики в
   `/home/user/.cache/abg-coord-20260917/m12b/` (0700), без URL прокси,
   userinfo, token, ping URL. Внутренние ошибки проверки (Docker недоступен,
   нет ответа API) отличает от внешних исходов цели: первые → rc≠0, вторые —
   записанный честный исход.
   Порядок ротации: каждый валидный `POST /v1/fetch` сдвигает стартовый
   профиль на один (health и невалидные запросы — нет). Пока идут AC-604/605,
   других клиентов у сервиса нет.
5. **Документы.** `docs/research/07-deployed-service.md`: версии, image ID,
   release SHA, таблица 15 профилей (имя/HTTP/egress IP/класс отказа), direct
   IP, no-auth 407, матрица 6 целей (provider/profile/status/challenge/elapsed,
   ok или честный отказ), без секретов. README — раздел «M12b deployed
   service»: запуск/остановка/откат на другой `releases/<sha>`, где секреты,
   клиентский `abg-fetch`.

## Что проверено вживую, а что предположение

Проверено координатором 17.09.2026: каталога
`/home/user/services/ai-browser-gateway` нет; порт 8765 свободен; gid
docker.sock 983; `/home/user/services/3proxy/.env` существует, ключи
PROXY_LOGIN/PROXY_PASSWORD (значения не читались); Docker 29.8.0, Compose
v5.5.1. Прокси `ms1..ms15.example.net:8126`, echo — `http://api.ipify.org`
(использовался в разведке 15.09; direct `192.0.2.10`, ms1
`198.51.100.21`). Цели — `bench/targets/targets.toml`, `valid` не false: 6.
Проверено по коду `gateway/product.py`: при direct 200 без `expected_text`
причина `content_missing` ведёт к первому egress-профилю. Предположение: все 15
прокси сейчас живы и отдают разные egress IP.

## Разрешения

Всё из «Задачи»; реальные внешние запросы: echo через каждый профиль и direct,
6 целей из targets.toml и `http://api.ipify.org` для AC-604; между ЗАПРОСАМИ
runner к одному hostname ≥30 с (ступени лестницы внутри одного POST — policy
продукта, их не разносить). Docker build/run/compose своего проекта. Commit в клоне.

## Не трогать

gateway/**, bench/**, scripts/**, deploy/**, существующие tests и frozen
probes, контракт, другие specs, TASKS.md, CHANGELOG.md; чужие сервисы и их
файлы; `~/.config/healthchecks.env` и API healthchecks; cf-fetch. Не менять
policy/expected_text/budget, не ретраить цель ради зелёного исхода.
Сначала закоммитить эту спеку byte-identical (`docs/specs/m12b-deploy.md`).

## Критерии приёмки

- **AC-601.** Unit без регрессий:
  `bash -c 'docker run --rm --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest discover -q -s tests -t .'`
- **AC-602.** Сервис развёрнут как в контракте (release, образ, user, RO,
  loopback, mounts, restart, healthy, monitor без socket/token, права
  секретов, отсутствие token/ping URL в argv/env/logs; monitor работает ≥130 с
  и в его логах нет ошибок доставки ping):
  `bash -c 'python3 tests/deployed_m12b.py --check-deploy'`
- **AC-603.** Все 15 профилей измерены и классифицированы: egress IP через
  echo, direct-контроль, 407 без auth. Недоступный профиль или IP, равный
  direct/чужому профилю, — записанная находка (класс отказа), не падение.
  rc≠0 — ошибка оснастки/Docker, direct не измерен, нет 407 без auth, или
  меньше трёх рабочих профилей с попарно разными IP ≠ direct (их требует
  AC-604):
  `bash -c 'python3 tests/deployed_m12b.py --check-profiles'`
- **AC-604.** API реально уходит в egress и меняет профиль между запросами.
  Цель `http://api.ipify.org`, `allow_browser=false`, `expected_text` = egress
  IP профиля из улик AC-603, отличный от direct: direct даёт `content_missing`,
  продукт переходит к первому профилю ротации. Запрос 1 фиксирует профиль P
  (успех не обязателен). Запросы 2 и 3 с `expected_text` = IP профилей P+1 и
  P+2 (порядок ms1..ms15 по кругу) обязаны дать `ok:true`, `egress_profile`
  ровно P+1 и P+2 и content с этим IP. P+1 и P+2 — следующие
  РАБОЧИЕ профили из AC-603 с уникальными IP; если на пути ротации нерабочий
  профиль, runner делает промежуточный запрос и записывает его исход, а не
  пропускает сдвиг:
  `bash -c 'python3 tests/deployed_m12b.py --check-api-egress'`
- **AC-605.** Шесть целей через deployed API, полная матрица исходов из JSON
  API (attempts); rc≠0 только при ошибке сервиса/оснастки (не 200, нет JSON,
  соединение), внешний отказ цели — записанный исход. Плюс
  CLI scripts/abg-fetch на https://example.com/ (режим text) с client-token: rc=0 и
  «Example Domain» — проверка CLI на deployed-сервисе:
  `bash -c 'python3 tests/deployed_m12b.py --run-targets'`
- **AC-606.** Документы есть, без userinfo-URL:
  `bash -c 'test -s docs/research/07-deployed-service.md && grep -q "M12b deployed service" README.md && ! git grep -nE "://[^/[:space:]]+:[^/[:space:]]+@" -- docs/research README.md'`
- **AC-607.** Вне разрешённых путей ничего не изменено:
  `bash -c 'git diff --exit-code RELEASE_SHA HEAD -- . ":(exclude)tests/deployed_m12b.py" ":(exclude)tests/test_deployed_m12b.py" ":(exclude)docs/research/07-deployed-service.md" ":(exclude)README.md" ":(exclude)docs/specs/m12b-deploy.md"'`
- **AC-608.** Чистое дерево:
  `bash -c 'git ls-files --error-unmatch tests/deployed_m12b.py tests/test_deployed_m12b.py docs/specs/m12b-deploy.md docs/research/07-deployed-service.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Что проверяет координатор при приёмке (не AC исполнителя)

Через API healthchecks (исполнителю доступ запрещён): у чека
`ai-browser-gateway-health` не меньше двух success-пингов с интервалом ≈60 с
без ручного ping; при `docker stop` api приходит fail, после старта — снова
success. Исполнитель ping вручную не делает и `/fail` не шлёт.

## Авторевью

Политика cross-review-v1. Исполнитель Codex, ревьюеры **agy + grok**. После
commit REVIEW_SHA параллельно:
`bash /home/user/.claude/skills/executor-milestone/scripts/review_run.sh initial agy --clone <клон> --base RELEASE_SHA --range RELEASE_SHA..<REVIEW_SHA> --context "<эта спека и план m12b; только чтение>"`
и тот же wrapper `initial grok`. Разобрать ВСЕ finding_id: fixed с
proof/commit, disproved с proof, иначе needs_owner. Один FIX_ONCE, затем verify
теми же на REVIEW..FINAL. Неполный ответ/таймаут — не принятие; один
технический повтор; quota error — без повторов.

## Контракт отчёта

report.json v2 в корне клона, untracked, ровно 8 записей AC-601…AC-608,
command посимвольно из спеки; blocked — rc=null и безопасный текст ошибки.
```json
{"schema_version":2,"policy_id":"cross-review-v1","spec_sha256":"<SHA этой спеки>",
 "base_sha":"RELEASE_SHA","reviewed_sha":"<REVIEW_SHA>","final_sha":"<FINAL_SHA>",
 "executor":{"backend":"codex","model":"<фактическая модель>"},
 "review":{"initial_receipts":[],"verification_receipts":[],"resolutions":[]},
 "handoff_status":"ready","criteria":[{"id":"AC-601","status":"pass|fail|blocked",
 "command":"<из спеки>","rc":0,"note":"<улика>"}]}
```
Перед сдачей автор сам гоняет
`python3 /home/user/.claude/skills/executor-milestone/scripts/accept_run.py /home/user/exec-clones/abg-m12b-deploy-20260917 --spec /home/user/exec-clones/abg-m12b-deploy-20260917/docs/specs/m12b-deploy.md --timeout 3600`.
Сервис после сдачи ОСТАЁТСЯ запущенным.

## Контракт на невыполнимое

Остановиться с одним списком blocker и уликами в `report-blocked.md`, если:
порт 8765 или каталог сервиса заняты чужим; `secrets/hc-ping` отсутствует;
рабочих профилей с разными IP меньше трёх (записать, не обходить); для выкладки нужна правка gateway/scripts/deploy; нужен секрет,
который нельзя получить программно. Спеку, AC, BASE и оснастку не менять,
rc не выдумывать, чужое не трогать.
