"""Split a roundup feed item into the stories it contains.

## The measured failure

The user asked why DeepSeek's five-hour outage and its "用多少送多少" credit giveaway was not
in the digest, when this pipeline already ingests 橘鸦's feed. It was not ranked low -- **it
was never an event at all**. It appeared only inside item #59, `AI早报：Codex活动、DeepSeek恢复
与多款模型发布`, demoted to `focus=0.33` because that item is another daily's roundup.

`daily.juya.uk` publishes **one item per day**, titled `2026-10-15`, whose body holds the whole
day's news:

    要闻
    Claude Code 桌面版更新优化多会话体验 ↗ #1
    Claude Code 新增闲置会话自动压缩 ↗ #2
    模型发布
    TypeSafe AI 更新 Jev，开放图像与长上下文功能 ↗ #3
    ...

The collector produced one `RawItem` for the entire day, so clustering, scoring and the rubric
all saw a single story called `2026-10-15`. No scoring change could have surfaced DeepSeek's
outage, because there was nothing to score.

## What this does

Detects the numbered-headline shape and emits one `RawItem` per headline, keeping the roundup
as the citation. The individual headlines link out to their own sources, but text extraction
drops the hrefs, so the honest reference is the roundup itself at `#N` -- which is verifiable
and is what a reader following the link actually lands on.

## Why the shape test is strict

A body is treated as a roundup only when it has a **run of numbered headlines** (`#1`, `#2`,
`#3` …), not merely a number or two. A news article quoting "#1" once must not be shredded
into fragments, and the cost of a false positive -- one story becoming twenty unrelated ones --
is much higher than the cost of a false negative, where the roundup is simply one item as
before.
"""

from __future__ import annotations

import re
from datetime import datetime

from .models import RawItem, SourceSpec

#: A numbered headline. The arrow is 橘鸦's link marker and survives text extraction; other
#: roundups in the same family use the number alone.
#:
#: `re.MULTILINE` is required, not decorative: without it `^` and `$` anchor to the ends of the
#: **whole body**, so at most one line can ever match however many headlines the body has. The
#: detector then reports zero roundups, which is exactly what the first version did on a body
#: with 58 numbered headlines.
_HEADLINE = re.compile(
    r"^(?P<title>.+?)\s*(?:↗|→|»)?\s*#(?P<n>\d{1,3})\s*$", re.MULTILINE
)

#: Section headings that carry no story of their own.
_SECTION = re.compile(
    r"^(要闻|概览|模型发布|开发生态|产品应用|技术与洞察|行业动态|研究|政策|其他|"
    r"今日要闻|新闻|资讯|快讯)$"
)

#: A title that is only a date is a container, not a story. Same rule the ranker applies.
_DATE_ONLY = re.compile(r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$")

#: At least this many numbered headlines before a body is treated as a roundup.
MIN_HEADLINES = 5


def looks_like_roundup(item: RawItem) -> bool:
    """True when this item's body is a list of numbered headlines.

    Cheap and total: it counts matches rather than parsing, so a malformed body answers `False`
    instead of raising inside the collector.
    """
    if not _DATE_ONLY.match((item.title or "").strip()):
        # A roundup is *titled* by its date. An article that happens to contain numbered lines
        # keeps its own title and is left alone.
        return False
    return len(_HEADLINE.findall(body_of(item))) >= MIN_HEADLINES


def body_of(item: RawItem) -> str:
    """The long text, preferring `content_text` over the truncated `summary`."""
    return item.content_text or item.summary or ""


def split_roundup(item: RawItem, spec: SourceSpec | None = None) -> list[RawItem]:
    """One `RawItem` per headline, or `[item]` when it is not a roundup.

    Returning the input unchanged rather than an empty list keeps the caller free of a special
    case: `split_roundup` is always safe to map over every collected item.
    """
    if not looks_like_roundup(item):
        return [item]

    body = body_of(item)
    out: list[RawItem] = []
    seen: set[str] = set()

    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("-*• \t")
        if not line or _SECTION.match(line):
            continue
        m = _HEADLINE.match(line)
        if not m:
            continue
        title = m.group("title").strip().strip("：:，,")
        if len(title) < 6 or title in seen:
            continue
        seen.add(title)
        number = int(m.group("n"))
        # Keep the trailing slash. `url.rstrip('/') + '#29'` produces
        # `https://daily.juya.uk/issues/2026-10-15#29`, which the server redirects to
        # `.../2026-10-15/` and **the fragment is lost on the way** -- the citation then lands
        # on the issue rather than the story.
        base = item.url if item.url.endswith("/") else item.url + "/"
        out.append(RawItem(
            source_id=item.source_id,
            title=title[:300],
            # The roundup itself, at the story's number. The outgoing href is lost in text
            # extraction, so this is the reference a reader can actually follow and check.
            url=f"{base}#{number}",
            published_at=item.published_at,
            summary=title,
            content_text=None,
            author=item.author,
            language=item.language,
            # Recorded so the audit trail shows this came out of a roundup rather than
            # arriving on its own; the ranker treats a roundup split as its own evidence.
            metrics={
                **(item.metrics or {}),
                "roundup_of": item.url,
                "roundup_index": number,
            },
            native_id=f"{item.native_id or item.url}#{number}",
        ))

    return out or [item]


def split_all(items: list[RawItem], specs: dict[str, SourceSpec] | None = None) -> list[RawItem]:
    """Split every roundup in a collection run, leaving ordinary items untouched.

    Reports nothing and raises nothing: a roundup that fails to split stays one item, which is
    the pre-existing behaviour and never worse than it.
    """
    out: list[RawItem] = []
    for item in items:
        try:
            out.extend(split_roundup(item, (specs or {}).get(item.source_id)))
        except Exception:  # noqa: BLE001 - a split failure must not lose the item
            out.append(item)
    return out
