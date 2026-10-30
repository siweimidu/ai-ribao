"""The official walkthrough for a tutorial story, verified rather than assumed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.official_video import (
    attach_official_videos,
    find_video,
    pick_candidate,
    product_terms,
    wants_video,
)

NOW = datetime.now(timezone.utc)


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, search_rows, role=1):
        self.search_rows = search_rows
        self.role = role

    async def get(self, url, **kwargs):
        if "search" in url:
            return _Resp({"data": {"result": self.search_rows}})
        return _Resp({"data": {"official": {"role": self.role}}})


ROWS = [
    {
        "title": "<em>Kimi</em> 的 3D 创作，有几种玩法？",
        "author": "Kimi官方",
        "bvid": "BV1xx411c7mD",
        "mid": 123,
    }
]


def _event(title: str) -> Event:
    return Event(
        event_id="e",
        title=title,
        member_item_ids=["m"],
        primary_item_id="m",
        source_ids=["rss:x"],
        all_urls=["https://example.com/a"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_a_tutorial_wants_a_video_and_an_announcement_does_not() -> None:
    assert wants_video("Kimi 官方教程：如何用 Kimi K3.1 Pro 创作 3D 作品")
    assert not wants_video("OpenAI 发布 GPT-6.1 Terra")


def test_the_product_terms_come_from_the_headline() -> None:
    assert {"kimi", "k3.1", "pro"} <= product_terms("Kimi 官方教程：如何用 Kimi K3.1 Pro 创作 3D 作品")


def test_a_candidate_must_name_the_product_in_title_and_uploader() -> None:
    terms = product_terms("Kimi 官方教程：Kimi K3.1 Pro")
    chosen = pick_candidate(ROWS, terms)
    assert chosen is not None
    assert chosen["url"] == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert chosen["title"] == "Kimi 的 3D 创作，有几种玩法？"


def test_a_stranger_upload_is_rejected() -> None:
    rows = [{"title": "Kimi 教程", "author": "某个搬运号", "bvid": "BV1", "mid": 9}]
    assert pick_candidate(rows, {"kimi"}) is None


def test_a_verified_account_is_required() -> None:
    verified = asyncio.run(find_video(_Client(ROWS, role=1), "Kimi 官方教程：K3.1 Pro"))
    assert verified is not None
    unverified = asyncio.run(find_video(_Client(ROWS, role=-1), "Kimi 官方教程：K3.1 Pro"))
    assert unverified is None


def test_attachment_lands_in_unique_facts() -> None:
    event = _event("Kimi 官方教程：如何用 Kimi K3.1 Pro 创作 3D 作品")
    count = asyncio.run(attach_official_videos([event], _Client(ROWS)))
    assert count == 1
    # unique_facts is dict[str, list[str]]; the video lives in flat keys.
    assert event.unique_facts["video_url"] == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert event.unique_facts["video_author"] == ["Kimi官方"]


def test_a_story_that_does_not_want_a_video_is_skipped() -> None:
    event = _event("OpenAI 发布 GPT-6.1 Terra")
    assert asyncio.run(attach_official_videos([event], _Client(ROWS))) == 0