"""A verified official video lifts a tutorial into the reader line of sight."""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.rank import (
    OFFICIAL_PROMOTE_AFTER,
    OFFICIAL_PROMOTE_LIMIT,
    has_official_video,
    promote_official_videos,
)

NOW = datetime.now(timezone.utc)


def _event(event_id: str, video: bool = False) -> Event:
    facts = {}
    if video:
        facts = {
            "video_url": ["https://b23.tv/x"],
            "video_title": ["演示"],
            "video_author": ["Kimi官方"],
        }
    return Event(
        event_id=event_id,
        title=f"t{event_id}",
        member_item_ids=[event_id],
        primary_item_id=event_id,
        source_ids=["rss:x"],
        all_urls=["https://example.com/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
        unique_facts=facts,
    )


def test_an_event_without_a_video_has_none() -> None:
    assert not has_official_video(_event("a"))
    assert has_official_video(_event("a", video=True))


def test_the_video_story_moves_up_but_not_to_the_very_top() -> None:
    rows = [_event(str(i)) for i in range(10)]
    rows.append(_event("tut", video=True))
    out = promote_official_videos(rows)
    assert out[0].event_id == "0"
    assert out[OFFICIAL_PROMOTE_AFTER].event_id == "tut"


def test_the_leading_news_keeps_its_place() -> None:
    rows = [_event(str(i)) for i in range(10)]
    rows.append(_event("tut", video=True))
    out = promote_official_videos(rows)
    assert [e.event_id for e in out[:OFFICIAL_PROMOTE_AFTER]] == ["0", "1", "2"]


def test_the_lift_is_capped() -> None:
    rows = [_event(str(i)) for i in range(10)]
    rows += [_event(f"tut{i}", video=True) for i in range(10)]
    out = promote_official_videos(rows)
    promoted = [e for e in out if e.event_id.startswith("tut")]
    assert len(promoted) == 10
    assert len(out) == 20
    first_block = out[OFFICIAL_PROMOTE_AFTER:OFFICIAL_PROMOTE_AFTER + OFFICIAL_PROMOTE_LIMIT]
    assert all(e.event_id.startswith("tut") for e in first_block)


def test_nothing_changes_without_a_video() -> None:
    rows = [_event(str(i)) for i in range(5)]
    assert [e.event_id for e in promote_official_videos(rows)] == ["0", "1", "2", "3", "4"]


def test_the_limits_are_bounded() -> None:
    assert 0 < OFFICIAL_PROMOTE_LIMIT <= 10
    assert OFFICIAL_PROMOTE_AFTER >= 1