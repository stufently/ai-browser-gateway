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

# Общий шаблон «любая зона» ловил бы имена файлов (`cli.py`, `README.md`),
# поэтому зоны перечислены; метки допускают `_` и не-ASCII буквы (IDN).
TLDS = ("com|net|org|ru|io|dev|top|shop|ai|app|sh|co|uk|info|xyz|me|cloud|site"
        "|online|store|pro|tech|link|page|biz|us|eu|de|fr|nl|pl|ua|by|kz|su|jp|cn"
        "|in|th|vn|id|sg|tr|br|ca|au|tv|cc|ws|to|onion|рф|xn--[a-z0-9-]+")
DOMAIN = re.compile(r"(?<![\w.-])((?:[^\W](?:[\w-]*[^\W])?\.)+(?:" + TLDS + r"))(?![\w-])",
                    re.IGNORECASE)
IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])")
# IPv6: только формы с `::` или из восьми групп, иначе ловятся отметки времени.
IPV6 = re.compile(r"(?<![\w:])((?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
                  r"|(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?)(?![\w:])",
                  re.IGNORECASE)
HOMEDIR = re.compile(r"/home/\w[\w.-]*", re.IGNORECASE)


def run(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def tokens(text):
    found = {m.group(1).lower() for m in DOMAIN.finditer(text)}
    found |= {m.group(1) for m in IPV4.finditer(text)}
    found |= {m.group(1).lower() for m in IPV6.finditer(text)}
    found |= {m.group(0) for m in HOMEDIR.finditer(text)}
    return found


def tracked():
    result = run(["git", "ls-files", "-z"])
    if result.returncode != 0:
        sys.exit("m22_no_new_domains: git ls-files: " + result.stderr.strip())
    return [p for p in result.stdout.split("\0") if p]


def read_text(path):
    """Текст файла; None — двоичный файл. Нечитаемый текст — отказ, а не пропуск."""
    try:
        raw = open(path, "rb").read()
    except OSError as exc:
        sys.exit(f"m22_no_new_domains: {path}: {exc.strerror}")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        sys.exit(f"m22_no_new_domains: {path}: не UTF-8, проверить нельзя")


def main():
    base = set()
    current = {}
    for path in tracked():
        text = read_text(path)
        if text is None:
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
