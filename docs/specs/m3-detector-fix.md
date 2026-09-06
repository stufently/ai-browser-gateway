# Веха M3 — заход исправлений

| | |
|---|---|
| Клон | `/home/user/exec-clones/abg-m3-detector`, ветка `m3-detector` |
| Базовый коммит | `4c75e78` «Add challenge detector and next-step rule» |
| Исполнитель | **Grok** (тот же, кто писал веху) |
| Основание | ревью и перекрёстный мутационный прогон Codex + проверка постановщика на живой цели |

Заход **один**. Всё, что ниже, закрывается в нём; новых улучшений не добавлять.

## Что подтвердилось на живом стенде (это не претензия, а контекст)

Постановщик собрал образ `abg-curl` с твоим пробником и сходил одним запросом на
`https://bizprofile.net/`. Детектор отработал ровно как задумано:

```
status 403 | challenge suspected
markers ['header_cf_mitigated', 'body_cf_challenges_host', 'body_cf_chl_opt',
         'body_cf_chl', 'body_cf_challenge_platform', 'body_just_a_moment',
         'body_noindex_nofollow']
cf-mitigated: challenge | server: cloudflare
```

На `https://example.com/` — `200`, `challenge none`, девять заголовков собрано.
Сбор заголовков, приоритет заголовка над телом и вывод имён правил работают.

## Находка 1 (код) — одиночный маркер в ТЕКСТЕ страницы даёт ложный челлендж

Проверено постановщиком, воспроизводится:

```python
detect_challenge(200, {}, "<html><head><title>Offers — LowEndTalk</title></head>"
                          "<body><p>Wait just a moment before you order.</p></body></html>")
# ('suspected', ('body_just_a_moment',))
```

То же самое даст обычная страница, где просто упомянут
`challenges.cloudflare.com` или `cf_chl_opt`. Для нашего набора целей это не
теория: `lowendtalk.com` — форум хостеров, где обсуждение обхода Cloudflare с
цитатами кусков заглушки — рядовой пост.

Чем стреляет: страница, у которой контента нет по другой причине, получает
вердикт «челлендж», и `next_step()` уводит в `change_egress` вместо `browser` —
то есть тратит второй адрес там, где помог бы рендеринг. Это ровно та ошибка,
против которой веха и написана, только в другую сторону.

**Что сделать:**

- Правило `body_just_a_moment` срабатывает **только внутри `<title>`**, а не по
  всему телу. Основание: в настоящей заглушке эта строка стоит именно в титуле
  (`<title>Just a moment...</title>`), в теле её больше нигде нет. Функция
  `_title()` в пробнике уже есть.
- Остальные маркеры тела (`challenges.cloudflare.com`, `cf_chl_opt`, `__cf_chl`,
  `/cdn-cgi/challenge-platform`) дают вердикт `suspected` **только если сработало
  не меньше двух разных правил тела** (титульное правило считается наравне с
  ними). Основание: в настоящей заглушке срабатывают пять из пяти, так что запас
  четырёхкратный, а одиночное упоминание в прозе перестаёт быть приговором.
- Сработавшие имена правил возвращаются **всегда**, даже когда вердикт остался
  `none`: они нужны для диагностики, и «одно совпадение, вердикта нет» — это
  полезная запись, а не пустота.
- `header_cf_mitigated` по-прежнему решает **в одиночку**: он приходит от самого
  Cloudflare, подделать его содержимым чужой страницы нельзя.

## Находка 2 (код) — правило captcha срабатывает на обычной вёрстке

`_CAPTCHA_ATTR` ловит любой атрибут, содержащий слово `captcha`:
`id="captcha-history"`, `src="/img/captcha-example.png"` — обычная статья или
раздел справки получает вердикт `captcha`. Живого тела с капчей у нас **не
измерено ни одного**, то есть правило целиком построено на догадке.

**Что сделать:** оставить правило, но требовать подтверждения. Вердикт `captcha`
ставится, только если помимо captcha-атрибута есть **хотя бы один независимый
признак челленджа**: заголовок `cf-mitigated`, любое сработавшее правило тела,
либо статус `403`/`429`. Один только атрибут — вердикт `none`, имя правила
`body_captcha` при этом всё равно возвращается.

Комментарий над правилом обновить: сказать прямо, что живого тела с капчей у нас
нет, и что правило держится на подтверждении, а не на самом слове.

## Находка 3 (не дефект, но дыра) — строка `challenge_suspected` в `next_step()`

Codex посчитал за дефект, что `FailureReason.challenge_suspected` отображается в
`change_egress`, хотя в таблице спеки этой строки не было. **Отображение
правильное и остаётся** — обнаруженный челлендж и должен вести к смене адреса, в
браузер идти незачем. Дефект в другом: строка ничем не покрыта, и подмена её на
`browser` переживает весь сьют. Нужен тест.

## Дыры в тестах (перекрёстный прогон Codex, все проверены постановщиком)

Все шесть — **дыры в тестах, а не находки в коде**:

1. Удаление любого одного маркера тела (`challenges.cloudflare.com`, `cf_chl_opt`,
   `__cf_chl`, `/cdn-cgi/challenge-platform`) не роняет ни один из 166 тестов.
   Нужен тест на **каждое** правило отдельно.
2. Строка `challenge_suspected → change_egress` не покрыта (см. находку 3).
3. Строка `javascript_required` **с челленджем** (`→ change_egress`) не покрыта:
   покрыт только вариант без челленджа.
4. Правило `egress_changed` покрыто только для `content_missing`. Добавление
   `and reason is FailureReason.content_missing` переживает сьют — то есть
   повторный `403` после смены адреса вернёт `change_egress` вместо `human`.
5. Имена правил у вердикта `captcha` не проверяются: возврат `("captcha", ())`
   переживает сьют.
6. Поддерживающее правило `body_noindex_nofollow` не проверяется: его удаление
   переживает сьют.

Плюс тесты под новое поведение находок 1 и 2.

Мутации в `tests/mutation_gate.py` — **не меньше восьми новых** поверх 39
имеющихся, минимум по одной на: каждое из четырёх правил тела; порог «не меньше
двух правил»; ограничение `just a moment` титулом; требование подтверждения у
captcha; строку `challenge_suspected`; правило `egress_changed` для причины,
отличной от `content_missing`.

## Не трогать

- `bench/models.py`, `bench/scenarios.py`, `bench/server/`, `bench/report/`,
  `bench/runner/`, `bench/providers/registry.py`, семь `Dockerfile`,
  `tests/fixtures/` — как и в основной спеке.
- Контракт вывода пробника: ни одно поле не удаляется и не меняет смысла.
- Приоритет «заголовок → тело → статус» сохраняется, `cf-mitigated` остаётся
  одиночным решающим признаком.
- Никаких новых маркеров, которых нет в фикстурах. Находки 1 и 2 **сужают**
  правила, а не добавляют новые.
- `docs/specs/m3-challenge-detector.md` не править. Эта спека
  (`docs/specs/m3-detector-fix.md`) приезжает untracked и **коммитится вместе с
  работой**.

## Критерии приёмки

- **AC-311 — весь сьют зелёный.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -m unittest discover -s tests -t . -q'`

- **AC-312 — мутационный гейт: не меньше 47 мутаций, все убиты.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "import ast,sys; t=ast.parse(open(\"tests/mutation_gate.py\").read()); n=[len(x.value.elts) for x in ast.walk(t) if isinstance(x,ast.Assign) and getattr(x.targets[0],\"id\",\"\")==\"MUTANTS\"][0]; sys.exit(0 if n>=47 else 1)" && python3 tests/mutation_gate.py'`

- **AC-313 — одиночный маркер в прозе больше не челлендж, настоящая заглушка — по-прежнему челлендж.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
prose = \"<html><head><title>Offers</title></head><body><p>Wait just a moment before you order.</p></body></html>\"
assert probe.detect_challenge(200, {}, prose)[0] == \"none\", probe.detect_challenge(200, {}, prose)
one = \"<html><body><p>See challenges.cloudflare.com for details.</p></body></html>\"
assert probe.detect_challenge(200, {}, one)[0] == \"none\", probe.detect_challenge(200, {}, one)
titled = \"<html><head><title>Just a moment...</title></head><body><p>x</p></body></html>\"
assert probe.detect_challenge(200, {}, titled)[0] == \"suspected\", probe.detect_challenge(200, {}, titled)
real = pathlib.Path(\"tests/fixtures/cf_interstitial_200body_403.html\").read_text()
verdict, markers = probe.detect_challenge(403, {}, real)
assert verdict == \"suspected\", verdict
assert len(markers) >= 3, markers
assert probe.detect_challenge(200, {\"cf-mitigated\": \"challenge\"}, \"<html><body>ok</body></html>\")[0] == \"suspected\"
"'`

- **AC-314 — captcha требует подтверждения.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location(\"probe\", \"bench/providers/docker/probe.py\")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
lone = \"<html><body><img id=\\\"captcha-history\\\" src=\\\"/img/captcha-example.png\\\"></body></html>\"
verdict, markers = probe.detect_challenge(200, {}, lone)
assert verdict == \"none\", (verdict, markers)
assert \"body_captcha\" in markers, markers
verdict, markers = probe.detect_challenge(403, {}, lone)
assert verdict == \"captcha\", (verdict, markers)
assert \"body_captcha\" in markers, markers
"'`

- **AC-315 — непокрытые строки таблицы эскалации закрыты.** Он проходит уже
  сейчас: код верен, дыра именно в тестах. Стоит регрессионным замком, а
  покрытие обеспечивает AC-312 — тесты писать всё равно надо.
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && python3 -c "
from bench.models import ChallengeType, FailureReason
from bench.escalate import Step, next_step
call = lambda e, c, changed=False: next_step(e, c, egress_changed=changed)
assert call(FailureReason.challenge_suspected, ChallengeType.suspected) is Step.change_egress
assert call(FailureReason.javascript_required, ChallengeType.suspected) is Step.change_egress
assert call(FailureReason.javascript_required, ChallengeType.none) is Step.browser
assert call(FailureReason.http_403, ChallengeType.none, True) is Step.human
assert call(FailureReason.http_429, ChallengeType.suspected, True) is Step.human
assert call(FailureReason.timeout, ChallengeType.none, True) is Step.retry_later
"'`

- **AC-316 — контракты M1 и M2 по-прежнему не тронуты.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && git diff --quiet 53cf517..HEAD -- bench/models.py bench/scenarios.py bench/server bench/report bench/runner bench/providers/registry.py bench/providers/docker/Dockerfile.curl bench/providers/docker/Dockerfile.curl_cffi bench/providers/docker/Dockerfile.primp bench/providers/docker/Dockerfile.playwright bench/providers/docker/Dockerfile.patchright bench/providers/docker/Dockerfile.camoufox bench/providers/docker/Dockerfile.pydoll tests/fixtures && git diff --quiet 3f7489a..HEAD -- docs/specs/m3-challenge-detector.md'`
  (основная спека сверяется от `3f7489a`, а не от `53cf517`: между ними её
  правил постановщик, и общий базис здесь дал бы ложный отказ.)

- **AC-317 — дерево чистое, спека захода закоммичена.**
  `bash -c 'cd /home/user/exec-clones/abg-m3-detector && git ls-files --error-unmatch docs/specs/m3-detector-fix.md >/dev/null && test -z "$(git status --porcelain -- . ":(exclude)report.json" ":(exclude)report-blocked.md")"'`

## Контракт отчёта

`report.json` в корне клона, записей ровно семь — по одной на критерий, формат
прежний. 🚨 Строку `command` копируй из спеки **дословно**.

## Контракт на невыполнимое

Требование невыполнимо или противоречит уже принятому — **остановись и доложи**.
Обходить запрещено: `|| true`, `set +e`, ослабление проверки под тест, правка
файлов из «Не трогать». Новых маркеров челленджа не добавлять: этот заход только
сужает правила и закрывает дыры в тестах.
