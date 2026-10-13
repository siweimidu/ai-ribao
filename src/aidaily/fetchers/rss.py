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
from datetime import datetime, timezone

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult


def _entry_datetime(entry: dict) -> datetime | None:
    """Earliest trustworthy date for an entry, or None -- never the fetch time."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
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
        res = await self.http.get(spec.url)
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
        out: list[RawItem] = []
        for entry in feed.entries:
            link = entry.get("link") or ""
            if not link and not entry.get("title"):
                continue
            published = _entry_datetime(entry)
            out.append(
                RawItem(
                    source_id=spec.source_id,
                    title=(entry.get("title") or "").strip(),
                    url=link,
                    published_at=published,
                    summary=(entry.get("summary") or "").strip()[:2000],
                    content_text=_entry_content(entry)[:200_000] or None,
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
