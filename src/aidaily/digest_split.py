"""Split a digest entry into the individual stories it is made of.

A digest feed publishes one item per issue: `AI 早报 2026-10-22` arrives as a single entry whose
body lists thirty stories. Treating that entry as one story is wrong twice over -- it is filtered
as a roundup, and if it survived it would occupy one slot in the issue while saying nothing about
any single event.

What the user wants instead: every story in that digest becomes its own candidate, carrying the
**original publisher link** rather than the digest link, and is ranked on its own merits by the
same scorer everything else uses. "不用筛选即可放到我的日报内容内，但要打分" -- nothing is dropped
for coming from a digest, but position is still decided by score.

The two known layouts:

* **Juya** (`daily.juya.uk`) -- an overview `<ul>` of `<li>Title <a href="ORIGINAL">x</a>
  <code>#N</code></li>` grouped under `<h3>section</h3>`, then a detail section with one
  `<h3>Title #N</h3>` per story.
* **Hex2077** -- a weekly issue whose body is prose plus per-story headings.

Only the pattern that is recognised is used. An unrecognised body yields no stories, and the
caller keeps the item as-is, so a layout change degrades to the old behaviour instead of to
silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Story:
    title: str
    url: str
    section: str
    summary: str


#: `<h3>Section</h3>` immediately followed by a list of stories. The overview block.
_SECTION = re.compile(r"<h3[^>]*>([^<]{1,20})</h3>\s*<ul>(.*?)</ul>", re.S)

#: One overview row: title, the ORIGINAL source link, and the story number. The link text is the
#: `↗` glyph in every issue seen; the `code` is `#N`.
_ROW = re.compile(
    r"<li>(?P<title>.+?)\s*<a[^>]+href=\s*\"(?P<url>https?://[^\"]+)\""
    r"[^>]*>.*?</a>\s*(?:<code>#\d+</code>)?</li>",
    re.S,
)

_TAG = re.compile(r"<[^>]+>")

#: Section names a digest uses. Recognising them keeps a page of prose from being parsed as a
#: story list: without this, any `<h3>` followed by `<ul>` would qualify.
KNOWN_SECTIONS = {
    "要闻", "开发生态", "模型发布", "产品应用", "技术与洞察", "行业动态",
    "概览", "快讯", "其他", "头条",
}


def _text(html: str) -> str:
    return " ".join(_TAG.sub(" ", html).split())


def split_digest(body_html: str) -> list[Story]:
    """Stories in a digest issue, or `[]` when the layout is not recognised.

    The overview list is preferred over the detail section: it carries the original link, which is
    what must appear as the story source. A story whose link points back into the digest itself
    is dropped -- that is a table of contents, not a source.
    """
    html = body_html or ""
    if not html.strip():
        return []

    stories: list[Story] = []
    seen: set[str] = set()
    for section_m in _SECTION.finditer(html):
        section = _text(section_m.group(1))
        if section not in KNOWN_SECTIONS:
            continue
        for row_m in _ROW.finditer(section_m.group(2)):
            title = _text(row_m.group("title"))
            url = row_m.group("url").strip()
            if len(title) < 8 or not url:
                continue
            # A row that links to the digest itself is navigation, not a story.
            if _is_self_link(url):
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            stories.append(Story(title=title[:200], url=url, section=section, summary=""))
    return stories


#: Hosts that are a digest rather than a publisher.
_SELF_HOSTS = ("juya.uk", "hex2077.dev", "aihot.news")


def _is_self_link(url: str) -> bool:
    return any(host in url for host in _SELF_HOSTS)


#: Feeds that publish one entry per ISSUE rather than per story, recognised by host.
#:
#: Configured here rather than in `sources/local.yaml` because two of the three are audited
#: sources: `build_registry.py` refuses a local row that shadows an audited one ("增补源必须用新的
#: source_id"), and the audit ledger carries no `params` field to hold the flag. Keying off the
#: host also means a feed that moves to a new path on the same site keeps working.
DIGEST_HOSTS = (
    "daily.juya.uk",
    "hex2077.dev",
)


def is_digest_feed(url: str) -> bool:
    host = (url or "").lower()
    if any(h in host for h in DIGEST_HOSTS):
        return True
    # AIHOT publishes both: `/feed/full.xml` is one entry per story and must NOT be split,
    # while `/feed/daily.xml`, `/weekly.xml`, `/monthly.xml` are issues.
    if "aihot.news/feed/" in host:
        return any(k in host for k in ("daily", "weekly", "monthly"))
    return False


def is_digest_title(title: str) -> bool:
    """Whether this entry is an issue of a digest rather than a single story.

    Needed because the digest entries have to be routed to `split_digest` before the roundup
    filter sees them: `AI 早报 2026-10-22` matches the roundup pattern, and dropping it is the
    exact behaviour that loses every story inside.
    """
    text = (title or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return True
    return bool(re.search(r"(早报|日报|晚报|周报|月刊|weekly|daily)", text, re.I))
