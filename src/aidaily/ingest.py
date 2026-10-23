"""Ingest: RawItem -> NormalizedItem.

This is where the pipeline stops trusting the source. Three decisions matter:

* **A missing date stays missing.** `published_at` is never backfilled with the
  fetch time. `age_bucket` then reports `unknown`, and downstream prompts are told not to make
  time claims about it. Inventing a date is how a digest ends up asserting that a
  two-year-old GitHub repo was "released today".
* **Window sources are labelled, not faked.** GitHub Trending's "today" is a star-delta
  window and Google Trends' is a 7-day aggregate; neither has a per-item publication
  date. They get `today_window` so they are treated as today's signal *by definition*
  (the same convention dailydawn arrived at, for the same reason).
* **The original URL is kept verbatim** alongside the normalized key.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone

from .models import AgeBucket, NormalizedItem, RawItem, SourceSpec
from .normalize import (
    content_fingerprint,
    simhash,
    strip_html,
    strip_text_urls,
    title_norm,
    try_normalize_url,
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WS_RE = re.compile(r"\s+")

#: Adapters whose items have no per-item publication date by construction.
WINDOW_ADAPTERS = {"GitHubTrendingFetcher", "PyTrendsFetcher"}


def detect_language(text: str, sample: int = 400) -> str | None:
    """Cheap script-based language guess: 'zh' or 'en', else None.

    Deliberately not a language-detection model: we only need to separate Chinese from
    Latin-script feeds, and a heuristic that cannot be wrong about *content* is safer
    than one that silently relabels a source.
    """
    if not text:
        return None
    head = text[:sample]
    letters = [c for c in head if c.isalpha() or _CJK_RE.match(c)]
    if not letters:
        return None
    cjk = sum(1 for c in letters if _CJK_RE.match(c))
    ratio = cjk / len(letters)
    if ratio >= 0.15:
        return "zh"
    if ratio <= 0.02:
        return "en"
    return None


def compute_age_bucket(
    published_at: datetime | None, today_utc: date, *, window_source: bool
) -> AgeBucket:
    if window_source:
        return "today_window"
    if published_at is None:
        return "unknown"
    days_ago = (today_utc - published_at.astimezone(timezone.utc).date()).days
    if days_ago <= 0:
        return "today"
    if days_ago <= 3:
        return "past_72h"
    return "older"


def item_id_for(spec: SourceSpec, raw: RawItem) -> str:
    """Stable identity: prefer the source's own native id, else the normalized URL.

    Using the native id means a feed that re-issues an item under a new URL still maps
    to the same record; using the URL is the fallback when the feed provides nothing.
    """
    basis = raw.native_id or try_normalize_url(raw.url) or raw.url or raw.title
    return hashlib.sha256(f"{spec.source_id}|{basis}".encode("utf-8")).hexdigest()[:16]


#: A stripped body shorter than this carries no identifying content.
#:
#: InfoQ RSS entries all end in `点击查看原文>` (six characters) after markup is removed, and
#: plenty of feeds carry only a link line or a "read more" stub. Hashing those made every entry
#: of the feed identical to every other one.
#:
#: 24 characters is above every stub seen (`点击查看原文>`, `阅读全文`, `Read more`) and below any
#: real lede -- the shortest genuine summary in the corpus is a 40-character sentence.
_MIN_IDENTIFYING_BODY = 24

#: Phrases that are a section label rather than a lede.
#:
#: Matched case-insensitively against the whole stripped body. Kept short and specific: a false
#: positive only means the title decides the fingerprint, which is the safer of the two errors --
#: the unsafe one is two different stories merging and the reader following a link to an article
#: the entry never described.
_BOILERPLATE_PHRASES = (
    "these are the stocks posting the largest moves",
    "this is a breaking news story",
    "read more",
    "click here",
    "subscribe to our newsletter",
    "sign up for our newsletter",
    "本文为转载",
    "点击查看原文",
    "阅读全文",
    "责任编辑",
)

#: A body that mostly repeats its own headline adds nothing to identity either: the headline
#: already identifies it, so hashing both is the same as hashing the headline.
#:
#: Measured on the same CNBC feed: the body of `Stocks making the biggest moves premarket:
#: CoreWeave, Rocket Lab` was one sentence naming no company, while four other entries shared it.


def _is_boilerplate(body: str, title: str) -> bool:
    """True when this body cannot tell one article from another.

    Two tests, both cheap and both conservative:

    * the body opens with a known section label, or
    * the body is almost entirely contained in the title, so it restates it.
    """
    text = body.strip().lower()
    if not text:
        return True

    for phrase in _BOILERPLATE_PHRASES:
        if text.startswith(phrase):
            return True

    # Strip the title from the body. Whatever is left is the part that is new information.
    folded_title = re.sub(r"[\W_]+", "", title.lower())
    folded_body = re.sub(r"[\W_]+", "", text)
    if folded_title and folded_body and folded_body in folded_title:
        return True
    return False


def normalize_raw(
    raw: RawItem, spec: SourceSpec, now: datetime | None = None
) -> NormalizedItem:
    now = now or datetime.now(timezone.utc)
    # Strip markup here rather than at render time: the text is passed to models, to the
    # dedup fingerprint and to the reader, and tag soup degrades all three.
    body = strip_html(raw.content_text or raw.summary or raw.title or "")
    # **A body too short to identify anything must not become the identity.**
    #
    # `content_sha256` is an exact dedup key with no time window (see `dedup.cluster`), so two
    # items with the same body are merged outright. Measured 2026-10-23: every InfoQ RSS entry
    # carries the same template summary, which strips to the six characters `点击查看原文>`. All
    # twelve of that day entries hashed identically, were merged into one unit, and the issue
    # published a single event whose headline was about API gateways while its facts listed Qwen
    # kernels, a DeepSeek funding round and a Huawei assistant review. The link the reader
    # clicked was one of the twelve, so it went to an article the entry never described.
    #
    # The fix is to stop deriving an identity from a body that carries none. Two shapes of
    # body carry none:
    #
    #   * too short -- `点击查看原文>` and friends (`_MIN_IDENTIFYING_BODY`),
    #   * boilerplate -- long enough to pass the length test but identical across unrelated
    #     articles. Measured on CNBC: 57 characters of "These are the stocks posting the
    #     largest moves premarket." sat under four different headlines naming different
    #     companies, so all four merged into one event about none of them.
    #
    # Both fall back to the title, so two items share a fingerprint only when they share a
    # headline -- which is what an exact key is for.
    title_body = strip_html(raw.title or "")
    if len(body) < _MIN_IDENTIFYING_BODY or _is_boilerplate(body, raw.title or ""):
        body_for_hash = title_body
    else:
        body_for_hash = body
    # Summary is display text: strip markup AND bare links so the digest never shows a
    # URL we did not record and verify ourselves.
    summary = strip_text_urls(strip_html(raw.summary or "", limit=2000))
    text_for_lang = f"{raw.title} {summary} {body[:200]}"
    return NormalizedItem(
        item_id=item_id_for(spec, raw),
        source_id=spec.source_id,
        title=strip_html(raw.title or "", limit=500),
        title_norm=title_norm(raw.title),
        url=raw.url,
        canonical_url=None,          # filled later only when a page is actually fetched
        published_at=raw.published_at,
        fetched_at=now,
        first_seen_at=now,
        updated_at=now,
        # Precedence: what the fetcher saw on the item, then what the source is
        # configured as, then a script heuristic. Relying on fetchers to copy
        # spec.language into every RawItem means one forgetful adapter silently
        # relabels a source.
        language=raw.language or spec.language or detect_language(text_for_lang),
        summary=summary,
        content_text=body or None,
        content_sha256=content_fingerprint(body_for_hash),
        simhash=simhash(body_for_hash),
        author=raw.author,
        metrics=raw.metrics or {},
        age_bucket=compute_age_bucket(
            raw.published_at, now.date(), window_source=spec.adapter in WINDOW_ADAPTERS
        ),
    )
