"""Collapsing duplicate releases must not erase the ranking components.

`rank_events` merges the several phrasings of one launch into a single row. The first version
of that merge returned `RankedEvent(..., components={})` for the survivor, which wiped the
`focus` component -- the AI-relevance score.

`select_for_digest` then rejected every row as `missing_or_invalid_focus`, because a missing
score fails closed by design. On 2026-10-19 that published **0 of 220 events** while the
headlines were unmistakably AI ("MiniMax 将发布 M3.1-Flash", "DeepSeek上新AI模型"). The run was
green; the page was empty.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.models import Event, NormalizedItem, SourceSpec
from aidaily.rank import rank_events

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


def _item(item_id: str, title: str) -> NormalizedItem:
    return NormalizedItem(
        item_id=item_id,
        source_id="rss:a",
        title=title,
        title_norm=title.lower(),
        url="https://example.com/" + item_id,
        content="x" * 400,
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        published_at=NOW - timedelta(hours=2),
        content_sha256="0" * 64,
        simhash=0,
    )


def _event(event_id: str, title: str, url: str) -> Event:
    return Event(
        event_id=event_id,
        primary_item_id=event_id + "-i",
        title=title,
        member_item_ids=[event_id + "-i"],
        source_ids=["rss:a"],
        all_urls=[url],
        first_seen_at=NOW - timedelta(hours=2),
        last_updated_at=NOW,
        independent_source_count=1,
    )


def _source() -> SourceSpec:
    return SourceSpec(
        source_id="rss:a",
        name="A",
        url="https://example.com/feed",
        normalized_url="https://example.com/feed",
        domain="example.com",
        source_type="rss",
        category="media",
        language="en",
    )


def test_collapsing_keeps_the_focus_component() -> None:
    """Two phrasings of one release merge, and the survivor still carries `focus`."""
    titles = [
        "DeepSeek 发布 V4.1-Flash-1017",
        "deepseek-v4.1-flash-1017 发布了",
    ]
    items = [_item("i%d" % i, t) for i, t in enumerate(titles)]
    events = [_event("e%d" % i, t, "https://example.com/s%d" % i) for i, t in enumerate(titles)]

    ranked = rank_events(events, items, [_source()], now=NOW)

    assert len(ranked) == 1, "the two phrasings did not merge"
    assert ranked[0].components, "components were wiped by the merge"
    assert "focus" in ranked[0].components, ranked[0].components


def test_the_merged_row_keeps_a_usable_score() -> None:
    ranked = rank_events(
        [
            _event("e0", "DeepSeek 发布 V4.1-Flash-1017", "https://example.com/s0"),
            _event("e1", "deepseek-v4.1-flash-1017 发布了", "https://example.com/s1"),
        ],
        [_item("i0", "DeepSeek 发布 V4.1-Flash-1017"), _item("i1", "deepseek-v4.1-flash-1017 发布了")],
        [_source()],
        now=NOW,
    )
    assert ranked[0].score > 0, "the surviving row lost its score"
