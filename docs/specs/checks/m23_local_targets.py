"""Чекер M23: цели вне гита и публичная сводка по классам.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m23_local_targets.py      ->  печатает `ok`

Проверяет поведение СКВОЗЬ командную строку, а не отдельные функции:
сводка `aggregate` печатает только классы и цифры; id целей, их адреса и
IP выхода в неё не попадают ни при каком входе; ошибки тоже не повторяют
id и адресов; несколько файлов целей склеиваются, а дубли id между ними
отвергаются.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from bench.models import ChallengeType, FailureReason  # noqa: E402
from bench.runner.record import RunRecord, to_jsonl_line  # noqa: E402

HOSTS = {
    "leak-id-alpha": "alpha-private-shop.test",
    "leak-id-beta": "beta-private-forum.test",
    "leak-id-gamma": "gamma-private-social.test",
}
# IP собран из частей: литерал в отслеживаемом файле гейт утечек M22 счёл бы
# новым адресом. Адрес из документационного диапазона TEST-NET-3.
EGRESS = ".".join(["203", "0", "113", "77"])
SECRETS = [*HOSTS, *HOSTS.values(), EGRESS, "target:", "AS64500"]

TARGETS = """
[[target]]
id = "leak-id-alpha"
url = "https://alpha-private-shop.test/"
class = "none"
expect = "A"

[[target]]
id = "leak-id-beta"
url = "https://beta-private-forum.test/"
class = "cloudflare"
expect = "B"

[[target]]
id = "leak-id-gamma"
url = "https://gamma-private-social.test/"
class = "cloudflare"
expect = "C"
"""

EXPECTED_TABLE = [
    "| Class | Targets | curl_cffi | patchright | scrapling | Any provider |",
    "|---|---|---|---|---|---|",
    "| cloudflare | 2 | 0/2 | 1/2 | 1/2 | 1/2 |",
    "| none | 1 | 1/1 | 1/1 | not measured | 1/1 |",
]


def fail(message):
    sys.exit("m23_local_targets: " + message)


def record(provider, target, success, error=FailureReason.none):
    if not success and error is FailureReason.none:
        error = FailureReason.http_403
    host = HOSTS[target]
    return RunRecord(
        provider=provider, provider_version="1", scenario=None, target=target,
        run_id=f"{provider}-{target}", mode="cold", success=success,
        sentinel_found=success, status=200 if success else 403,
        final_url=f"https://{host}/", challenge_type=ChallengeType.none,
        elapsed_ms=10, startup_ms=1, cpu_ms=1, peak_rss_mb=1.0, bytes=100,
        redirects=0, error_type=error, date="2026-09-22T00:00:00+00:00",
        kernel="k", docker_version="d", image_version="i", egress_ip=EGRESS,
        asn="AS64500", cell=f"target:{target}")


def scenario_record():
    return RunRecord(
        provider="curl_cffi", provider_version="1", scenario="static", target=None,
        run_id="scenario-static", mode="cold", success=True, sentinel_found=True,
        status=200, final_url="http://stand.invalid/static",
        challenge_type=ChallengeType.none, elapsed_ms=5, startup_ms=1, cpu_ms=1,
        peak_rss_mb=1.0, bytes=10, redirects=0, error_type=FailureReason.none,
        date="2026-09-22T00:00:00+00:00", kernel="k", docker_version="d",
        image_version="i", egress_ip=EGRESS, asn="AS64500", cell="scenario:static")


def bench(*args):
    return subprocess.run([sys.executable, "-m", "bench", *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)


def assert_clean(label, text):
    for secret in SECRETS:
        if secret in text:
            fail(f"{label}: утёк {secret!r}")
    if re.search(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
        fail(f"{label}: в выводе IP-адрес")
    if ".test" in text or "https://" in text or "http://" in text:
        fail(f"{label}: в выводе адрес цели")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        targets = tmp / "local.toml"
        targets.write_text(TARGETS, encoding="utf-8")
        runs = tmp / "run.jsonl"
        records = [
            record("curl_cffi", "leak-id-alpha", True),
            record("curl_cffi", "leak-id-beta", False),
            record("curl_cffi", "leak-id-gamma", False),
            record("patchright", "leak-id-alpha", True),
            record("patchright", "leak-id-beta", True),
            record("patchright", "leak-id-gamma", False),
            record("scrapling", "leak-id-alpha", False, FailureReason.not_measured),
            record("scrapling", "leak-id-beta", True),
            record("scrapling", "leak-id-gamma", False, FailureReason.timeout),
            scenario_record(),
        ]
        runs.write_text("".join(to_jsonl_line(r) for r in records), encoding="utf-8")

        # 1. Сводка: ровно ожидаемая таблица, и никаких id/адресов/IP.
        result = bench("aggregate", str(runs), "--targets", str(targets))
        if result.returncode != 0:
            fail(f"aggregate rc={result.returncode}: {result.stderr[-400:]}")
        lines = result.stdout.splitlines()
        rows = [line for line in lines if line.startswith("|")]
        if rows != EXPECTED_TABLE:
            fail("таблица сводки не та:\n" + "\n".join(rows))
        assert_clean("aggregate stdout", result.stdout)
        assert_clean("aggregate stderr", result.stderr)

        # 2. --output пишет тот же текст и не перезаписывает существующий файл.
        dest = tmp / "summary.md"
        result = bench("aggregate", str(runs), "--targets", str(targets), "--output", str(dest))
        if result.returncode != 0 or dest.read_text(encoding="utf-8").splitlines() != lines:
            fail("aggregate --output записал не то, что печатает stdout")
        dest.write_text("keep", encoding="utf-8")
        result = bench("aggregate", str(runs), "--targets", str(targets), "--output", str(dest))
        if result.returncode == 0 or dest.read_text(encoding="utf-8") != "keep":
            fail("aggregate --output перезаписал существующий файл")

        # 3. Запись о цели, которой нет в файлах целей: отказ без эха id.
        orphan = tmp / "orphan.toml"
        orphan.write_text(TARGETS.split("[[target]]\nid = \"leak-id-gamma\"")[0], encoding="utf-8")
        result = bench("aggregate", str(runs), "--targets", str(orphan))
        if result.returncode != 2:
            fail(f"цель без класса в файлах целей должна давать rc=2, а не {result.returncode}")
        assert_clean("aggregate orphan stderr", result.stderr)

        # 4. Класс, похожий на домен, отвергается — тоже без эха значения.
        dotted = tmp / "dotted.toml"
        dotted.write_text(TARGETS.replace('class = "none"', 'class = "alpha-private-shop.test"'),
                          encoding="utf-8")
        result = bench("aggregate", str(runs), "--targets", str(dotted))
        if result.returncode != 2:
            fail(f"класс с точкой должен давать rc=2, а не {result.returncode}")
        assert_clean("aggregate dotted stderr", result.stderr)

        # 5. Несколько файлов целей склеиваются; дубль id между файлами — отказ.
        extra = tmp / "extra.toml"
        extra.write_text('[[target]]\nid = "public-one"\nurl = "https://public.invalid/"\n'
                         'class = "none"\nexpect = "P"\n', encoding="utf-8")
        result = bench("plan", "--targets", str(targets), str(extra), "--providers", "curl")
        if result.returncode != 0:
            fail(f"plan с двумя файлами целей rc={result.returncode}: {result.stderr[-300:]}")
        cells = set(re.findall(r'"cell": "([^"]+)"', result.stdout))
        want = {"target:leak-id-alpha", "target:leak-id-beta", "target:leak-id-gamma",
                "target:public-one"}
        if cells != want:
            fail(f"plan склеил не те ячейки: {sorted(cells)}")
        result = bench("plan", "--targets", str(targets), str(targets), "--providers", "curl")
        if result.returncode != 2:
            fail(f"дубль id между файлами целей должен давать rc=2, а не {result.returncode}")

        # 6. Публичный файл целей по-прежнему грузится один.
        result = bench("plan", "--targets", "bench/targets/targets.toml", "--providers", "curl")
        if result.returncode != 0:
            fail(f"публичный targets.toml перестал грузиться: {result.stderr[-300:]}")
    print("ok")


if __name__ == "__main__":
    main()
