"""Title quality: catching entries that have no title at all.

A feed entry whose title is `2026-10-14` is not a story. It is a container — a daily
digest feed using its publication date as the item title, or a page titled after itself.
These entries scored well on every signal we have (long body, official source, fresh) and
reached position 3 of a real digest under the headline "2026-10-14", which is a failure the
reader sees immediately and no scoring weight can fix, because the score is measuring the
container's contents, not the entry.

The rule is deliberately narrow: only reject a title that is *demonstrably* not a title.
A short title is not evidence of anything ("Grok 5" is a real title), and a Chinese
headline of four characters is normal. Guessing at "low information" would punish exactly
the terse headlines this digest wants.
"""

from __future__ import annotations

import re

#: `2026-10-14`, `2026/10/14`, `10-14`, `20261014`, `2026-10-14 09:30`, `Oct 14, 2026`
_DATE_ONLY = re.compile(
    r"^\s*[\[\(]?\s*"
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"          # 2026-10-14
    r"|\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?"     # 10-14 or 10/14/26
    r"|\d{8}"                                     # 20261014
    r"|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})"   # Oct 14, 2026
    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"           # optional clock
    r"\s*[\]\)]?\s*$"
)

#: Titles that are the publication's own name repeated, or a bare section label. These are
#: container pages, not articles. Kept short and explicit on purpose: a broad heuristic
#: here would silently drop legitimate terse headlines.
_CONTAINER_TITLES = {
    "rss", "feed", "atom", "index", "home", "首页", "主页", "归档", "archive",
    "每日归档", "今日归档", "daily", "digest", "newsletter", "untitled", "无标题",
    "no title", "post", "文章", "更新", "最新", "全部", "更多", "more",
}


def is_title_like(title: str) -> bool:
    """True when the title carries information a reader can use.

    Used to *demote* rather than drop: an entry with an unusable title may still be the
    only record of a story, and the digest's job is to not lose sources.
    """
    text = (title or "").strip()
    if not text:
        return False
    if _DATE_ONLY.match(text):
        return False
    if text.lower() in _CONTAINER_TITLES:
        return False
    # A title that is only punctuation or symbols carries nothing.
    if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", text):
        return False
    return True


def title_quality(title: str) -> float:
    """A multiplier in (0, 1] applied to an entry's score.

    Returns 1.0 for a usable title. Everything else lands at 0.15 — enough that the entry
    survives into a digest with room to spare, but far below any real story, so it cannot
    take a headline slot.
    """
    return 1.0 if is_title_like(title) else 0.15
