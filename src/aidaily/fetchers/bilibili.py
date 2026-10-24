"""Bilibili hot-search as a digest source, filtered to AI.

## Why a dedicated fetcher

Bilibili publishes no RSS. Its hot-search list is a JSON endpoint, and the shape is stable
enough to read directly; routing it through the generic JSON fetcher would mean encoding a
nested path (`data.trending.list`) it does not know about.

## Why the filter lives here and not downstream

Measured 2026-10-24: of the 50 hot searches, exactly one was about AI -- `Kimi K3.1 Pro发布`
-- and the other 49 were esports results, variety shows and food videos. That is the normal
ratio, not a bad day: Bilibili is an entertainment platform and its trending list is mostly
entertainment.

The existing `focus` scorer rejected all 49 and kept the one, so this fetcher applies it at
collection time. Dropping here rather than at selection means the pipeline never spends a
cluster, a model call or a slot on 电竞赛果.

## What a row carries

`heat_score` is Bilibili own ranking weight, kept so the digest can show how big the topic was
on that platform. No publication time exists -- a hot search is a live window, like GitHub
Trending -- so `published_at` stays None and the pipeline treats it as unknown freshness.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..focus import focus_multiplier
from ..models import Event, RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

#: The hot-search endpoint. `limit` caps the returned rows; 50 is what the site itself shows.
HOT_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/square?limit=50"

#: Sent with every request. Bilibili rejects the default Python user agent, and the Referer
#: is what the site own pages send -- without it the endpoint sometimes answers 412.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json",
}


class BilibiliHotFetcher(BaseFetcher):
    name = "BilibiliHotFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        res = await self.http.get(
            HOT_SEARCH_URL, timeout_s=getattr(spec, "timeout_s", None) or None
        )
        base = self.from_http(spec, res)
        if not base.ok or res.verdict == "not_modified":
            return base
        base.items = self._parse(spec, res.text)
        return base

    def _parse(self, spec: SourceSpec, text: str) -> list[RawItem]:
        """Rows that are about AI. Never raises: a shape change costs the source, not the run."""
        import json

        try:
            payload = json.loads(text)
        except ValueError:
            return []

        rows = (
            ((payload or {}).get("data") or {}).get("trending") or {}
        ).get("list") or []

        now = datetime.now(timezone.utc)
        out: list[RawItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            keyword = str(row.get("keyword") or "").strip()
            shown = str(row.get("show_name") or "").strip()
            if not keyword and not shown:
                continue
            # Both fields can carry information: `GEN IG` plus `GEN战胜IG S16瑞士轮`. The
            # focus scorer needs the descriptive one, so both are joined for the judgement
            # and the more informative one becomes the title.
            title = shown or keyword
            if shown and keyword and keyword not in shown:
                title = f"{shown}（{keyword}）"

            probe = Event(
                event_id="probe",
                title=f"{keyword} {shown}".strip(),
                member_item_ids=[],
                primary_item_id="",
                source_ids=[],
                all_urls=[],
                first_seen_at=now,
                last_updated_at=now,
            )
            _multiplier, components = focus_multiplier(probe)
            if not (components.get("focus") or 0) >= 0.6:
                continue

            heat = row.get("heat_score")
            out.append(
                RawItem(
                    source_id=spec.source_id,
                    title=title[:200],
                    url=f"https://search.bilibili.com/all?keyword={keyword or shown}",
                    published_at=None,  # a hot search is a live window, not a publication
                    summary=shown[:500],
                    content_text=None,
                    language="zh",
                    metrics={
                        "heat_score": heat if isinstance(heat, (int, float)) else None,
                        "platform": "bilibili",
                        "keyword": keyword,
                    },
                    native_id=keyword or shown,
                )
            )
        return out
