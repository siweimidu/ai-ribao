"""Fix live juya extraction: story-by-story DOM structure, no denormalized whole-page junk.

The feed's `content` is an HTML **render of the issue page**, not a plain-text outline. Its story
rows have two shapes:

* the first announcements have `<h3><a href="source">title</a> <code>#1</code></h3>` followed by
  the full analysis blocks for that one story;
* the category lists have `<li>title <a href="source">↗</a> <code>#29</code></li>`.

The old stripper ran on the entire document, erased every tag boundary except `</p>`, and compared
the resulting 40 KB page against the feed's 360-character summary when choosing normalised content.
The title/summary similarity was **4.3%**, so it set the *date* as title and kept the whole HTML
as body: one polluting entry per issue. The splitter then looked for numbered plain-text lines
that were no longer present. That is the production root cause.

Split here, directly from the HTML's semantic units, before generic normalization. One article
per story, not one article per issue; `h3` stories carry their paragraphs, list stories carry their
visible headline and their source's href.
"""

from __future__ import annotations

import re
import sys
from typing import Callable
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

from .models import RawItem, SourceSpec

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RANK = re.compile(r"#\s*(\d{1,3})\b")

#: Section headings. `<h3>要闻</h3>` carries no rank of its own, but its *next* ranked sibling
#: belongs to the section, so `_rank_after` finds `#1` and the heading was emitted as a story
#: titled `要闻`. These are structure, not news.
_SECTION = re.compile(
    r"^(要闻|概览|模型发布|开发生态|产品应用|技术与洞察|行业动态|研究|政策|其他|"
    r"今日要闻|新闻|资讯|快讯|产品|技术)$"
)

#: Plain-text fallback: `Title ↗ #12`. Kept because an older cached item, or a roundup that
#: ships text rather than HTML, still has to be splittable.
_HEADLINE = re.compile(r"^(?P<title>.+?)\s*(?:↗|→|»)?\s*#(?P<n>\d{1,3})\s*$", re.MULTILINE)


def looks_like_roundup(item: RawItem) -> bool:
    """Roundup pages are date-titled entries whose body contains ranked issue links."""
    if not _DATE_ONLY.fullmatch((item.title or "").strip()):
        return False
    html = item.content_text or item.summary or ""
    if "<" not in html:
        # Plain text is still supported for cached/older versions.
        return len(_HEADLINE.findall(html)) >= 5
    soup = BeautifulSoup(html, "html.parser")
    return bool(soup.find("h3") and len(soup.find_all("code", string=_RANK)) >= 5)


def split_roundup(item: RawItem, spec: SourceSpec | None = None) -> list[RawItem]:
    """Extract each live Juya story into a normal RawItem, preserving its source URL.

    An unmatched/non-roundup item is returned unchanged. The issue's own page URL is stored as
    `roundup_of`; story URLs are the exact hrefs Juya published, never guessed or manufactured.
    """
    raw = item.content_text or item.summary or ""
    if not raw:
        return [item]

    # **The roundup test comes first, for both shapes.** It used to sit after the plain-text
    # branch, so every non-roundup item with a text body went straight to `_split_plain_text`
    # and was shredded by whatever `#N` happened to appear in it -- the exact false positive the
    # title check exists to prevent.
    if not looks_like_roundup(item):
        return [item]

    if "<" not in raw:
        return _split_plain_text(item, raw)

    soup = BeautifulSoup(raw, "html.parser")

    base = item.url
    output: list[RawItem] = []
    seen: set[str] = set()

    # Shape 1: top stories are headings with a complete article block after them. The next h3,
    # h2, or hr is the boundary; retain the prose up to it for analysis, not just the headline.
    for heading in soup.find_all("h3"):
        title = _visible_title(heading)
        rank = _rank_after(heading)
        if not title or rank is None or title in seen:
            continue
        # A bare section name is a heading for the list below it, not a story.
        if _SECTION.match(title) and not heading.find("a", href=True):
            continue
        seen.add(title)
        content: list[str] = []
        for node in heading.next_elements:
            if getattr(node, "name", None) in {"h2", "h3", "hr"}:
                break
            if getattr(node, "name", None) in {"p", "blockquote", "ul", "ol"}:
                block = node.get_text(" ", strip=True)
                if block and block not in content:
                    content.append(block)
        urls = _links_for(heading, [heading, *[e for e in heading.next_elements
                                    if getattr(e, "name", None) in {"p", "blockquote", "ul", "ol"}]])
        output.append(_make_item(item, title, rank, "\n\n".join(content), urls))

    # Shape 2: later section entries are list items. Extract each ranked <li>, but do not
    # duplicate a story already taken from an h3 block.
    for li in soup.find_all("li"):
        title = _visible_title(li)
        rank = _rank_after(li)
        if not title or rank is None or title in seen:
            continue
        seen.add(title)
        urls = [
            urljoin(base, str(a.get("href")))
            for a in li.find_all("a", href=True)
            if _is_story_link(a, base)
        ]
        output.append(_make_item(item, title, rank, title, urls))

    # Some older issues keep the ranked label in plain text immediately after the title.
    if not output:
        return _split_plain_text(item, soup.get_text("\n"))
    output.sort(key=lambda r: int((r.metrics or {}).get("roundup_index", 9999)))
    return output


def _visible_title(node) -> str:
    """Visible headline only; omit link glyphs and #N marker from the story title."""
    parts: list[str] = []
    for child in node.children:
        name = getattr(child, "name", None)
        if name == "code" and _RANK.search(child.get_text(" ", strip=True)):
            continue
        text = child.get_text(" ", strip=True) if name else str(child).strip()
        if text and text not in {"↗", "→", "»"}:
            parts.append(text)
    title = " ".join(" ".join(parts).split())
    title = re.sub(r"\s+(?:↗|→|»)\s*$", "", title).strip()
    return title


def _rank_after(node) -> int | None:
    # Rank can be a code sibling after the outgoing link, or part of the plain text.
    siblings = list(node.next_siblings)
    for sibling in siblings[:4]:
        text = sibling.get_text(" ", strip=True) if getattr(sibling, "name", None) else str(sibling)
        match = _RANK.search(text or "")
        if match:
            return int(match.group(1))
        if getattr(sibling, "name", None) in {"h2", "h3", "hr", "li"}:
            break
    text = node.get_text(" ", strip=True)
    match = _RANK.search(text)
    return int(match.group(1)) if match else None


def _is_story_link(anchor, base: str) -> bool:
    href = str(anchor.get("href") or "")
    if not href or href.startswith("#"):
        return False
    label = anchor.get_text(" ", strip=True)
    # Ignore issue navigation / video links; retain explicitly attached source citations.
    return label not in {"YouTube", "哔哩哔哩", "↗", "→", "»"} or bool(re.search(r"https?://", href))


def _links_for(heading, blocks) -> list[str]:
    links: list[str] = []
    for block in blocks:
        for a in block.find_all("a", href=True):
            if _is_story_link(a, ""):
                links.append(str(a["href"]))
    return links


def _make_item(parent: RawItem, title: str, rank: int, body: str, urls: list[str]) -> RawItem:
    # Choose the first URL actually published with this story. If no URL is attached, use the
    # issue anchor as the citation, because that is the only verifiable place it appears.
    base = parent.url if parent.url.endswith("/") else parent.url + "/"
    story_url = next((urldefrag(url)[0] for url in urls if url), f"{base}#{rank}")
    native = f"{parent.native_id or parent.url}#juya-{rank}"
    return RawItem(
        source_id=parent.source_id,
        title=title[:300],
        url=story_url,
        published_at=parent.published_at,
        summary=(body or title)[:2000],
        content_text=(body or title)[:12000],
        author=parent.author,
        language=parent.language,
        metrics={**(parent.metrics or {}), "roundup_of": parent.url, "roundup_index": rank},
        native_id=native,
    )


def _split_plain_text(item: RawItem, text: str) -> list[RawItem]:
    """Split a text roundup, emitting each distinct headline once.

    Deduplicated by title: some issues repeat a headline in a "seen elsewhere" section, and two
    identical stories would be merged straight back together by L2 while still costing two model
    calls.
    """
    output: list[RawItem] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _HEADLINE.match(line.strip())
        if not match:
            continue
        title = match.group("title").strip()
        if title in seen:
            continue
        seen.add(title)
        output.append(_make_item(item, title, int(match.group("n")), title, []))
    return output or [item]


def split_all(
    items: list[RawItem],
    specs: dict[str, SourceSpec] | None = None,
    *,
    on_error: Callable[[RawItem, Exception], None] | None = None,
) -> list[RawItem]:
    """Split every roundup in a collection run, leaving ordinary items untouched.

    A roundup that fails to split stays one item -- never worse than before -- but the failure is
    **reported, not swallowed**. An earlier version caught every exception and appended the item
    unchanged, which made "not a roundup" and "the splitter crashed" produce byte-identical
    output. Measured consequence: a production collect run wrote 4836 items with zero splits
    while the same splitter on the same ten roundup items produced 37 and 29 stories, and the log
    said nothing either way.
    """
    out: list[RawItem] = []
    for item in items:
        try:
            out.extend(split_roundup(item, (specs or {}).get(item.source_id)))
        except Exception as exc:  # noqa: BLE001 - a split failure must not lose the item
            (on_error or _report_split_error)(item, exc)
            out.append(item)
    return out


def _report_split_error(item: RawItem, exc: Exception) -> None:
    print(
        f"roundup: 拆分失败，保留原条目 {item.source_id} {item.title[:40]!r} "
        f"({type(exc).__name__}: {exc})",
        file=sys.stderr,
    )
