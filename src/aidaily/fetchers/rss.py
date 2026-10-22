"""RSS / Atom / JSON Feed fetcher.

Two details are load-bearing, both learned from real failures found during the audit:

1. **Parse bytes, never `response.text`.** `news.google.com/rss/search` declares
   `encoding="UTF-8"` and the bytes are in fact valid UTF-8, but any client that decodes
   with a guessed codepage (the Windows console and some proxies do) hands feedparser
   garbage and gets *zero* entries from a feed that has 100. feedparser reads the XML
   prolog itself when given bytes, which is authoritative.
2. **Never trust entry order.** `ainewslog.com` publishes oldest-first -- its own
   neighbouring project documents this ("Feed is ordered oldest-first ... never trust
   ordering"). We take the max timestamp, not `entries[0]`.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..digest_split import is_digest_feed, is_digest_title, split_digest
from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult


#: How far ahead of "now" a feed date may be before it is treated as a placeholder.
#:
#: Publishers do emit these: on 2026-10-19 the AllenAI feed dated four posts 2026-10-31, twelve
#: days ahead. Those items then failed the digest's own future_date check, and before that check
#: was made per-event they cost the entire day's issue.
#:
#: The tolerance is generous on purpose: timezone sloppiness routinely puts an item a few hours
#: into the future, and that is harmless.
_MAX_FUTURE_SKEW = timedelta(hours=36)


def _entry_datetime(entry: dict) -> datetime | None:
    """Earliest trustworthy date for an entry, or None -- never the fetch time.

    A date more than _MAX_FUTURE_SKEW ahead of now is a placeholder, not a publication date.
    Returning None is the honest answer: the item has no usable date, and callers already treat
    a missing date as "cannot be proven new" rather than inventing one.
    """
    now = datetime.now(timezone.utc)
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                when = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
            if when - now > _MAX_FUTURE_SKEW:
                continue
            return when
    return None


def _entry_content(entry: dict) -> str:
    """Fullest available body. `content` is richer than `summary` when present."""
    blocks = entry.get("content") or []
    if blocks:
        value = blocks[0].get("value")
        if value:
            return str(value)
    for key in ("summary", "description"):
        if entry.get(key):
            return str(entry[key])
    return ""


def _entry_id(entry: dict, link: str) -> str:
    raw = entry.get("id") or entry.get("guid") or link
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()[:16]


class RssFetcher(BaseFetcher):
    """Handles source_type rss, atom and jsonfeed."""

    name = "RssFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        # The source's own timeout, not the client default: a Chinese host can take two
        # minutes on a GitHub runner while the client allows 30s per attempt.
        res = await self.http.get(spec.url, timeout_s=getattr(spec, "timeout_s", None) or None)
        base = self.from_http(spec, res)
        if not base.ok:
            return base
        if res.verdict == "not_modified":
            return base

        if spec.source_type == "jsonfeed":
            items = self._parse_jsonfeed(spec, res.body)
        else:
            items = self._parse_feed(spec, res.body)
        base.items = items
        return base

    # --- XML feeds ---------------------------------------------------------------
    def _parse_feed(self, spec: SourceSpec, body: bytes) -> list[RawItem]:
        import feedparser

        feed = feedparser.parse(body)      # bytes: the XML prolog is authoritative
        params = spec.params or {}
        out: list[RawItem] = []
        for entry in feed.entries:
            link = entry.get("link") or ""
            if not link and not entry.get("title"):
                continue
            published = _entry_datetime(entry)
            title = (entry.get("title") or "").strip()
            body = _entry_content(entry)

            # **A digest issue is not a story; it is a container of stories.**
            #
            # `AI 早报 2026-10-22` arrives as one entry whose body lists thirty stories. Kept whole
            # it is filtered as a roundup and every story inside is lost; the page then shows a
            # digest link rather than the publisher it came from. Split it and each story becomes
            # its own candidate carrying the ORIGINAL publisher URL.
            #
            # `max_items_per_digest` bounds the fan-out: one weekly issue can carry forty stories,
            # and letting all of them in at once would drown that day in one source.
            if is_digest_feed(spec.url) and is_digest_title(title):
                split = split_digest(body)
                limit = int(params.get("max_items_per_digest") or 60)
                for story in split[:limit]:
                    out.append(
                        RawItem(
                            source_id=spec.source_id,
                            title=story.title,
                            url=story.url,
                            published_at=published,
                            summary=story.summary or "",
                            content_text=None,
                            author=None,
                            language=spec.language,
                            # The section travels with the story: it is the digest author's own
                            # judgement and a useful prior when this project has none.
                            metrics={"digest_section": story.section, "digest_title": title[:120]},
                            native_id=f"{_entry_id(entry, link)}#{story.url}",
                        )
                    )
                if split:
                    continue
                # Unrecognised layout: fall through and keep the item whole rather than
                # dropping the issue entirely.

            out.append(
                RawItem(
                    source_id=spec.source_id,
                    title=title,
                    url=link,
                    published_at=published,
                    summary=(entry.get("summary") or "").strip()[:2000],
                    content_text=body[:200_000] or None,
                    author=entry.get("author") or None,
                    language=spec.language,
                    metrics={"tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")][:8]},
                    native_id=_entry_id(entry, link),
                )
            )
        return out

    # --- JSON Feed -----------------------------------------------------------------
    def _parse_jsonfeed(self, spec: SourceSpec, body: bytes) -> list[RawItem]:
        try:
            doc = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return []
        out: list[RawItem] = []
        for item in doc.get("items") or []:
            link = item.get("url") or item.get("external_url") or item.get("id") or ""
            title = (item.get("title") or "").strip()
            if not link and not title:
                continue
            published = _parse_iso(item.get("date_published") or item.get("date_modified"))
            content = item.get("content_html") or item.get("content_text") or item.get("summary") or ""
            out.append(
                RawItem(
                    source_id=spec.source_id,
                    title=title,
                    url=link,
                    published_at=published,
                    summary=(item.get("summary") or "").strip()[:2000],
                    content_text=str(content)[:200_000] or None,
                    author=(item.get("author") or {}).get("name") if isinstance(item.get("author"), dict) else None,
                    language=spec.language,
                    metrics={"tags": (item.get("tags") or [])[:8]},
                    native_id=hashlib.sha256(str(item.get("id") or link).encode()).hexdigest()[:16],
                )
            )
        return out


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
