"""Turn a Google News redirect into the publisher it points at.

## The problem

`api:news-google-com-search` returns `news.google.com/rss/articles/CBMi...` links. The page
showed one of them as a story whose source was 「news.google.com」 -- while the article was, in
fact, from 凤凰网. Two things go wrong: the link takes the reader through an aggregator, and the
byline credits the wrong publisher.

Measured 2026-10-30, position #02: 中国首个 AI 定义芯片诞生, credited to news.google.com, actually
https://tech.ifeng.com/c/8xdpukAXGMN.

## The approach

One HEAD request per unresolved link, following redirects, bounded in count, concurrency and
time. A failure leaves the original URL alone -- an unresolved link is a smaller defect than a
broken one.
"""

from __future__ import annotations

import asyncio

#: Only links from this host are worth resolving.
GOOGLE_NEWS_HOST = "news.google.com"

#: How many links to resolve per issue, and how hard to try.
RESOLVE_LIMIT = 60
RESOLVE_CONCURRENCY = 10
RESOLVE_TIMEOUT_S = 8.0


def needs_resolution(url: str) -> bool:
    """True when the link still points at the aggregator."""
    return GOOGLE_NEWS_HOST in (url or "")


async def resolve_one(client, url: str) -> str | None:
    """Follow one redirect and return the final URL, or None when it cannot be resolved."""
    try:
        response = await client.get(url, follow_redirects=True, timeout=RESOLVE_TIMEOUT_S)
    except Exception:
        return None
    final = str(getattr(response, "url", "") or "")
    if not final or final == url or needs_resolution(final):
        return None
    return final


async def resolve_events(events, client, *, limit: int = RESOLVE_LIMIT) -> int:
    """Rewrite Google News links in place. Returns how many were resolved.

    Only the *first* link of each event is resolved: that is the one the card links to and the
    one the byline prints. Resolving every URL would multiply the cost for no visible gain.
    """
    targets = []
    for event in events:
        urls = list(getattr(event, "all_urls", None) or [])
        if not urls:
            continue
        if not any(needs_resolution(u) for u in urls):
            continue
        targets.append(event)
        if len(targets) >= limit:
            break

    if not targets:
        return 0

    sem = asyncio.Semaphore(RESOLVE_CONCURRENCY)

    async def one(event) -> bool:
        urls = list(event.all_urls or [])
        for index, url in enumerate(urls):
            if not needs_resolution(url):
                continue
            async with sem:
                resolved = await resolve_one(client, url)
            if resolved:
                urls[index] = resolved
                event.all_urls = urls
                return True
            return False
        return False

    results = await asyncio.gather(*(one(e) for e in targets), return_exceptions=True)
    return sum(1 for r in results if r is True)
