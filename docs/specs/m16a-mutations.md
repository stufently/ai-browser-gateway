# M16a — независимые мутации тестов детектора

18.09.2026. Проверочная задача gk, не реализация. Правку и тесты писала
cx-панель; мутации гоняет противоположный исполнитель.

Клон /home/user/exec-clones/abg-m16a-mutations-20260918, ветка
m16a-mutations, origin push DISABLED. SOURCE_SHA `c90a395` (FINAL M16a,
полный SHA — `git rev-parse c90a395` в клоне).
Выход: /home/user/.cache/abg-coord-20260918/m16a-mutations/.

## Что мутировать

Продукт мутаций — изменения M16a в `bench/providers/docker/probe.py`,
функция `detect_challenge`: вычисление `decisive_body` и `body_enough`,
условие `captcha_confirmed`, порядок и состав четырёх `return` в конце
функции, сбор `body_names` из `_BODY_RULES` и `_SUPPORTING_BODY_RULES`,
`_decisive_title`, срабатывание `_CAPTCHA_ATTR`. Прочитать целиком
`docs/specs/m16a-captcha-false-positive.md` и `git diff e80a5ef c90a395`.

Суть правки: `captcha_confirmed` раньше принимал ЛЮБУЮ одну решающую
body-метку, теперь требует `body_enough` (title «just a moment» либо ≥2
решающих меток). Заголовок `cf-mitigated` и статусы 403/429 остаются
подтверждением.

Авторский набор — `tests.test_detect`. Команда (сначала green на SOURCE):

`docker run --rm --network none --user 1002:1002 -v "$PWD":/work:ro -w /work -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 python3 -m unittest -q tests.test_detect`

20–30 смысловых мутантов по одному изменению, каждый в отдельной копии дерева
под выходным каталогом. Обязательные оси: **порог улики** (`len(decisive_body)
>= 2` → `>= 1`, `>= 3`, `> 2`; убрать из `body_enough` ветку
`body_just_a_moment`; `or` → `and`); **условие captcha** (вернуть
`decisive_body` вместо `body_enough`; убрать по одному каждый дизъюнкт
`header_names`, `body_enough`, `status in (403, 429)`; `captcha_confirmed`
всегда True; всегда False; `status in (403, 429)` → `status == 403` →
`status >= 400`); **порядок возвратов** (поменять местами ветки `body_enough`
и `captcha_names and captcha_confirmed`; убрать раннюю ветку `header_verdict`;
`captcha` → `suspected` и наоборот в возвращаемом вердикте); **состав меток**
(`decisive_body` считать по `_SUPPORTING_BODY_RULES` вместо `_BODY_RULES`;
не добавлять `body_captcha` в возвращаемый кортеж; `body_names` без
supporting-веток; `_decisive_title` → весь текст для `body_just_a_moment`);
**регистр и границы** (сравнивать не по `lowered`, а по `text`; `_CAPTCHA_ATTR`
не искать вовсе; искать в `lowered` вместо `text`).

Отдельно проверить, **убивается ли откат правки**: мутант
`body_enough` → `decisive_body` в строке `captcha_confirmed` обязан падать
на авторском наборе; если он выживает — это дыра в тестах вехи, и она главная
находка прогона.

Для каждого: id, ось, diff, SHA256 исходника/мутанта/восстановления,
доказательство активации изменённой строки авторским набором, команда/cwd/rc,
лог, упавший тест и строка assertion. Syntax/import error — invalid. Нет вызова
— survivor «непокрыто». Equivalent — только с доказательством (для дизъюнктов,
недостижимых из-за более раннего `return`, это ожидаемый и важный результат:
пометить equivalent и объяснить, каким `return` перехвачено).
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
