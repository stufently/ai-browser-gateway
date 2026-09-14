#!/usr/bin/env python3
"""Independent M8 audit of EXISTING tests; no Scrapling install or network needed.

Run: python3 tests/cross_mutation_m8.py
Exit 0 only if every mutation is killed at its predeclared assertion; 1 for
survivors/unproven kills, 2 for invalid baselines or audit infrastructure errors.
The generated mutation-report.md contains the complete evidence. Do not run
concurrently with another process editing the provider sources.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = "bench/providers/docker/probe.py"
REGISTRY = "bench/providers/registry.py"
SCRAPLING = "tests.test_probe.ScraplingAdapterTests."
SOLVER = SCRAPLING + "test_scrapling_requests_cloudflare_solver"
WARM = SCRAPLING + "test_scrapling_warm_blank_does_not_call_fetch"
REGISTRY_TEST = "tests.test_registry.RegistryTests.test_registry_contract"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    before: str
    after: str
    target: str
    assertion: str | None
    gap: str = ""


# Derived from the adapter's decisions and the unchanged tests, independently
# of tests/mutation_gate_scrapling.py. None means no dedicated assertion exists;
# an incidental failure must never be promoted to a kill for that decision.
MUTATIONS = [
    Mutation("M01: убрать ранний about:blank", PROBE,
             '        if url == "about:blank":\n            return _result(None, url, b"", 0, headers=None)\n',
             '', WARM,
             'self.assertNotIn("about:blank", captured.get("urls", []))'),
    Mutation("M02: не вызывать callable body", PROBE,
             '        if callable(body):\n            body = body()\n',
             '        if callable(body):\n            body = body\n', SOLVER, None,
             'Во всех успешных Page body уже bytes, ветка callable не выполняется. '
             'Нужен test_scrapling_calls_body: body — метод со счётчиком, возвращающий '
             'UTF-8 bytes; проверить один вызов, result["body"] и result["bytes"]. '
             'Без вызова адаптер кодирует строковое представление метода вместо HTML.'),
    Mutation("M03: пропустить коэрцию не-bytes", PROBE,
             '        if not isinstance(body, bytes):\n',
             '        if False:  # mutation: preserve non-bytes verbatim\n', SOLVER, None,
             'Нет Page с текстовым body. Нужен test_scrapling_encodes_text_body: '
             'body="Привет", перехватить исключение в error и проверить assertIsNone(error), '
             'затем result["body"] == "Привет" и bytes == 12. '
             'Мутант передаст str в _result, где вызов decode вызовет AttributeError; '
             'падение должно быть на собственном ассерте об отсутствии ошибки.'),
    Mutation("M04: кодировать None как строку", PROBE,
             '            body = b"" if body is None else str(body).encode("utf-8")\n',
             '            body = str(body).encode("utf-8")\n', SOLVER, None,
             'Нет body=None. Нужен test_scrapling_none_body_is_empty: проверить '
             'result["body"] == "" и result["bytes"] == 0. Мутант даёт "None" и 4 байта.'),
    Mutation("M05: обнулить число редиректов", PROBE,
             '        return _result(status, final_url, body, len(history), headers=headers)\n',
             '        return _result(status, final_url, body, 0, headers=headers)\n', SOLVER, None,
             'В каждой Page history=(), assertions на redirects отсутствуют. '
             'Нужен test_scrapling_counts_redirects с двумя элементами history '
             'и assertEqual(result["redirects"], 2); мутант возвращает 0.'),
    Mutation("M06: убрать fallback history=None", PROBE,
             '        history = getattr(response, "history", None) or ()\n',
             '        history = getattr(response, "history", None)\n', SOLVER, None,
             'Нужен test_scrapling_missing_history_is_empty с history=None и '
             'отсутствующим атрибутом history: перехватить исключение и проверить '
             'assertIsNone(error), затем в обоих случаях redirects == 0. '
             'Нынешние фикстуры всегда содержат (); мутант на новых входах вызывает len(None).'),
    Mutation("M07: терять status ответа", PROBE,
             '        status = getattr(response, "status", None)\n',
             '        status = None\n', WARM, None,
             'Тест warm проверяет ok и sentinel, но run_probe считает status=None допустимым. '
             'Нужен test_scrapling_preserves_status: ответы 201 и 403, точное сравнение '
             'result["status"]; отдельно run_probe с marker и 403 должен дать ok=False. '
             'Мутант теряет HTTP-статус и может превратить HTTP-ошибку в успех.'),
    Mutation("M08: убрать fallback пустого final URL", PROBE,
             '        final_url = str(getattr(response, "url", url) or url)\n',
             '        final_url = str(getattr(response, "url", url))\n', SOLVER, None,
             'У всех Page url непустой. Нужен test_scrapling_empty_url_uses_request_url '
             'с url=None и url="": final_url должен совпадать с URL запроса. '
             'Мутант возвращает соответственно "None" и "".'),
    Mutation("M09: инвертировать solve_cloudflare в fetch", PROBE,
             '        response = self.session.fetch(url, solve_cloudflare=self.solve_cloudflare)\n',
             '        response = self.session.fetch(url, solve_cloudflare=not self.solve_cloudflare)\n',
             SOLVER, 'self.assertIs(captured["fetch"][1]["solve_cloudflare"], True)'),
    Mutation("M10: убрать scrapling из probe.PROVIDERS", PROBE,
             '     "pydoll", "scrapling", "wayback", "rss"}\n',
             '     "pydoll", "wayback", "rss"}\n', REGISTRY_TEST, None,
             'test_registry_contract проверяет bench.providers.registry.PROVIDERS, '
             'а не множество в probe.py. Нужен test_probe_provider_names_match_registry '
             'с assertIn("scrapling", probe.PROVIDERS) и сверкой имён обоих реестров. '
             'Удаление наблюдаемо через контракт множества, поэтому это не эквивалентный '
             'мутант для требуемого наличия имени. Однако обычный CLI ведёт себя одинаково: '
             'обе ветки main вызывают run_probe с тем же make_adapter (явно или по умолчанию). '
             'Один лишь успешный CLI-запуск не доказывает наличие имени в множестве.'),
    Mutation("M11: убрать scrapling из make_adapter", PROBE,
             '        "scrapling": ScraplingAdapter,\n', '',
             SCRAPLING + "test_make_adapter_selects_scrapling",
             'self.assertIsInstance(adapter, self.probe.ScraplingAdapter)'),
    Mutation("M12: убрать scrapling из registry.PROVIDERS", REGISTRY,
             "    Provider('scrapling', 'abg-scrapling:m8', 2, 'browser', True),\n", '',
             REGISTRY_TEST, 'self.assertEqual({p.name for p in PROVIDERS}, {'),
    Mutation("M13: отключить real_chrome", PROBE,
             '            "real_chrome": True,\n',
             '            "real_chrome": False,\n', SOLVER, None,
             'Session сохраняет init kwargs, но real_chrome не проверяется. '
             'Нужен test_scrapling_session_browser_options с assertIs(init["real_chrome"], True). '
             'Мутант меняет переданную браузерную опцию на False; это наблюдаемая разница аргументов.'),
    Mutation("M14: включить google_search", PROBE,
             '            "google_search": False,\n',
             '            "google_search": True,\n', SOLVER, None,
             'Нет проверки init["google_search"]. Нужен test_scrapling_disables_google_search '
             'с assertIs(init["google_search"], False); мутант передаёт True. '
             'Фикстура принимает любые kwargs, поэтому существующий тест остаётся зелёным.'),
    Mutation("M15: сократить timeout до 1", PROBE,
             '            "timeout": 120_000,\n',
             '            "timeout": 1,\n', SOLVER, None,
             'Нужен test_scrapling_session_timeout с assertEqual(init["timeout"], 120_000). '
             'Мутант передаёт 1 вместо 120000; ни одна текущая проверка kwargs этого не замечает.'),
    Mutation("M16: увеличить retries до 2", PROBE,
             '            "retries": 1,\n', '            "retries": 2,\n',
             SOLVER, 'self.assertEqual(captured["init"]["retries"], 1)'),
    Mutation("M17: не закрывать сессию", PROBE,
             '            self.session.__exit__(None, None, None)\n',
             '            pass  # mutation: omit session exit\n',
             SOLVER, 'self.assertTrue(captured.get("closed"))'),
    Mutation("M18: не входить в контекст сессии", PROBE,
             '        self.session.__enter__()\n',
             '        pass  # mutation: omit session enter\n', SOLVER, None,
             'Фиктивный __enter__ только возвращает self, fetch не требует инициализации. '
             'Нужен test_scrapling_enters_session_before_fetch со счётчиком __enter__ '
             'и проверкой порядка enter → fetch → exit. Мутант пропускает наблюдаемый вызов '
             'жизненного цикла, хотя текущая фикстура продолжает работать.'),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceResult(unittest.TestResult):
    """Capture actual exception frames instead of matching unittest console text."""
    def __init__(self):
        super().__init__()
        self.events = []

    def record(self, test, err, kind):
        self.events.append({
            "test": test.id(), "kind": kind,
            "exception": err[0].__name__, "message": str(err[1]),
            "frames": [{"file": str(Path(f.filename).resolve()),
                        "line": f.lineno, "function": f.name}
                       for f in traceback.extract_tb(err[2])],
            "traceback": "".join(traceback.format_exception(*err)),
        })

    def addFailure(self, test, err):
        self.record(test, err, "failure")
        super().addFailure(test, err)

    def addError(self, test, err):
        self.record(test, err, "error")
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            kind = "failure" if issubclass(err[0], test.failureException) else "error"
            self.record(test, err, kind)
        super().addSubTest(test, subtest, err)


def run_child(target: str, evidence: Path) -> int:
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(target)
    result = EvidenceResult()
    suite.run(result)
    payload = {
        "target": target, "tests_run": result.testsRun,
        "loader_errors": loader.errors, "events": result.events,
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "successful": result.wasSuccessful(),
    }
    evidence.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


def run_target(target: str) -> dict:
    # -B alone still READS pre-existing bytecode. A fresh pycache prefix also
    # prevents same-size mutations within the same second using stale .pyc.
    with tempfile.TemporaryDirectory(prefix="m8-cross-") as box:
        evidence = Path(box) / "evidence.json"
        command = [sys.executable, "-B", "-X", f"pycache_prefix={box}/cache",
                   str(Path(__file__).resolve()), "--run-target", target, str(evidence)]
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True,
                                       env={**os.environ, "PYTHONHASHSEED": "0"},
                                       text=True, timeout=60)
        except subprocess.TimeoutExpired as exc:
            return {"rc": 124, "infrastructure_error": str(exc)}
        if not evidence.exists():
            return {"rc": completed.returncode, "infrastructure_error":
                    completed.stdout + completed.stderr or "missing child evidence"}
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload.update(rc=completed.returncode, stdout=completed.stdout,
                       stderr=completed.stderr)
        return payload


def valid_run(run: dict) -> bool:
    return (not run.get("infrastructure_error") and run.get("tests_run") == 1
            and not run.get("loader_errors") and not run.get("skipped")
            and not run.get("expected_failures") and not run.get("unexpected_successes"))


def green(run: dict) -> bool:
    return (valid_run(run) and run["rc"] == 0 and run["successful"]
            and not run["events"])


def assertion_location(mutation: Mutation) -> dict | None:
    if mutation.assertion is None:
        return None
    module, cls_name, method = mutation.target.rsplit(".", 2)
    path = ROOT / (module.replace(".", "/") + ".py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == cls_name)
    func = next(node for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name == method)
    matches = [i for i, line in enumerate(source.splitlines(), 1)
               if func.lineno <= i <= func.end_lineno
               and line.strip() == mutation.assertion]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one assertion in {mutation.target}: {matches}")
    return {"file": str(path), "line": matches[0], "function": method}


def own_assertion_kill(before: dict, after: dict, target: str, location: dict | None) -> bool:
    if not (green(before) and valid_run(after) and after["rc"] == 1
            and not after["successful"] and location and after["events"]):
        return False
    for event in after["events"]:
        if event["kind"] != "failure" or event["test"] != target:
            return False
        test_frames = [frame for frame in event["frames"]
                       if frame["file"] == location["file"]]
        if not test_frames or test_frames[-1] != location:
            return False
    return True


def audit_one(mutation: Mutation) -> dict:
    path = ROOT / mutation.path
    original = path.read_bytes()  # Step 1 precedes even the baseline run.
    digest = sha256(original)
    row = {"name": mutation.name, "path": mutation.path, "target": mutation.target,
           "sha256_before": digest, "applied": False, "killed": False}
    try:
        row["baseline"] = run_target(mutation.target)  # Step 2: unmutated source.
        if not green(row["baseline"]):
            raise RuntimeError("Target baseline is not a single green test")
        if path.read_bytes() != original:
            raise RuntimeError("Source changed during baseline")
        before, after = mutation.before.encode(), mutation.after.encode()
        row["occurrences"] = original.count(before)  # Step 3: exactly one match.
        if row["occurrences"] != 1 or before == after:
            raise ValueError("Mutation must change exactly one matching fragment")
        row["assertion"] = assertion_location(mutation)
        mutated = original.replace(before, after, 1)
        path.write_bytes(mutated)  # Step 4: apply, verify readback, run only target.
        row["sha256_mutated"] = sha256(path.read_bytes())
        if path.read_bytes() != mutated or row["sha256_mutated"] == digest:
            raise RuntimeError("Mutation readback failed")
        row["applied"] = True
        row["mutant"] = run_target(mutation.target)
    except Exception as exc:
        row["audit_error"] = f"{type(exc).__name__}: {exc}"
    finally:  # Step 5: unconditional byte restoration, including child failures.
        path.write_bytes(original)
        row["sha256_restored"] = sha256(path.read_bytes())
        if path.read_bytes() != original or row["sha256_restored"] != digest:
            raise RuntimeError(f"RESTORATION FAILED: {path}")
    if "mutant" in row:  # Step 6: classify only after verified restoration.
        row["killed"] = own_assertion_kill(
            row["baseline"], row["mutant"], mutation.target, row["assertion"])
        if not valid_run(row["mutant"]):
            row["audit_error"] = "Invalid mutant test run; cannot count as a kill"
    return row


def write_report(rows: list[dict], protected: dict[str, str], revision: str) -> None:
    killed = sum(row["killed"] for row in rows)
    lines = ["# Независимый перекрёстный мутационный прогон M8", "",
             f"Исполнитель: Codex. Последний коммит проверяемых исходников и тестов: `{revision}`.",
             "BASE_SHA из задания: `1337140b51482eb9b6d65cc60a406e533b627e4d`; "
             "мутации наложены на текущую M8, включая исправления warm blank/retries, без checkout BASE_SHA.",
             "", f"Мутаций: {len(rows)}; доказанно убиты: {killed}; не убиты: {len(rows) - killed}.",
             "Команда: `python3 tests/cross_mutation_m8.py`. Код возврата: "
             f"`{exit_code(rows)}`. AC-002: **{'pass' if exit_code(rows) == 0 else 'fail'}**.",
             "", "## Методика", "",
             "Авторский список мутаций не изучался; авторская обвязка не импортировалась и не запускалась. "
             "Набор составлен по решениям start/navigate/close и регистрации провайдера. "
             "Существующие тесты не дополнены и не изменены.",
             "Для каждой строки: сохранены байты и SHA-256, целевой тест выполнен на исходнике, "
             "проверено ровно одно вхождение, замена проверена чтением с диска, выполнен ровно "
             "тот же тест в отдельном процессе, исходник восстановлен в finally и хеш сверен. "
             "Каждый процесс использует новый pycache_prefix и -B, поэтому старый pyc не скрывает мутацию.",
             "Убийство засчитывается только при зелёном baseline, rc=1 после мутации и unittest failure "
             "в заранее заданных методе/файле/строке ассерта. Ошибки загрузки, сборки, setup, "
             "пропуски и падения на другом ассерте не засчитываются. Если собственного ассерта "
             "на решение нет, выбран ближайший существующий тест, а место убийства задано как null.",
             "В колонке «набор упал» набор означает ровно один указанный целевой тест, "
             "не весь репозиторий. Полные модули проверяются отдельно на восстановленном исходнике. "
             "Вывод о пробелах опирается также на чтение всех ScraplingAdapterTests и RegistryTests; "
             "прогон ближайшего теста не объявляется прогоном всей матрицы тестов под мутантом.",
             "", "## Результаты", "",
             "| Мутация | Легла | Набор упал | Кто поймал |",
             "| --- | --- | --- | --- |"]
    for row in rows:
        run = row.get("mutant", {})
        failed = "да" if run.get("rc", 0) else "нет"
        if "audit_error" in row:
            failed = "ошибка аудита"
        location = row.get("assertion")
        catcher = (f'`{row["target"]}` — '
                   f'`{Path(location["file"]).relative_to(ROOT)}:{location["line"]}`'
                   if row["killed"] else "никто; не убит")
        lines.append(f'| {row["name"]} | {"да, 1 вхождение" if row["applied"] else "нет"} '
                     f'| {failed} | {catcher} |')
    lines.extend(["", "## Разбор каждого неубитого мутанта", ""])
    for mutation, row in zip(MUTATIONS, rows):
        if row["killed"]:
            continue
        lines.extend([f"### {mutation.name}", "", f"Целевой тест: `{mutation.target}`.", "",
                      mutation.gap or "Ожидалось падение собственного ассерта; доказательство не получено.", ""])
        if "audit_error" in row:
            lines.extend([f'Ошибка аудита: {row["audit_error"]}', ""])
    lines.extend(["## Целостность", "",
                  "Все существующие файлы bench/providers/**, tests/test_probe.py, "
                  "tests/test_registry.py и tests/mutation_gate_scrapling.py сравниваются "
                  "побайтово до и после полного прогона. SHA-256 приведены ниже. "
                  "Проверка чистоты Git выполняется после локального коммита; report.json игнорируется Git.", "",
                  "```json", json.dumps(protected, indent=2, ensure_ascii=False), "```", "",
                  "## Машинные доказательства каждого прогона", "",
                  "Содержат baseline/mutant rc, число тестов, исходный и восстановленный хеши, "
                  "предварительно назначенный ассерт и настоящий traceback. Абсолютные пути относятся к клону.", "",
                  "```json", json.dumps(rows, indent=2, ensure_ascii=False), "```", ""])
    (ROOT / "mutation-report.md").write_text("\n".join(lines), encoding="utf-8")


def exit_code(rows: list[dict]) -> int:
    if any("audit_error" in row for row in rows):
        return 2
    return 0 if rows and all(row["killed"] for row in rows) else 1


def main() -> int:
    paths = sorted(path for path in (ROOT / "bench/providers").rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts)
    paths.extend(ROOT / name for name in (
        "tests/test_probe.py", "tests/test_registry.py", "tests/mutation_gate_scrapling.py"))
    protected = {path: path.read_bytes() for path in paths}
    # Audit-only commits must not change the generated evidence on a rerun.
    revision = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", "bench/providers",
         "tests/test_probe.py", "tests/test_registry.py", "tests/mutation_gate_scrapling.py"],
        cwd=ROOT, text=True).strip()
    rows = []
    try:
        for mutation in MUTATIONS:
            row = audit_one(mutation)
            rows.append(row)
            verdict = "KILLED" if row["killed"] else "SURVIVED"
            if "audit_error" in row:
                verdict = "AUDIT ERROR"
            print(f'{mutation.name}: {verdict}; applied={row["applied"]}; '
                  f'baseline={row["baseline"]["rc"]}; mutant={row.get("mutant", {}).get("rc")}',
                  flush=True)
    finally:
        changed = [str(path) for path, data in protected.items() if path.read_bytes() != data]
        if changed:
            raise RuntimeError(f"Protected files changed: {changed}")
    write_report(rows, {str(path.relative_to(ROOT)): sha256(data)
                        for path, data in protected.items()}, revision)
    print(f'{sum(row["killed"] for row in rows)}/{len(rows)} killed; '
          f'all protected bytes unchanged; report: mutation-report.md')
    return exit_code(rows)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--run-target":
        raise SystemExit(run_child(sys.argv[2], Path(sys.argv[3])))
    raise SystemExit(main())
