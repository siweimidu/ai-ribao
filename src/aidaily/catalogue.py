"""Catalogue rows are not stories, whoever serves them.

Measured 2026-10-25, after `api:aibase-com` was exempted from filtering: 28 of its 40 items
were navigation chrome rather than news,

    #2 Gemini & Gemini Advanced gemini.google.com
    #3 Claude 2 claude.ai
    AI Tools Directory
    Full Ranking

and two of them ranked into the top ten of the issue. `#2 Gemini & Gemini Advanced` tells a
reader nothing that happened.

That source is no longer exempt, but the shape is not unique to it: any extractor pointed at a
listing page will produce it. This is the content-level guard, so the defect cannot return
through a different feed.
"""

from __future__ import annotations

import re

#: `#2 Gemini & Gemini Advanced gemini.google.com` -- a rank number, a name, a bare domain.
#: The rank number is what distinguishes it from a headline that happens to end in a domain.
#: The domain part allows subdomains (`gemini.google.com`) and any TLD.
_RANKED_LINK = re.compile(
    r"^#\d+\s+\S.*?\s+(?:[a-z0-9-]+\.)+[a-z]{2,}\s*$", re.IGNORECASE
)

#: Phrases that only appear on a listing page.
_CATALOGUE_PHRASES = (
    "ai tools directory",
    "full ranking",
    "brand monitoring",
    "view all tools",
    "browse all",
    "see all tools",
)


def is_catalogue_row(title: str) -> bool:
    """True when the title is a navigation entry rather than a piece of news."""
    text = (title or "").strip()
    if not text:
        return True
    if _RANKED_LINK.match(text):
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in _CATALOGUE_PHRASES)