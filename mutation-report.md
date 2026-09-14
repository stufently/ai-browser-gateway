# Независимый перекрёстный мутационный прогон M8

Исполнитель: Codex. Последний коммит проверяемых исходников и тестов: `a831dd5e9d01e7c7067d4048d6e145c44616e4b6`.
BASE_SHA из задания: `1337140b51482eb9b6d65cc60a406e533b627e4d`; мутации наложены на текущую M8, включая исправления warm blank/retries, без checkout BASE_SHA.

Мутаций: 18; доказанно убиты: 6; не убиты: 12.
Команда: `python3 tests/cross_mutation_m8.py`. Код возврата: `1`. AC-002: **fail**.

## Методика

Авторский список мутаций не изучался; авторская обвязка не импортировалась и не запускалась. Набор составлен по решениям start/navigate/close и регистрации провайдера. Существующие тесты не дополнены и не изменены.
Для каждой строки: сохранены байты и SHA-256, целевой тест выполнен на исходнике, проверено ровно одно вхождение, замена проверена чтением с диска, выполнен ровно тот же тест в отдельном процессе, исходник восстановлен в finally и хеш сверен. Каждый процесс использует новый pycache_prefix и -B, поэтому старый pyc не скрывает мутацию.
Убийство засчитывается только при зелёном baseline, rc=1 после мутации и unittest failure в заранее заданных методе/файле/строке ассерта. Ошибки загрузки, сборки, setup, пропуски и падения на другом ассерте не засчитываются. Если собственного ассерта на решение нет, выбран ближайший существующий тест, а место убийства задано как null.
В колонке «набор упал» набор означает ровно один указанный целевой тест, не весь репозиторий. Полные модули проверяются отдельно на восстановленном исходнике. Вывод о пробелах опирается также на чтение всех ScraplingAdapterTests и RegistryTests; прогон ближайшего теста не объявляется прогоном всей матрицы тестов под мутантом.

## Результаты

| Мутация | Легла | Набор упал | Кто поймал |
| --- | --- | --- | --- |
| M01: убрать ранний about:blank | да, 1 вхождение | да | `tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch` — `tests/test_probe.py:813` |
| M02: не вызывать callable body | да, 1 вхождение | нет | никто; не убит |
| M03: пропустить коэрцию не-bytes | да, 1 вхождение | нет | никто; не убит |
| M04: кодировать None как строку | да, 1 вхождение | нет | никто; не убит |
| M05: обнулить число редиректов | да, 1 вхождение | нет | никто; не убит |
| M06: убрать fallback history=None | да, 1 вхождение | нет | никто; не убит |
| M07: терять status ответа | да, 1 вхождение | нет | никто; не убит |
| M08: убрать fallback пустого final URL | да, 1 вхождение | нет | никто; не убит |
| M09: инвертировать solve_cloudflare в fetch | да, 1 вхождение | да | `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver` — `tests/test_probe.py:771` |
| M10: убрать scrapling из probe.PROVIDERS | да, 1 вхождение | нет | никто; не убит |
| M11: убрать scrapling из make_adapter | да, 1 вхождение | да | `tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling` — `tests/test_probe.py:907` |
| M12: убрать scrapling из registry.PROVIDERS | да, 1 вхождение | да | `tests.test_registry.RegistryTests.test_registry_contract` — `tests/test_registry.py:10` |
| M13: отключить real_chrome | да, 1 вхождение | нет | никто; не убит |
| M14: включить google_search | да, 1 вхождение | нет | никто; не убит |
| M15: сократить timeout до 1 | да, 1 вхождение | нет | никто; не убит |
| M16: увеличить retries до 2 | да, 1 вхождение | да | `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver` — `tests/test_probe.py:773` |
| M17: не закрывать сессию | да, 1 вхождение | да | `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver` — `tests/test_probe.py:775` |
| M18: не входить в контекст сессии | да, 1 вхождение | нет | никто; не убит |

## Разбор каждого неубитого мутанта

### M02: не вызывать callable body

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Во всех успешных Page body уже bytes, ветка callable не выполняется. Нужен test_scrapling_calls_body: body — метод со счётчиком, возвращающий UTF-8 bytes; проверить один вызов, result["body"] и result["bytes"]. Без вызова адаптер кодирует строковое представление метода вместо HTML.

### M03: пропустить коэрцию не-bytes

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Нет Page с текстовым body. Нужен test_scrapling_encodes_text_body: body="Привет", перехватить исключение в error и проверить assertIsNone(error), затем result["body"] == "Привет" и bytes == 12. Мутант передаст str в _result, где вызов decode вызовет AttributeError; падение должно быть на собственном ассерте об отсутствии ошибки.

### M04: кодировать None как строку

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Нет body=None. Нужен test_scrapling_none_body_is_empty: проверить result["body"] == "" и result["bytes"] == 0. Мутант даёт "None" и 4 байта.

### M05: обнулить число редиректов

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

В каждой Page history=(), assertions на redirects отсутствуют. Нужен test_scrapling_counts_redirects с двумя элементами history и assertEqual(result["redirects"], 2); мутант возвращает 0.

### M06: убрать fallback history=None

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Нужен test_scrapling_missing_history_is_empty с history=None и отсутствующим атрибутом history: перехватить исключение и проверить assertIsNone(error), затем в обоих случаях redirects == 0. Нынешние фикстуры всегда содержат (); мутант на новых входах вызывает len(None).

### M07: терять status ответа

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch`.

Тест warm проверяет ok и sentinel, но run_probe считает status=None допустимым. Нужен test_scrapling_preserves_status: ответы 201 и 403, точное сравнение result["status"]; отдельно run_probe с marker и 403 должен дать ok=False. Мутант теряет HTTP-статус и может превратить HTTP-ошибку в успех.

### M08: убрать fallback пустого final URL

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

У всех Page url непустой. Нужен test_scrapling_empty_url_uses_request_url с url=None и url="": final_url должен совпадать с URL запроса. Мутант возвращает соответственно "None" и "".

### M10: убрать scrapling из probe.PROVIDERS

Целевой тест: `tests.test_registry.RegistryTests.test_registry_contract`.

test_registry_contract проверяет bench.providers.registry.PROVIDERS, а не множество в probe.py. Нужен test_probe_provider_names_match_registry с assertIn("scrapling", probe.PROVIDERS) и сверкой имён обоих реестров. Удаление наблюдаемо через контракт множества, поэтому это не эквивалентный мутант для требуемого наличия имени. Однако обычный CLI ведёт себя одинаково: обе ветки main вызывают run_probe с тем же make_adapter (явно или по умолчанию). Один лишь успешный CLI-запуск не доказывает наличие имени в множестве.

### M13: отключить real_chrome

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Session сохраняет init kwargs, но real_chrome не проверяется. Нужен test_scrapling_session_browser_options с assertIs(init["real_chrome"], True). Мутант меняет переданную браузерную опцию на False; это наблюдаемая разница аргументов.

### M14: включить google_search

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Нет проверки init["google_search"]. Нужен test_scrapling_disables_google_search с assertIs(init["google_search"], False); мутант передаёт True. Фикстура принимает любые kwargs, поэтому существующий тест остаётся зелёным.

### M15: сократить timeout до 1

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Нужен test_scrapling_session_timeout с assertEqual(init["timeout"], 120_000). Мутант передаёт 1 вместо 120000; ни одна текущая проверка kwargs этого не замечает.

### M18: не входить в контекст сессии

Целевой тест: `tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver`.

Фиктивный __enter__ только возвращает self, fetch не требует инициализации. Нужен test_scrapling_enters_session_before_fetch со счётчиком __enter__ и проверкой порядка enter → fetch → exit. Мутант пропускает наблюдаемый вызов жизненного цикла, хотя текущая фикстура продолжает работать.

## Целостность

Все существующие файлы bench/providers/**, tests/test_probe.py, tests/test_registry.py и tests/mutation_gate_scrapling.py сравниваются побайтово до и после полного прогона. SHA-256 приведены ниже. Проверка чистоты Git выполняется после локального коммита; report.json игнорируется Git.

```json
{
  "bench/providers/__init__.py": "5cb11fef98a25326d6cd7cf992bcb20389f910d537a1c57c39378f0172d2a45a",
  "bench/providers/docker/Dockerfile.camoufox": "8d78a4140131836774bdccb6950c9763d2c0c9959f53f6dd04196708c64fbd19",
  "bench/providers/docker/Dockerfile.curl": "ed5d9fba89f232e545d89583f0af56580c0607f2fb89976a624fd75462b2d473",
  "bench/providers/docker/Dockerfile.curl_cffi": "e9375e806931876aa46a0031b84a92b038e79493aa02cf870ea092f0a655d2ca",
  "bench/providers/docker/Dockerfile.patchright": "4c44acd9d07d327298e336565404b6b28ce5c3cba87bd3cfdcf64fd21d8b2a35",
  "bench/providers/docker/Dockerfile.playwright": "349dcc34599e0577aa1f900c831bcd86e976b7aac7b93b6334f6366c10892af4",
  "bench/providers/docker/Dockerfile.primp": "ac7df9645737b049ac55e08c3d0c922c349e3a596e7e1660bb87cb78fe51848c",
  "bench/providers/docker/Dockerfile.pydoll": "f3124d3e00a90a7d498bbfcad836a9bb7d5a2d110b5e16881dd20ed705cb106d",
  "bench/providers/docker/Dockerfile.rss": "fa80eb1ba22c63927a024743fd3bb7230bf9eb342343a6b9534ac2f41eab2576",
  "bench/providers/docker/Dockerfile.scrapling": "d139842c8bf0d9a5c01eb7783faed28b767ecaabfab0472ca6e2a14f939b6bb5",
  "bench/providers/docker/Dockerfile.wayback": "5076d91e5e57ec93293b532ec0e187ae0005d2d3309a6aae79584652b81fb626",
  "bench/providers/docker/probe.py": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
  "bench/providers/registry.py": "7759a6d21b68dbf09a6f6235e51b22e459295efeb295e89ff0685358b735bbde",
  "tests/test_probe.py": "f5942274a08f8db53c7f6e6689c765450a5263520f84937954c6b58cbca29620",
  "tests/test_registry.py": "2ddc42f0e441c3e5b7e8e764bf42d3d9632f5ca63ffb279782a04738c02d3381",
  "tests/mutation_gate_scrapling.py": "179763fbc29ac0e287f25dd42ef755450883a5e778d24599c825811b89eff3b8"
}
```

## Машинные доказательства каждого прогона

Содержат baseline/mutant rc, число тестов, исходный и восстановленный хеши, предварительно назначенный ассерт и настоящий traceback. Абсолютные пути относятся к клону.

```json
[
  {
    "name": "M01: убрать ранний about:blank",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
      "line": 813,
      "function": "test_scrapling_warm_blank_does_not_call_fetch"
    },
    "sha256_mutated": "828bb268ee6efedf4e01ec065ecebfaa51334f06e9cbf00851b72e1149f30c9f",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "'about:blank' unexpectedly found in ['about:blank']",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
              "line": 813,
              "function": "test_scrapling_warm_blank_does_not_call_fetch"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 1199,
              "function": "assertNotIn"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 750,
              "function": "fail"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_probe.py\", line 813, in test_scrapling_warm_blank_does_not_call_fetch\n    self.assertNotIn(\"about:blank\", captured.get(\"urls\", []))\n    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 1199, in assertNotIn\n    self.fail(self._formatMessage(msg, standardMsg))\n    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 750, in fail\n    raise self.failureException(msg)\nAssertionError: 'about:blank' unexpectedly found in ['about:blank']\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M02: не вызывать callable body",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "94986861a37bc8dce7bfb9d044bfd46668dad26827cddc2a450c0a6847d65f6f",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M03: пропустить коэрцию не-bytes",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "d55e3118d16cbca28048385c5e0b9c13a9684fa91310823bb476b7a1a942061d",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M04: кодировать None как строку",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "fd97c864add4bc5e7833cd9c9397fde746e4f2e66da14654673e3c848d5261ef",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M05: обнулить число редиректов",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "5bf2c4150bdaafc4a0c32b55367868825003e67a20cb94c9f31820b9e2db7113",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M06: убрать fallback history=None",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "c37cdb51cd6f68df7e11ea9f03cc91b4015f66c3004f4d1858645e82441c7993",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M07: терять status ответа",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "cba509fb311f799fa21c96d1d339bb00bea2fc73655c92feb7dd26571bc410cf",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_warm_blank_does_not_call_fetch",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M08: убрать fallback пустого final URL",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "93cf6ea462b27e6a2d357237962b764492226daeee65dfb5a35aaf04a9be303e",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M09: инвертировать solve_cloudflare в fetch",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
      "line": 771,
      "function": "test_scrapling_requests_cloudflare_solver"
    },
    "sha256_mutated": "cd98efcdb9e046a3751b801d36202cff7c0a3bf1e6570e1e2a2320cdd02f9488",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "False is not True",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
              "line": 771,
              "function": "test_scrapling_requests_cloudflare_solver"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 1206,
              "function": "assertIs"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 750,
              "function": "fail"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_probe.py\", line 771, in test_scrapling_requests_cloudflare_solver\n    self.assertIs(captured[\"fetch\"][1][\"solve_cloudflare\"], True)\n    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 1206, in assertIs\n    self.fail(self._formatMessage(msg, standardMsg))\n    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 750, in fail\n    raise self.failureException(msg)\nAssertionError: False is not True\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M10: убрать scrapling из probe.PROVIDERS",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_registry.RegistryTests.test_registry_contract",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_registry.RegistryTests.test_registry_contract",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "fb04d41ab3e07c83c67960b5c4f0a7e3814a27c208de016e49cda27c00f6eb24",
    "mutant": {
      "target": "tests.test_registry.RegistryTests.test_registry_contract",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M11: убрать scrapling из make_adapter",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
      "line": 907,
      "function": "test_make_adapter_selects_scrapling"
    },
    "sha256_mutated": "f0eace6c0e7929ef4e37b18ff3c7487560c1299546a531909800e42b53601bf4",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_probe.ScraplingAdapterTests.test_make_adapter_selects_scrapling",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "None is not an instance of <class 'container_probe.ScraplingAdapter'>",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
              "line": 907,
              "function": "test_make_adapter_selects_scrapling"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 1337,
              "function": "assertIsInstance"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 750,
              "function": "fail"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_probe.py\", line 907, in test_make_adapter_selects_scrapling\n    self.assertIsInstance(adapter, self.probe.ScraplingAdapter)\n    ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 1337, in assertIsInstance\n    self.fail(self._formatMessage(msg, standardMsg))\n    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 750, in fail\n    raise self.failureException(msg)\nAssertionError: None is not an instance of <class 'container_probe.ScraplingAdapter'>\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M12: убрать scrapling из registry.PROVIDERS",
    "path": "bench/providers/registry.py",
    "target": "tests.test_registry.RegistryTests.test_registry_contract",
    "sha256_before": "7759a6d21b68dbf09a6f6235e51b22e459295efeb295e89ff0685358b735bbde",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_registry.RegistryTests.test_registry_contract",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_registry.py",
      "line": 10,
      "function": "test_registry_contract"
    },
    "sha256_mutated": "b6b5e2bbcd75cd32c25be06bbc9293c56091d1719fdaa9fe2b9928979b82602e",
    "mutant": {
      "target": "tests.test_registry.RegistryTests.test_registry_contract",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_registry.RegistryTests.test_registry_contract",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "Items in the second set but not the first:\n'scrapling'",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_registry.py",
              "line": 10,
              "function": "test_registry_contract"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 925,
              "function": "assertEqual"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 1185,
              "function": "assertSetEqual"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 750,
              "function": "fail"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_registry.py\", line 10, in test_registry_contract\n    self.assertEqual({p.name for p in PROVIDERS}, {\n    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n        'curl', 'curl_cffi', 'primp', 'playwright', 'patchright', 'camoufox',\n        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n        'pydoll', 'scrapling', 'wayback', 'rss'})\n        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 925, in assertEqual\n    assertion_func(first, second, msg=msg)\n    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 1185, in assertSetEqual\n    self.fail(self._formatMessage(msg, standardMsg))\n    ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 750, in fail\n    raise self.failureException(msg)\nAssertionError: Items in the second set but not the first:\n'scrapling'\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "7759a6d21b68dbf09a6f6235e51b22e459295efeb295e89ff0685358b735bbde"
  },
  {
    "name": "M13: отключить real_chrome",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "0ae6eac07881bc62879a70ef95b758b9c4de03569a4c1c0e9e2265b72a0fa3ad",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M14: включить google_search",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "4feb0b99f5e75cbe4547e9105f23b27a0436a1952c70fb53eba1de51da19ea0a",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M15: сократить timeout до 1",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "0b89ae688e72f55d3b34808b7ae0013d4ad4b3ed18f286cfbd7059411fd3039c",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M16: увеличить retries до 2",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
      "line": 773,
      "function": "test_scrapling_requests_cloudflare_solver"
    },
    "sha256_mutated": "41c095a84c90c29bad7a327baafbb47a30b08c7456c97231fcccf1c30f9c9800",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "2 != 1",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
              "line": 773,
              "function": "test_scrapling_requests_cloudflare_solver"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 925,
              "function": "assertEqual"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 918,
              "function": "_baseAssertEqual"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_probe.py\", line 773, in test_scrapling_requests_cloudflare_solver\n    self.assertEqual(captured[\"init\"][\"retries\"], 1)\n    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 925, in assertEqual\n    assertion_func(first, second, msg=msg)\n    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 918, in _baseAssertEqual\n    raise self.failureException(msg)\nAssertionError: 2 != 1\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M17: не закрывать сессию",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": true,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": {
      "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
      "line": 775,
      "function": "test_scrapling_requests_cloudflare_solver"
    },
    "sha256_mutated": "eff6a608378d9f13a02926adf73c79ecd5e1adb24a97fb126d1d8cf6280ed1f0",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [
        {
          "test": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
          "kind": "failure",
          "exception": "AssertionError",
          "message": "None is not true",
          "frames": [
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 58,
              "function": "testPartExecutor"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 669,
              "function": "run"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 615,
              "function": "_callTestMethod"
            },
            {
              "file": "/home/user/exec-clones/abg-m8-cross/tests/test_probe.py",
              "line": 775,
              "function": "test_scrapling_requests_cloudflare_solver"
            },
            {
              "file": "/usr/lib/python3.14/unittest/case.py",
              "line": 762,
              "function": "assertTrue"
            }
          ],
          "traceback": "Traceback (most recent call last):\n  File \"/usr/lib/python3.14/unittest/case.py\", line 58, in testPartExecutor\n    yield\n  File \"/usr/lib/python3.14/unittest/case.py\", line 669, in run\n    self._callTestMethod(testMethod)\n    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 615, in _callTestMethod\n    result = method()\n  File \"/home/user/exec-clones/abg-m8-cross/tests/test_probe.py\", line 775, in test_scrapling_requests_cloudflare_solver\n    self.assertTrue(captured.get(\"closed\"))\n    ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.14/unittest/case.py\", line 762, in assertTrue\n    raise self.failureException(msg)\nAssertionError: None is not true\n"
        }
      ],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": false,
      "rc": 1,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  },
  {
    "name": "M18: не входить в контекст сессии",
    "path": "bench/providers/docker/probe.py",
    "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
    "sha256_before": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a",
    "applied": true,
    "killed": false,
    "baseline": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "occurrences": 1,
    "assertion": null,
    "sha256_mutated": "368003ca50b21a5ad3faec784d895a88687248afed55e6d1c6b93ce59997ec32",
    "mutant": {
      "target": "tests.test_probe.ScraplingAdapterTests.test_scrapling_requests_cloudflare_solver",
      "tests_run": 1,
      "loader_errors": [],
      "events": [],
      "skipped": 0,
      "expected_failures": 0,
      "unexpected_successes": 0,
      "successful": true,
      "rc": 0,
      "stdout": "",
      "stderr": ""
    },
    "sha256_restored": "1bcf9604adcef7bcf88c740355eb07ccf27dcf6e9ce8a165d1789bad59a7812a"
  }
]
```
