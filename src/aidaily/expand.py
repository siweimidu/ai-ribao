"""Fetch an article page and split it into the stories it contains.

## Why this exists

The collector reads feeds. For a daily roundup that is not enough: the feed entry is the
*issue*, and the news is inside the issue. Measured 2026-10-20 on `ainewslog`: 480 feed items,
median body 92 characters, while one article page held 21 stories averaging 200 characters each.
The registry therefore gained a source 488 issues deep whose content was almost entirely
invisible -- one line a day instead of twenty stories.

## What it does

For an item flagged as a roundup, fetch its URL once, hand the HTML to `article.split_article`,
and return one `RawItem` per story. Everything else passes through untouched.

## Cost control

One HTTP request per roundup item, not per story, and only for items that look like roundups
(title matches a daily-issue shape). The fetch is sequential with a small delay, because these
are ordinary web pages belonging to someone else.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from .article import split_article
from .models import RawItem

#: Why an expansion did not happen, drained by the caller into the run log.
#:
#: A silent `return [item]` made a blocked page and a page the splitter could not
#: parse look identical -- the first production run expanded 0 of 488 issues and
#: said nothing at all.
_NOTE: list[tuple[str, str]] = []


#: Titles that mark an item as a daily issue rather than a single article.
#: `AI 日报 — 2026-10-19`, `AI Daily — 2026-10-19`, `AI 日报 2026-10-19`.
_ISSUE_TITLE = re.compile(
    r"(AI\s*日报|AI\s*Daily|AI\s*News\s*Log).{0,12}\d{4}[-年]\d{1,2}[-月]\d{1,2}",
    re.IGNORECASE,
)

#: A body longer than this already carries the news; no need to fetch.
_ALREADY_RICH = 1200


def looks_like_issue(item: RawItem) -> bool:
    """Whether this item is a whole day's news rather than one story.

    Both conditions must hold: the title names a date, *and* the body is thin. A long body means
    the feed already carried the text, and fetching again would only duplicate it.
    """
    body = (item.content_text or item.summary or "")
    return bool(_ISSUE_TITLE.search(item.title or "")) and len(body) < _ALREADY_RICH


async def expand_issue(
    item: RawItem,
    http,
    *,
    min_stories: int = 3,
    delay_s: float = 1.0,
) -> list[RawItem]:
    """The stories inside one issue, or `[item]` when it cannot be expanded.

    Never raises: a page that will not load leaves the original item in place, which is exactly
    the behaviour before this module existed.
    """
    if not looks_like_issue(item):
        return [item]

    url = item.url or ""
    if not url.startswith(("http://", "https://")):
        return [item]

    # `HttpClient` already spaces requests to one host, but a burst of 488 issue pages still
    # trips the host's own rate limit. This delay is ours, and it is paid before every request
    # so a run that is failing slows down instead of hammering.
    await asyncio.sleep(delay_s)
    try:
        result = await http.get(url)
    except Exception as exc:  # noqa: BLE001 - a page that will not load is not fatal
        _NOTE.append((item.source_id, f"expand: {type(exc).__name__}"))
        return [item]

    if not getattr(result, "ok", False):
        _NOTE.append(
            (item.source_id, f"expand: HTTP {getattr(result, 'status', None)} {getattr(result, 'verdict', '')}")
        )
        return [item]

    html = result.body.decode("utf-8", "replace") if getattr(result, "body", b"") else ""
    if not html:
        _NOTE.append((item.source_id, "expand: empty body"))
        return [item]

    stories = split_article(html, min_stories=min_stories)
    if not stories:
        _NOTE.append((item.source_id, f"expand: split found no stories in {len(html)} chars"))
        return [item]

    expanded: list[RawItem] = []
    for index, story in enumerate(stories, start=1):
        expanded.append(
            RawItem(
                source_id=item.source_id,
                title=story.title,
                url=f"{url}#story-{index}",
                summary=story.summary[:2000],
                content_text=story.summary or story.title,
                published_at=item.published_at,
                language=item.language,
                author=story.source or item.author,
            )
        )
    return expanded


#: How many issues one source may expand in a single run.
#:
#: `ainewslog` publishes 488 issues; fetching all of them every run is 488 requests to one host,
#: which its rate limit refuses -- measured: every request after the first few came back blocked
#: and nothing expanded. The newest issues are the ones a daily digest needs, and older ones are
#: already in the archive, so a cap loses nothing that matters and keeps the run polite.
MAX_ISSUES_PER_SOURCE = 12


async def expand_all(
    items: list[RawItem],
    http,
    *,
    min_stories: int = 3,
    max_issues: int = MAX_ISSUES_PER_SOURCE,
) -> list[RawItem]:
    """Expand issues in `items`, newest first, up to `max_issues` of them.

    Ordinary items pass through untouched, and anything past the cap passes through as well --
    an unexpanded issue is still a valid item, just a thin one.
    """
    issues = [i for i in items if looks_like_issue(i)]
    issues.sort(key=lambda i: (i.published_at or datetime.min.replace(tzinfo=timezone.utc), i.url), reverse=True)
    chosen = {id(i) for i in issues[:max_issues]}

    out: list[RawItem] = []
    for item in items:
        if id(item) in chosen:
            out.extend(await expand_issue(item, http, min_stories=min_stories))
        else:
            out.append(item)
    return out


def drain_notes() -> list[tuple[str, str]]:
    """Take the accumulated expansion notes, clearing them.

    The caller appends these to the run log, so a run that expanded nothing can be told apart
    from a run that had nothing to expand.
    """
    notes = list(_NOTE)
    _NOTE.clear()
    return notes