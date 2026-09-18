# M16a-fix2 — независимые мутации тестов детектора

18.09.2026. Проверочная задача gk, не реализация. Правку и тесты писала
cx-панель; мутации гоняет противоположный исполнитель.

Клон /home/user/exec-clones/abg-m16a-fix2-mutations-20260918, ветка
m16a-fix2-mutations, origin push DISABLED. SOURCE_SHA `6ff902fb7746929865c4e8e0db6599d81cbffe4a` (FINAL M16a-fix2,
полный SHA уже записан).
Выход: /home/user/.cache/abg-coord-20260918/m16a-fix2-mutations/.

## Что мутировать

Продукт мутаций — изменения M16a-fix в `bench/providers/docker/probe.py`,
функция `detect_challenge`: вложенный класс `InteractiveCaptcha` (разбор
`handle_starttag`, сбор `attrs`, разбор `class`, проверка `data-sitekey`,
разбор `src` у `script`, отсечение `#`, разбор query и условие `render=`),
множество `_CAPTCHA_WIDGET_CLASSES`, добавление метки
`body_captcha_interactive`, выражение `captcha_confirmed`, условие ветки
`captcha`. Прочитать целиком `docs/specs/m16a-fix-interactive-captcha.md`,
`docs/specs/m16a-fix2-widget-edges.md` и
`git diff 7cca18c 6ff902fb7746929865c4e8e0db6599d81cbffe4a`.

Суть правки: `captcha` теперь требует ИНТЕРАКТИВНОГО виджета (класс
`g-recaptcha`/`h-captcha`/`cf-turnstile`, атрибут `data-sitekey`, подключение
`recaptcha/api.js` БЕЗ `render=`). Невидимая reCAPTCHA v3 уликой не считается.
`captcha_confirmed` сведён к `decisive_body or status in (403, 429)`.

Авторский набор — `tests.test_detect`. Команда (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_detect`

⚠️ Гонять ИМЕННО так (`-m unittest -q tests.test_detect` — 52 теста), а НЕ
`python3 tests/test_detect.py`: в файле есть блок `if __name__ == "__main__"`
перед двумя классами, и прямой запуск молча выполняет только 45 тестов.

20–30 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: **набор классов виджета** (убрать по
одному из `_CAPTCHA_WIDGET_CLASSES`; сравнивать подстрокой вместо разбиения
`class` на слова; сравнивать с учётом регистра); **атрибут** (убрать проверку
`data-sitekey`; проверять значение вместо наличия); **разбор script** (снять
условие `render=`; считать интерактивным ЛЮБОЙ `recaptcha/api.js`; убрать
отсечение `#`; `path.endswith` → `path ==`; искать `render` без `=`;
`startswith("render=")` → `"render" in part`); **источник текста** (кормить
парсер `lowered` вместо `text`; вызывать `feed` на срезе первых N символов);
**метка и вердикт** (не добавлять `body_captcha_interactive`; добавлять всегда;
условие ветки `captcha` без требования метки; `captcha_confirmed` всегда True;
всегда False; `status in (403, 429)` → `status >= 400` → `status == 403`;
`decisive_body` → `body_names`); **порядок** (поменять местами ветку
`body_enough` и ветку `captcha`); **краевые случаи M16a-fix2** (считать `render=explicit`
невидимым; считать интерактивным ЛЮБОЕ значение `render=`; сравнивать
`explicit` без учёта регистра и наоборот; убрать `convert_charrefs=False`;
убрать `try/except` вокруг `feed`; ловить только `ValueError`; считать
`template` флагом вместо счётчика; не уменьшать счётчик на закрывающем теге;
не возвращаться из `handle_starttag` внутри шаблона).

Отдельно проверить пять откатов, каждый обязан падать на авторском наборе:
условие ветки `captcha` назад к `if captcha_names and captcha_confirmed:`;
`captcha_confirmed` назад к `header_names or body_enough or status in
(403, 429)`; условие `render=` назад к «любой `render=` — невидимый»; снятие
`try/except` вокруг `feed`; снятие учёта `<template>`. Выживший откат —
главная находка прогона.

Для каждого: id, ось, diff, SHA256 исходника/мутанта/восстановления,
доказательство активации изменённой строки авторским набором, команда/cwd/rc,
лог, упавший тест и строка assertion. Syntax/import error — invalid. Нет вызова
— survivor «непокрыто». Equivalent — только с доказательством.
Тест на отказ должен падать по причине мутации, а не по побочному эффекту.

## Выход и границы

`result.md` (таблица kill/survivor/invalid/equivalent, survivors с пояснением),
`mutations.json`, `commands.json`, `logs/`, `SHA256SUMS`. В конце —
восстановленный green, `git status` клона пуст, HEAD == SOURCE_SHA.

Ничего не коммитить. Не ходить в сеть (`--network none`), реальный Docker-сокет
в контейнеры не монтировать, провайдерские образы не запускать и не
пересобирать, не трогать `/home/user/services/**`, сервис, секреты,
`/home/user/.cache/abg-coord-20260918/*` кроме своего выхода. Не править
продукт, тесты, specs, TASKS/CHANGELOG. Без push, reviewers, других моделей,
новых панелей, sudo, host installs. Исполнение кода только в Docker 1002:1002;
host Python — файлы/git/оркестрация. report.json не требуется. На quota error —
сохранить доказательство и остановиться. После пакета остановиться с путём к
result.md.
