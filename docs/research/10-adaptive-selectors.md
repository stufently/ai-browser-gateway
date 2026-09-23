# Scrapling adaptive selectors on real redesigns (2026-09-23)

Scrapling advertises that its scrapers "fix themselves" when a site changes
its markup: a selector run with `auto_save=True` stores a fingerprint of the
matched element, and a later run with `adaptive=True` looks for the most
similar element when the selector finds nothing. The gateway returns pages,
not fields, so this feature could only matter to projects that consume the
gateway's HTML and extract data from it. The question here is whether those
projects should adopt it.

## Setup

- `scrapling==0.4.15`, the version the gateway ships, used as a parser only:
  `Selector(html, adaptive=True)` works on HTML from any source, including the
  gateway's output.
- Four pages, each with one snapshot from 2019–2021 and one from September
  2026, taken from the Wayback Machine at pinned timestamps: a PyPI project
  page, a Wikipedia article (legacy Vector skin, then Vector 2022), a GitHub
  repository page (server-rendered, then React), and a LowEndTalk category
  page.
- 15 fields. For each one the old selector is what a scraper written against
  the old page would use; the right answer on the new page is a selector
  written by hand for the new markup. A result counts only if it is the same
  element, not merely similar text.
- Script: [`scripts/adaptive_selectors.py`](scripts/adaptive_selectors.py).
  It downloads the snapshots and prints the tables below;
  `python3 adaptive_selectors.py <cache-dir> 40 60 80` in the one-shot image.

## Result

Five selectors kept working without help: two built on ids, two classes
that survived the redesigns (`td.organiser`, `article.markdown-body`), and
the LowEndTalk list, whose markup did not change. One more still matched, but
the wrong element (the last row below). The other nine found nothing, and
those are the case adaptive mode is for. In eight of them the field is still
on the new page; the GitHub language list is not, because the new page draws
it with JavaScript and the static HTML holds only a loading placeholder.

| Field | Old selector on the new page | `percentage=40` (default) | `percentage=60` | `percentage=80` |
| --- | --- | --- | --- | --- |
| PyPI summary | nothing | relocated | relocated | missed |
| PyPI version header | nothing | relocated | relocated | missed |
| PyPI `pip install` line, by class | nothing | relocated | relocated | relocated |
| Wikipedia first TOC entry | nothing | **wrong element** | missed | missed |
| Wikipedia section heading | nothing | **wrong element** (`Media from Commons`) | missed | missed |
| GitHub description | nothing | **wrong element** (`Public`) | missed | missed |
| GitHub default branch | nothing | missed | missed | missed |
| GitHub commit count | nothing | **wrong element** (`10.1k`, the fork count) | missed | missed |
| GitHub language bar (gone from the HTML) | nothing | **wrong element** (an unrelated dialog) | nothing, correct | nothing, correct |
| Wikipedia stable release, by row number | **empty row, no error** | same | same | same |

- **Where it worked:** PyPI renamed its BEM classes
  (`package-header__name` → `project-header__name`) and moved the summary
  from a section of its own into the page header; tags and text stayed the
  same. The fingerprint found all three fields, including the moved one.
- **Where it failed:** Wikipedia and GitHub rebuilt the page. At the default
  threshold five of the six fields it did not recover came back as a
  different element with no warning: the fork count in place of the commit
  count, the word `Public` in place of the repository description.
- **Threshold:** at 60 the three PyPI fields are still found and every wrong
  relocation turns into "nothing found". At 80 even two of the PyPI fields
  are lost. With a threshold of 60 the fingerprint itself returned no wrong
  element on this set, but it recovered 3 of the 8 broken fields that still
  exist on the new page. The positional selector below stays wrong at any
  threshold.
- **The blind spot:** adaptive mode runs only when the selector finds
  nothing. A positional selector that now points at another row
  (`tr:nth-child(7)` landed on an empty spacer row) returns a wrong value and
  never reaches the fingerprint.

## Reading for consumer projects

- **Adaptive mode handled a moderate markup change, not a rebuild.** PyPI
  renamed classes and moved a block; Wikipedia and GitHub rebuilt the page,
  and there the fingerprint either found nothing or found a neighbour. Four
  sites do not say where the line between the two lies.
- **The default threshold is the dangerous one.** A scraper that returns a
  plausible wrong value (a fork count in the commit-count field) is worse
  than one that fails. Anyone who adopts the feature should set
  `percentage=60` or higher and still validate the value.
- **What actually protects a scraper is failing loudly.** Checking the
  extracted value's shape and stopping when it fails catches four of the six
  silent errors above: three empty values and `10.1k` where an exact count
  is expected. Free text in a free-text field (`Public` as a description,
  `Media from Commons` as a heading) passes any shape check, which is one
  more reason to keep the threshold high. Of the selectors here, those built
  on ids (`#pip-command`, `#firstHeading`) survived every redesign.
- **Consumer history does not ask for it.** The maintainer's scrapers that
  parse third-party pages were checked for fixes caused by a layout change of
  the source site; there were none. Their selectors lean on ids and data
  attributes.

## Decision

- The gateway does not add field extraction; this was already out of scope
  and nothing here changes it.
- Consumer projects do not adopt adaptive selectors now. If a scraper against
  a site that renames classes often shows up, adaptive mode with
  `percentage=60` plus value checks is a reasonable addition there, and this
  script is the way to check the threshold on that site first.

## Limits

Four sites and 15 fields, one pair of snapshots each: this shows how the
feature behaves on real redesigns, not a success rate. The threshold of 60
was chosen on the same set it is reported on.
