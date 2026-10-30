"""Credit the publisher, not the aggregator.

Measured 2026-10-30: position #02 rendered as 「单一来源 news.google.com」 for an article that is
actually https://tech.ifeng.com/c/8xdpukAXGMN. The link went through an aggregator and the byline
credited the wrong publisher.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.resolve_links import needs_resolution, resolve_events

NOW = datetime.now(timezone.utc)


class _Resp:
    def __init__(self, url: str) -> None:
        self.url = url


class _Client:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.calls = 0

    async def get(self, url, **kwargs):
        self.calls += 1
        target = self.mapping.get(url)
        if target is None:
            raise RuntimeError("boom")
        return _Resp(target)


class _BadClient:
    async def get(self, url, **kwargs):
        raise RuntimeError("network down")


def _event(event_id: str, *urls: str) -> Event:
    return Event(
        event_id=event_id,
        title="t",
        member_item_ids=[event_id],
        primary_item_id=event_id,
        source_ids=["api:news-google-com-search"],
        all_urls=list(urls),
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


GOOGLE = "https://news.google.com/rss/articles/CBMiX"
IFENG = "https://tech.ifeng.com/c/8xdpukAXGMN"


def test_only_aggregator_links_need_resolving() -> None:
    assert needs_resolution(GOOGLE)
    assert not needs_resolution(IFENG)


def test_a_redirect_is_replaced_in_place() -> None:
    event = _event("a", GOOGLE)
    resolved = asyncio.run(resolve_events([event], _Client({GOOGLE: IFENG})))
    assert resolved == 1
    assert event.all_urls == [IFENG]


def test_a_direct_link_is_left_alone() -> None:
    event = _event("a", IFENG)
    count = asyncio.run(resolve_events([event], _Client({})))
    assert count == 0
    assert event.all_urls == [IFENG]


def test_a_failure_keeps_the_original_url() -> None:
    """An unresolved link is a smaller defect than a broken one."""
    event = _event("a", GOOGLE)
    count = asyncio.run(resolve_events([event], _BadClient()))
    assert count == 0
    assert event.all_urls == [GOOGLE]


def test_a_redirect_into_the_aggregator_is_refused() -> None:
    event = _event("a", GOOGLE)
    count = asyncio.run(resolve_events([event], _Client({GOOGLE: GOOGLE + "2"})))
    assert count == 0