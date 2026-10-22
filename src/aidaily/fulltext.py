"""Fetch an article page and keep its prose, for feeds that only carry a teaser.

## Why this exists

Measured 2026-10-22 on a full run: of the sources that produced items, almost all had a body
under 200 characters -- `huggingface` 888/888, `deepmind` 99/100, `therundown.ai` 50/50. Those
feeds publish a headline and a one-line teaser, and the article itself is one request away.

The model is asked to write facts, inferences and uncertainties from this material. Given a
teaser it can only restate the headline, which is why some entries read thin.

## Scope

Only sources that opt in (`site_fulltext: true` in the registry) are fetched. Extracting every
page would multiply the collect time and hit hosts that never wanted it.

## What "the prose" means here

No readability heuristics, no new dependency: take the `<p>` elements, drop the ones that are
navigation or boilerplate, and keep the rest in order. That is enough for the article sites in
this registry and it fails visibly (an empty result leaves the item untouched).
"""

from __future__ import annotations

import re

#: Paragraphs shorter than this are almost always nav, captions or "Read more" links.
_MIN_PARAGRAPH = 60

#: A page whose prose is shorter than this did not yield an article; keep the teaser.
_MIN_BODY = 400

#: Boilerplate that shows up as a paragraph on many sites.
_BOILERPLATE = re.compile(
    r"(cookie|subscribe|newsletter|sign up|advertise|privacy policy|terms of service|"
    r"all rights reserved|share this|follow us|read more)",
    re.IGNORECASE,
)


def extract_body(html: str) -> str:
    """The readable paragraphs of an article page, joined by blank lines.

    Returns "" when the page yields nothing usable, so the caller keeps whatever it had.
    """
    if not html:
        return ""

    # Scripts and styles first: their contents contain `<p>`-like noise and CSS braces.
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", html)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned)
    cleaned = re.sub(r"<noscript[\s\S]*?</noscript>", " ", cleaned)

    paragraphs: list[str] = []
    for raw in re.findall(r"<p[^>]*>([\s\S]*?)</p>", cleaned):
        text = re.sub(r"<[^>]+>", "", raw)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < _MIN_PARAGRAPH:
            continue
        if _BOILERPLATE.search(text):
            continue
        # A paragraph that is one long run of menu labels has no sentence punctuation.
        if text.count(" ") < 8 and not re.search(r"[.。!?！？]", text):
            continue
        paragraphs.append(text)

    body = "\n\n".join(paragraphs)
    if len(body) < _MIN_BODY:
        return ""
    return body[:20_000]
