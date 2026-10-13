"""Reddit fetcher: reads old.reddit.com HTML instead of the JSON API.

Measured on 2026-10-13 from this machine, against the live endpoints:

    reddit.com/r/{programming,startups,LocalLLaMA,...}/top.json   -> HTTP 403 Blocked  (12/12)
    old.reddit.com/r/{MachineLearning,LocalLLaMA,artificial}/hot/ -> HTTP 200 healthy  (3/3)

So the registry keeps the audited JSON URL (a URL is evidence and is never rewritten by
an override), and this adapter performs the translation at fetch time. If Reddit ever
restores anonymous JSON, `fetch_method` in sources/overrides.yaml flips back to
`httpx_json` and nothing else changes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

# /r/<sub>/top.json?t=day&limit=15   ->   old.reddit.com/r/<sub>/top/?t=day
_REDDIT_JSON_RE = re.compile(r"^/r/(?P<sub>[A-Za-z0-9_]+)/(?P<sort>top|hot|new|rising)\.json$")


def json_url_to_html(url: str) -> str | None:
    """Map an audited Reddit JSON endpoint to its old.reddit.com HTML equivalent.

    Returns None when the URL is not a recognised Reddit listing, so the caller can
    fall back to the URL as-is rather than silently fetching something wrong.
    """
    parts = urlsplit(url)
    if not parts.hostname or not parts.hostname.endswith("reddit.com"):
        return None
    m = _REDDIT_JSON_RE.match(parts.path or "")
    if not m:
        return None
    query = parts.query or ""
    return f"https://old.reddit.com/r/{m.group('sub')}/{m.group('sort')}/" + (f"?{query}" if query else "")


def detect_login_wall(html: str) -> str | None:
    """Return a reason when the response is an access wall rather than a listing.

    HTTP status alone is misleading here: measured 2026-10-13, `old.reddit.com` answers
    **200** with a 330 KB login page. Any health check that only looks at status and body
    size calls that "healthy" -- which is exactly the false positive the first probe run
    produced. Content sanity checks are the only reliable signal.
    """
    head = html[:30_000].lower()
    # A genuine listing first: never call real content a wall.
    if 'data-fullname="t3_' in html or "shreddit-post" in head or 'class="thing' in html:
        return None
    if "/login/" in head and "lor2" in head:
        return "old.reddit.com 要求登录（reason=lor2），匿名访问已关闭"
    if "whoa there" in head or "you've been blocked" in head or "are you a robot" in head:
        return "Reddit 返回反爬拦截页"
    if "captcha" in head:
        return "Reddit 返回验证码页"
    return "页面不含任何帖子结构（疑似访问墙或页面改版）"


class RedditFetcher(BaseFetcher):
    name = "RedditFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        url = json_url_to_html(spec.url) or spec.url
        res = await self.http.get(url)
        base = self.from_http(spec, res)
        base.detail = f"{base.detail} [via {url}]".strip()
        if not base.ok or res.verdict == "not_modified":
            return base

        html = res.text
        wall = detect_login_wall(html)
        if wall:
            # Measured 2026-10-13: old.reddit.com 302s to
            # /login/?reason=lor2&dest=... and serves a 330 KB login page with HTTP 200.
            # Reporting this as "ok, 0 items" would look like a quiet feed; it is an
            # access denial and needs a different fix (OAuth).
            return SourceResult(
                spec.source_id, "blocked", [], f"{wall} [via {url}]", res.status
            )

        base.items = self._parse_listing(spec, html)
        return base

    def _parse_listing(self, spec: SourceSpec, html: str) -> list[RawItem]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        out: list[RawItem] = []

        for thing in soup.select("div.thing[data-fullname]"):
            title_el = thing.select_one("a.title")
            if title_el is None:
                continue
            title = title_el.get_text(strip=True)
            link = thing.get("data-url") or title_el.get("href") or ""
            if link.startswith("/"):
                link = "https://old.reddit.com" + link

            published = None
            if ts := thing.get("data-timestamp"):
                try:
                    published = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                except (TypeError, ValueError):
                    published = None
            if published is None:
                time_el = thing.select_one("time[datetime]")
                if time_el is not None:
                    published = _iso(time_el.get("datetime"))

            def _int(attr: str) -> int:
                try:
                    return int(thing.get(attr) or 0)
                except (TypeError, ValueError):
                    return 0

            out.append(
                RawItem(
                    source_id=spec.source_id,
                    title=title,
                    url=link,
                    published_at=published,
                    summary="",
                    content_text=None,
                    author=thing.get("data-author") or None,
                    language=spec.language,
                    metrics={
                        "score": _int("data-score"),
                        "comments": _int("data-comments-count"),
                        "subreddit": thing.get("data-subreddit") or "",
                        "permalink": "https://old.reddit.com" + (thing.get("data-permalink") or ""),
                        "nsfw": thing.get("data-nsfw") == "true",
                    },
                    native_id=thing.get("data-fullname") or None,
                )
            )
        return out


def _iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
