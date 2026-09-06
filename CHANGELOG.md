# CHANGELOG

## 2026-09-06

### Добавлено
- **Воспроизводимый раннер (веха M2).** Всё, что раньше жило черновыми пробниками
  в scratchpad, стало кодом репозитория.
  - `bench/providers/registry.py` — неизменяемый реестр провайдеров и wire-формат
    Docker: `build_argv()` собирает запуск, `parse_output()` читает последнюю
    JSON-строку и падает на битой.
  - `bench/runner/matrix.py` — план прогона (провайдер × ячейка × режим) с
    уникальным `run_id`.
  - `bench/runner/execute.py` — исполнение через инъектируемый `Launcher`;
    `DockerLauncher` пишет `--cidfile` и добивает контейнер по таймауту;
    `--network host` только для ячеек своего стенда, чужие цели идут наружу.
  - `bench/runner/environment.py` — метаданные прогона; неизвестное остаётся
    `unknown`, а не выдумывается.
  - `bench/report/build.py` + `bench/cli.py` — сборка отчёта потоком из JSONL
    и командная строка `python3 -m bench run|report`.
  - Семь Dockerfile и общий `bench/providers/docker/probe.py`: один контракт
    вывода на все провайдеры, обход `page.frames`, режимы `cold`/`warm`.
  - `tests/` — 137 тестов, `tests/mutation_gate.py` на 32 мутации.

- **Ядро benchmark-харнесса (веха M1).** Только стандартная библиотека, ни одной
  сторонней зависимости.
  - `bench/models.py` — нормализованный `FetchResult`, таксономия отказов и
    `evaluate()`: единственное место с правилом успеха.
  - `bench/scenarios.py` — 12 сценариев стенда A с уникальными sentinel.
  - `bench/server/app.py` — детерминированное WSGI-приложение стенда, тестируемое
    без сокетов; `python3 -m bench.server` поднимает его вживую.
  - `bench/report/coverage.py` — incremental coverage, unique wins и правило
    отбора провайдера с настраиваемым порогом.
  - `bench/report/render.py` — Markdown-отчёт; строка «не измерено» не может
    превратиться в число.
  - `bench/runner/record.py` — схема прогона и JSONL с валидацией на обоих концах.
  - `tests/` — 75 тестов и `tests/mutation_gate.py` на 17 мутаций.
- **Материалы фазы 1:** `docs/BENCHMARK_PLAN.md`, `docs/research/01-candidates.md`,
  `docs/research/02-egress-and-managed-browser.md`,
  `docs/research/03-stand-b-results.md`, `bench/targets/targets.toml`.

### Исправлено
- **Адаптер pydoll не передавал chromium флаги песочницы**, и все 24 ячейки
  прогона падали `provider_error` через 60 с. Дебиановский `chromium` собран с
  setuid-песочницей, контейнер идёт под `--user 1002:1002` без `CAP_SYS_ADMIN` —
  браузер не стартует вовсе, а симптом не похож на права: ни сообщения, ни кода
  ошибки, только таймаут. С `--no-sandbox --disable-dev-shm-usage --disable-gpu
  --disable-dbus` старт занимает 1,4 с. Найдено на живом стенде: ни гейт, ни 31
  мутация, ни два независимых ревью дефект не увидели.
- `evaluate()` сверял sentinel **раньше** статуса, поэтому `403` со строкой
  ожидания в теле возвращал успех. Заглушка Cloudflare называет заблокированный
  хост, и на живой цели `bizprofile.net` провальный запрос действительно
  засчитывался успехом. Теперь отказ по `4xx`/`5xx` побеждает sentinel.
- `incremental()` проходил по `records` дважды и терял всё на генераторе
  (`total_cells=0` при живых успехах); вход материализуется один раз.
- Провайдер без единого успеха, не указанный в `order`, исчезал из отчёта молча —
  теперь `ValueError`.
- `render_markdown()` не пробрасывал порог отбора в `keep_decision()`.
- Разбор `Accept-Encoding` игнорировал вес: `gzip;q=0` читался как разрешение.

### Известные ограничения
- Замер боевых целей сделан с ОДНОГО egress (хостинговый ASN без репутации).
  Пока второго адреса нет, «инструмент не справился» и «адрес не пустили»
  неразличимы.
