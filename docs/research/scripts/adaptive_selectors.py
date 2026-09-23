"""Scrapling adaptive selectors on real redesigns (Wayback snapshots).

A fingerprint is saved on the old snapshot (`auto_save=True`); the old
selector is then run on the new snapshot with `adaptive=True`. The right
answer is a selector written by hand for the new markup. See
docs/research/10-adaptive-selectors.md.

Run inside any image with `scrapling==0.4.15`:
  python3 adaptive_selectors.py <cache-dir> [percentage ...]
"""
import gzip
import os
import sys
import tempfile
import urllib.request

from scrapling.parser import Selector

WAYBACK = "https://web.archive.org/web/{}id_/{}"
SNAPSHOTS = {
    "pypi": ("https://pypi.org/project/requests/", "20191231155537", "20260919174735"),
    "wiki": ("https://en.wikipedia.org/wiki/Python_(programming_language)",
             "20210101173036", "20260921061154"),
    "gh": ("https://github.com/psf/requests", "20191231235741", "20260910022006"),
    "let": ("https://lowendtalk.com/categories/offers", "20191231195140", "20260921041901"),
}

# (page, field, old selector, right answer on the new markup). A tuple
# answer is (css, text the element must contain); None means the field is
# not in the new page.
CASES = [
    ("pypi", "summary", "p.package-description__summary", "p.project-header__summary"),
    ("pypi", "version", "h1.package-header__name", "h1.project-header__name"),
    ("pypi", "pip-by-id", "#pip-command", "#pip-command"),
    ("pypi", "pip-by-class", "p.package-header__pip-instructions > span", "#pip-command"),
    ("wiki", "title", "h1#firstHeading", "h1#firstHeading"),
    ("wiki", "developer", "table.infobox td.organiser a", "td.infobox-data.organiser a"),
    ("wiki", "toc-first", "#toc li.toclevel-1 span.toctext",
     ("#toc-History div.vector-toc-text span", "History")),
    ("wiki", "history-heading", "span.mw-headline#History", "h2#History"),
    ("wiki", "stable-release", "table.infobox > tbody > tr:nth-child(7) > td",
     "table.infobox > tbody > tr:nth-child(8) > td"),
    ("gh", "description", "span[itemprop=about]", "p[class*=SidebarAbout-module__description]"),
    ("gh", "branch", "#branch-select-menu span.css-truncate-target",
     "span[class*=RefSelectorText]"),
    ("gh", "readme", "article.markdown-body", "article.markdown-body"),
    ("gh", "commits-count", "ul.numbers-summary li.commits span.num",
     ("span.fgColor-default", "Commits")),
    # The new page renders the language list with JavaScript; the static
    # HTML holds only a loading placeholder, so there is no right element.
    ("gh", "languages", "div.repository-lang-stats", None),
    ("let", "first-title", "li.ItemDiscussion div.Title a", "li.ItemDiscussion div.Title a"),
]


def snapshot(cache, site, age):
    path = os.path.join(cache, f"{site}-{age}.html")
    if not os.path.exists(path):
        url, old, new = SNAPSHOTS[site]
        req = urllib.request.Request(WAYBACK.format(old if age == "old" else new, url),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
        if body[:2] == b"\x1f\x8b":  # Wayback returns the original encoding
            body = gzip.decompress(body)
        with open(path, "wb") as fh:
            fh.write(body)
    with open(path, "rb") as fh:
        return fh.read()


def xpath_of(sel):
    return sel._root.getroottree().getpath(sel._root)


def answer(page, right):
    if right is None:
        return []
    if isinstance(right, str):
        return page.css(right)
    css, needle = right
    return [e for e in page.css(css) if needle in e.get_all_text()]


def short(found):
    return "`" + " ".join(found[0].get_all_text(strip=True).split())[:40] + "`" if found else "—"


def run(cache, percentage):
    store = os.path.join(tempfile.mkdtemp(), "adaptive.db")
    pages = {}
    for site in SNAPSHOTS:
        args = {"storage_file": store, "url": SNAPSHOTS[site][0]}
        pages[site] = tuple(Selector(snapshot(cache, site, age), url=SNAPSHOTS[site][0],
                                     adaptive=True, storage_args=args)
                            for age in ("old", "new"))
    print(f"\npercentage={percentage}\n")
    print("| Page | Field | Old selector, new page | Adaptive, new page | Verdict |")
    print("|---|---|---|---|---|")
    for site, field, old_sel, right in CASES:
        old_page, new_page = pages[site]
        ident = f"{site}:{field}"
        if not old_page.css(old_sel, auto_save=True, identifier=ident):
            sys.exit(f"{ident}: old selector finds nothing on the old snapshot")
        want = answer(new_page, right)
        want = xpath_of(want[0]) if want else None
        plain = new_page.css(old_sel)
        got = new_page.css(old_sel, adaptive=True, identifier=ident, percentage=percentage)
        if plain:
            verdict = "still works" if xpath_of(plain[0]) == want else "wrong match, silent"
        elif not got:
            verdict = "missed" if want else "correctly empty"
        elif xpath_of(got[0]) == want:
            verdict = "relocated"
        else:
            verdict = "wrong relocation"
        print(f"| {site} | {field} | {short(plain)} | {short(got)} | {verdict} |")


def main():
    cache = sys.argv[1]
    os.makedirs(cache, exist_ok=True)
    for pct in [int(p) for p in sys.argv[2:]] or [40]:
        run(cache, pct)


if __name__ == "__main__":
    main()
