"""Fetch an X (Twitter) account timeline without an API key.

## Why this endpoint

X's own "embed a timeline" widget calls

    https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>

which answers with a server-rendered page whose `__NEXT_DATA__` script holds the tweet objects:
text, timestamp, like and retweet counts, media URLs, and the status id. It is not the public API
and needs no token -- it exists so that third-party pages can show someone else's timeline.

Measured 2026-10-21: 10 handles returned 525 tweets in 40 seconds, including 99-101 entries for
high-volume accounts. Every alternative was dead or account-bound:

* Nitter instances -- 410 Gone, 451, TLS failures; the public network is effectively gone.
* RSSHub's `/twitter/user` route -- needs `TWITTER_AUTH_TOKEN`, i.e. a **logged-in cookie from
  the reader's own account**, and its own docs say the password method "easily triggers Twitter's
  risk control mechanism" and stopped working in October 2025.
* X API v2 -- 401 without a paid plan.

## The rate limit is real and must be respected

Measured the hard way: ~30 requests with a 0.6s gap produced 429 on every one, and the block
outlasted 10-second gaps for several minutes. The endpoint is therefore fetched with a *slow*
per-request delay and a small number of handles per run; a 429 is reported as `blocked` so the
next run tries again rather than the source silently vanishing.

## What a tweet becomes

One `RawItem` per tweet. `title` is the first line (the digest needs a headline), `content_text`
is the full text, and `url` is the canonical `https://x.com/<handle>/status/<id>` -- built from
the status id, never guessed.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

#: The `__NEXT_DATA__` JSON blob every syndication page carries.
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>'
)

#: X's own timestamp format: `Wed Oct 07 18:05:04 +0000 2026`.
_TS = "%a %b %d %H:%M:%S %z %Y"


def _handle(spec: SourceSpec) -> str:
    """The screen name this source points at.

    Accepts either a full profile URL or a bare handle, because both spellings are natural when
    a source is added by hand.
    """
    raw = (spec.url or "").strip()
    m = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", raw)
    if m:
        return m.group(1)
    return raw.lstrip("@").split("/")[0]


def _parse_entries(payload: dict) -> list[dict]:
    """The tweet objects out of a syndication page."""
    timeline = (
        payload.get("props", {}).get("pageProps", {}).get("timeline", {})
    )
    entries = timeline.get("entries") or []
    out: list[dict] = []
    for entry in entries:
        tweet = (entry.get("content") or {}).get("tweet")
        if tweet:
            out.append(tweet)
    return out


def _when(tweet: dict) -> datetime | None:
    raw = tweet.get("created_at") or ""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _TS).astimezone(timezone.utc)
    except ValueError:
        return None


def _headline(text: str) -> str:
    """First non-empty line, trimmed to something a digest can print.

    A tweet has no title. Using the whole text as one would make every entry a paragraph in the
    list; using the first sentence keeps the shape of the page intact.
    """
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:160]
    return text.strip()[:160]


def to_items(spec: SourceSpec, tweets: list[dict]) -> list[RawItem]:
    """Turn tweet objects into `RawItem`s. Pure, so the parsing is testable offline."""
    handle = _handle(spec)
    out: list[RawItem] = []
    for tweet in tweets:
        text = (tweet.get("full_text") or tweet.get("text") or "").strip()
        status_id = tweet.get("id_str") or ""
        if not text or not status_id:
            continue
        url = f"https://x.com/{handle}/status/{status_id}"
        media = (tweet.get("entities") or {}).get("media") or []
        out.append(
            RawItem(
                source_id=spec.source_id,
                title=_headline(text),
                url=url,
                published_at=_when(tweet),
                summary=text[:2000],
                content_text=text[:20_000],
                author=tweet.get("user", {}).get("screen_name") or handle,
                language=spec.language,
                metrics={
                    "likes": tweet.get("favorite_count"),
                    "retweets": tweet.get("retweet_count"),
                    "replies": tweet.get("reply_count"),
                    "media": len(media),
                },
                native_id=status_id,
            )
        )
    return out


#: Serialises every X request in the process.
#:
#: The endpoint rate-limits the aggregate, so ten concurrent fetches -- one per source --
#: all fail. A lock plus the per-request gap keeps the whole run inside the budget.
_ENDPOINT_LOCK = asyncio.Lock()


from pathlib import Path
p = Path("src/aidaily/fetchers/x_timeline.py")
s = p.read_text(encoding="utf-8")

# Measured on GitHub Actions 2026-10-21 with 26 X sources, serialised behind the lock:
#
#   x:chatgpt 101 · x:aiatmeta 100 · x:deepseek_ai 99 · x:alibaba_qwen 21 · x:anthropicai 20
#   x:baidu_inc 20   -- then 20 sources in a row came back 429.
#
# So the endpoint's budget is roughly **six fetches per window**, not six per handle. A run that
# tries all 26 spends most of them on 429s and starves the rest of the collect.
#
# The budget is spent on the accounts most likely to have news, and the rest rotate in on later
# runs. `_BUDGET` is a module-level counter reset at the start of each process.
_BUDGET = 6
_spent = 0


#: Where the rotation cursor is kept between runs.
_CURSOR_FILE = "x-rotation.json"


def _cursor_path():
    from pathlib import Path

    return Path("data") / "state" / _CURSOR_FILE


def load_cursor() -> int:
    """How many accounts have been served so far, across runs."""
    try:
        import json as _json

        return int(_json.loads(_cursor_path().read_text(encoding="utf-8")).get("offset", 0))
    except Exception:  # noqa: BLE001 - a missing or corrupt cursor restarts the cycle
        return 0


def save_cursor(offset: int) -> None:
    """Remember the rotation position. Best effort: losing it only re-shuffles the order."""
    try:
        import json as _json

        path = _cursor_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"offset": offset}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _take_budget() -> bool:
    """Whether this process may spend one more X request.

    The limit is per process (one collect run), because that is the granularity the endpoint
    measures. Returning False keeps the source `skipped` rather than `blocked`: nothing went
    wrong, we simply did not ask.
    """
    global _spent
    if _spent >= _BUDGET:
        return False
    _spent += 1
    return True


def reset_budget() -> None:
    """Called at the start of a collect run so tests and repeated runs start clean."""
    global _spent
    _spent = 0


class XTimelineFetcher(BaseFetcher):
    """Handles source_type `x_timeline`."""

    name = "XTimelineFetcher"

    #: Seconds between requests. See the module docstring: 0.6s earned a 429 on every call.
    request_gap_s: float = 6.0

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        handle = _handle(spec)
        if not handle:
            return SourceResult(spec.source_id, "skipped", detail="no handle in url")

        url = (
            "https://syndication.twitter.com/srv/timeline-profile/screen-name/"
            + handle
        )
        # Spend from the per-run budget first: once it is gone, further requests only produce
        # 429s and delay the rest of the collect.
        if not _take_budget():
            return SourceResult(
                spec.source_id, "skipped",
                detail=f"X budget spent for this run ({_BUDGET} requests)",
            )

        # One at a time, gap included. See `_ENDPOINT_LOCK`.
        async with _ENDPOINT_LOCK:
            await asyncio.sleep(self.request_gap_s)
            res = await self.http.get(
                url,
                timeout_s=getattr(spec, "timeout_s", None) or 30,
                retries=0,
            )
        if res.status == 429:
            return SourceResult(
                spec.source_id, "blocked", detail="HTTP 429 from syndication endpoint", status=429
            )
        base = self.from_http(spec, res)
        if not base.ok or res.verdict == "not_modified":
            return base

        match = _NEXT_DATA.search(res.body.decode("utf-8", "replace"))
        if not match:
            return SourceResult(
                spec.source_id, "empty",
                detail="no __NEXT_DATA__; the page shape changed",
            )

        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            return SourceResult(spec.source_id, "empty", detail=f"bad __NEXT_DATA__: {exc}"[:120])

        tweets = _parse_entries(payload)
        base.items = to_items(spec, tweets)
        if not base.items:
            base.verdict = "empty"
            base.detail = f"{len(tweets)} tweet objects, none usable"
        return base


def plan_run(all_source_ids: list[str], *, budget: int = _BUDGET) -> list[str]:
    """Which X sources this run should fetch, rotating across runs.

    With 26 accounts and a six-request budget, a fixed order starves the last twenty forever.
    The cursor records how many were served so far; the window wraps around, so five runs cover
    everyone.

    Deterministic given the cursor: the ids are sorted first, so the same cursor always yields
    the same plan.
    """
    ids = sorted(all_source_ids)
    if not ids:
        return []
    offset = load_cursor() % len(ids)
    window = [ids[(offset + i) % len(ids)] for i in range(min(budget, len(ids)))]
    return window


def advance_cursor(total: int, served: int) -> None:
    """Move the cursor past the accounts this run served."""
    if total <= 0:
        return
    save_cursor((load_cursor() + served) % total)