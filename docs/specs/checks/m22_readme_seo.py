"""Чекер M22: публичный README собран под поиск и цитирование.

Владеет постановщик; исполнитель его не правит. Запуск из корня клона:
  python3 docs/specs/checks/m22_readme_seo.py      ->  печатает `ok`

Чекер проверяет СТРУКТУРУ и внутреннюю связность, а не красоту текста:
состав и порядок разделов, наличие ответов на поисковые вопросы, таблицу
сравнения провайдеров, рабочие относительные ссылки и отсутствие
локальных id образа в командах (грабля M21-fix1).
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
RU = ROOT / "docs" / "README.ru.md"

REQUIRED_H2 = [
    "Why",
    "When a plain fetch is not enough",
    "Quick start",
    "CLI reference",
    "How the provider ladder works",
    "MCP server for AI agents",
    "Self-hosted HTTP API",
    "How it compares",
    "Benchmarks",
    "FAQ",
    "Responsible use",
    "Development",
    "Documentation",
    "License",
]
TAGLINE_MAX = 200
TAGLINE_TERMS = ("ai agent", "cloudflare")
SYMPTOM_TERMS = ("403", "just a moment")
LADDER_TERMS = ("curl_cffi", "patchright", "scrapling")
BENCH_KEEP = "not a general success-rate promise"
FAQ_MIN = 6


def fail(message):
    sys.exit("m22_readme_seo: " + message)


def strip_code(lines):
    """Строки вне ``` -блоков: в примерах команд заголовков и ссылок не ищем."""
    out, fenced = [], False
    for line in lines:
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return out


def sections(lines):
    """{заголовок H2: [строки тела]} плюс порядок заголовков."""
    order, body, current = [], {}, None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            order.append(current)
            body[current] = []
        elif current is not None:
            body[current].append(line)
    return order, body


def slug(text):
    text = re.sub(r"`", "", text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def check_links(path):
    text = path.read_text(encoding="utf-8")
    anchors = {slug(m.group(2)) for m in re.finditer(r"^(#+)\s+(.*)$", text, re.M)}
    for match in re.finditer(r"\]\(([^)\s]+)\)", text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            if target[1:] not in anchors:
                fail(f"{path.name}: якорь {target} не ведёт ни к одному заголовку")
            continue
        head = target.split("#", 1)[0]
        if head and not (path.parent / head).exists():
            fail(f"{path.name}: ссылка {target} ведёт в несуществующий файл")


def main():
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "# AI Browser Gateway":
        fail("первая строка README должна быть заголовком # AI Browser Gateway")

    tagline = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith(("## ", "[![", "![")):
            break
        if stripped:
            tagline.append(stripped)
        elif tagline:
            break
    joined = " ".join(tagline)
    if not joined:
        fail("между заголовком и бейджами нет абзаца-описания")
    if len(joined) > TAGLINE_MAX:
        fail(f"абзац-описание длиннее {TAGLINE_MAX} символов: {len(joined)}")
    low = joined.lower()
    for term in TAGLINE_TERMS:
        if term not in low:
            fail(f"в абзаце-описании нет ключевого слова {term!r}")

    clean = strip_code(lines)
    order, body = sections(clean)
    if order != REQUIRED_H2:
        fail(f"состав или порядок разделов H2 не тот: {order}")

    symptoms = "\n".join(body["When a plain fetch is not enough"]).lower()
    bullets = [x for x in body["When a plain fetch is not enough"] if x.startswith("- ")]
    if len(bullets) < 3:
        fail("в разделе про недостаточность обычного запроса меньше трёх пунктов списка")
    for term in SYMPTOM_TERMS:
        if term not in symptoms:
            fail(f"раздел про недостаточность обычного запроса не называет признак {term!r}")

    compare = body["How it compares"]
    rows = [x for x in compare if x.startswith("|")]
    if len(rows) < 6:
        fail("в разделе сравнения нет таблицы минимум с четырьмя строками данных")
    compare_text = "\n".join(compare)
    for term in LADDER_TERMS:
        if term not in compare_text:
            fail(f"таблица сравнения не называет провайдера {term}")

    faq = body["FAQ"]
    questions = [x for x in faq if x.startswith("### ")]
    if len(questions) < FAQ_MIN:
        fail(f"в FAQ меньше {FAQ_MIN} вопросов: {len(questions)}")
    for question in questions:
        if not question.rstrip().endswith("?"):
            fail(f"заголовок FAQ не сформулирован вопросом: {question}")
    answers, current = {}, None
    for line in faq:
        if line.startswith("### "):
            current = line
            answers[current] = []
        elif current and line.strip():
            answers[current].append(line)
    for question, answer in answers.items():
        if not answer:
            fail(f"вопрос FAQ без ответа: {question}")

    bench = "\n".join(body["Benchmarks"])
    if BENCH_KEEP not in bench:
        fail("из раздела Benchmarks пропала оговорка об ограниченности выборки")
    if "docs/research/" not in bench:
        fail("раздел Benchmarks не ссылается на исследования в docs/research/")

    docs = "\n".join(body["Documentation"])
    if "docs/README.ru.md" not in docs:
        fail("раздел Documentation не ссылается на русский README")

    if re.search(r"sha256:[0-9a-f]{64}", text):
        fail("в README остался локальный id образа sha256:… — чужой его не скачает")

    check_links(README)
    check_links(RU)
    print("ok")


if __name__ == "__main__":
    main()
