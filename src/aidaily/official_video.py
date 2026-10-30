"""The official video for a tutorial or demo story.

## Why

「Kimi 官方教程：如何用 Kimi K3.1 Pro 创作 3D 作品」 deserves the official walkthrough next to
it, not just a link to a blog post. The reader wants the demonstration; the text is the index.

## What counts as official

Two conditions, both cheap:

1. the video title names the same product as the story;
2. the uploader is a verified account whose name carries the product or its maker.

Anything else is somebody screen recording, and attaching it would put a stranger video under
this site headline. When neither check can be completed the story simply has no video --
the absence is honest, the wrong video is not.

## Cost

One search plus one profile lookup per candidate, at most a handful of candidates per issue,
each bounded by a short timeout. A failure is silent: the story publishes without a video.
"""

from __future__ import annotations

import asyncio
import re

#: Words that mark a story as something the reader would want *shown*.
TUTORIAL_HINTS = (
    "教程",
    "演示",
    "上手",
    "实操",
    "实战",
    "walkthrough",
    "tutorial",
    "demo",
    "how to",
)

#: Search endpoint. Public, no key -- the same one the site uses.
SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"

#: Verified-account lookup, so 「官方」 is checked rather than assumed.
PROFILE_URL = "https://api.bilibili.com/x/space/wbi/acc/info"

#: How much of this the issue is allowed to spend.
VIDEO_LOOKUP_LIMIT = 6
VIDEO_CONCURRENCY = 3
VIDEO_TIMEOUT_S = 6.0

_TAG = re.compile(r"<[^>]+>")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{2,}")


def wants_video(title: str) -> bool:
    """True when the headline suggests a demonstration rather than an announcement."""
    text = (title or "").lower()
    return any(hint in text for hint in TUTORIAL_HINTS)


def product_terms(title: str) -> set[str]:
    """The names a matching video has to mention."""
    terms = {w.lower().strip(".-") for w in _LATIN.findall(title or "")}
    return {t for t in terms if len(t) >= 3}


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


def pick_candidate(results: list, terms: set) -> dict | None:
    """The first result whose title names the same product.

    Uploader verification happens afterwards, one call, for this candidate only.
    """
    if not terms:
        return None
    for row in results or []:
        title = _clean(str(row.get("title") or "")).lower()
        if not title:
            continue
        if not any(term in title for term in terms):
            continue
        author = str(row.get("author") or "").lower()
        if not any(term in author for term in terms) and "官方" not in author:
            continue
        bvid = str(row.get("bvid") or "")
        if not bvid:
            continue
        return {
            "platform": "bilibili",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "title": _clean(str(row.get("title") or ""))[:80],
            "author": str(row.get("author") or "")[:40],
            "mid": row.get("mid"),
        }
    return None


async def _verified(client, mid) -> bool:
    if not mid:
        return False
    try:
        response = await client.get(
            PROFILE_URL, params={"mid": mid}, timeout=VIDEO_TIMEOUT_S
        )
        payload = response.json()
    except Exception:
        return False
    data = (payload or {}).get("data") or {}
    verify = data.get("official") or {}
    # role 0/1 are 个人认证 / 机构认证; anything else is not an official account.
    return int(verify.get("role", -1)) in (0, 1)


async def find_video(client, title: str) -> dict | None:
    """Search for, filter and verify one official video. None when nothing qualifies."""
    terms = product_terms(title)
    if not terms:
        return None
    try:
        response = await client.get(
            SEARCH_URL,
            params={"search_type": "video", "keyword": title[:40]},
            timeout=VIDEO_TIMEOUT_S,
        )
        payload = response.json()
    except Exception:
        return None
    rows = ((payload or {}).get("data") or {}).get("result") or []
    candidate = pick_candidate(rows, terms)
    if candidate is None:
        return None
    if not await _verified(client, candidate.get("mid")):
        return None
    return candidate


async def attach_official_videos(events, client, *, limit: int = VIDEO_LOOKUP_LIMIT) -> int:
    """Attach the verified video to each event that wants one.

    Returns how many were attached. Never raises.
    """
    targets = [e for e in events if wants_video(getattr(e, "title", ""))][:limit]
    if not targets:
        return 0

    sem = asyncio.Semaphore(VIDEO_CONCURRENCY)

    async def one(event) -> bool:
        async with sem:
            found = await find_video(client, event.title)
        if not found:
            return False
        # unique_facts is dict[str, list[str]] -- flat keys, not a nested object.
        facts = event.unique_facts if isinstance(event.unique_facts, dict) else {}
        facts["video_url"] = [found["url"]]
        facts["video_title"] = [found["title"]]
        facts["video_author"] = [found["author"]]
        event.unique_facts = facts
        return True

    results = await asyncio.gather(*(one(e) for e in targets), return_exceptions=True)
    return sum(1 for r in results if r is True)
