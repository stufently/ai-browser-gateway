"""Чекер M22: в публичный репозиторий не приезжают новые домены, IP и пути.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m22_no_new_domains.py   ->  печатает `ok`

Директива владельца 22.09.2026: список сайтов мониторинга (и любой другой
список чужих хостов) в публичный репозиторий попасть не должен. Списка
разрешённых имён в файле нет намеренно — чекер сравнивает НЫНЕШНЕЕ дерево
с базовым коммитом: что было при открытии репозитория, то и остаётся, всё
новое считается утечкой, пока постановщик не разрешит его явно.
"""
import re
import subprocess
import sys

BASE_SHA = "43f5f41293aa01010b8750da617753950140cd5d"

# Разрешено добавлять только это: спецификация протокола, на которую честно
# ссылается раздел про MCP. Всё остальное новое — повод остановиться и спросить.
EXTRA_ALLOWED = {"modelcontextprotocol.io", "spec.modelcontextprotocol.io"}

TLDS = ("com|net|org|ru|io|dev|top|shop|ai|app|sh|co|uk|info|xyz|me|cloud|site"
        "|online|store|pro|tech|link|page")
DOMAIN = re.compile(r"(?<![\w.-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + TLDS + r"))(?![\w-])",
                    re.IGNORECASE)
IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])")
HOMEDIR = re.compile(r"/home/\w[\w.-]*")


def run(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def tokens(text):
    found = {m.group(1).lower() for m in DOMAIN.finditer(text)}
    found |= {m.group(1) for m in IPV4.finditer(text)}
    found |= {m.group(0) for m in HOMEDIR.finditer(text)}
    return found


def tracked():
    result = run(["git", "ls-files", "-z"])
    if result.returncode != 0:
        sys.exit("m22_no_new_domains: git ls-files: " + result.stderr.strip())
    return [p for p in result.stdout.split("\0") if p]


def main():
    base = set()
    current = {}
    for path in tracked():
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for token in tokens(text):
            current.setdefault(token, set()).add(path)
        old = run(["git", "show", f"{BASE_SHA}:{path}"])
        if old.returncode == 0:
            base |= tokens(old.stdout)

    leaked = {token: sorted(paths) for token, paths in current.items()
              if token not in base and token not in EXTRA_ALLOWED}
    if leaked:
        lines = [f"  {token} -> {', '.join(paths)}" for token, paths in sorted(leaked.items())]
        sys.exit("m22_no_new_domains: в отслеживаемых файлах появились новые "
                 "домены/адреса/пути:\n" + "\n".join(lines))
    print("ok")


if __name__ == "__main__":
    main()
