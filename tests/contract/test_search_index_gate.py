"""A search-engine hit with no second outlet is not the day news.

Measured 2026-10-29: the issue published at #80

    再度嫌弃“AI” 川普宣布全面禁用 都要改称“SI” - 文学城

single source `api:news-google-com-search`, one Google News redirect URL, published_range
`2026-10-28T20:00:48Z` -- and readers had already seen the story the day before.

Google News re-dates an article when it re-indexes it, so the calendar-date rule cannot trust
that field. The feed is not removed: its items still publish when another outlet carries the
same event, because that second outlet is what makes the date credible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.pipeline import SEARCH_INDEX_SOURCES, _uncorroborated_search_hit

NOW = datetime.now(timezone.utc)


def _event(*sources: str) -> Event:
    return Event(
        event_id="e",
        title="川普宣布全面禁用 AI 并改称 SI",
        member_item_ids=["m"],
        primary_item_id="m",
        source_ids=list(sources),
        all_urls=["https://news.google.com/rss/articles/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_the_measured_item_is_refused() -> None:
    assert _uncorroborated_search_hit(_event("api:news-google-com-search"))


def test_a_second_outlet_makes_it_acceptable() -> None:
    assert not _uncorroborated_search_hit(
        _event("api:news-google-com-search", "rss:axios")
    )


def test_the_aihot_trio_is_a_real_second_outlet() -> None:
    """Their three feeds collapse to one group, but that group is not the search feed."""
    assert not _uncorroborated_search_hit(
        _event("api:news-google-com-search", "rss:aihot-news-picks")
    )


def test_an_ordinary_source_is_untouched() -> None:
    assert not _uncorroborated_search_hit(_event("rss:axios"))


def test_the_source_is_still_registered() -> None:
    """The rule refuses items, not sources -- 「不得擅自删除信息源」."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "sources" / "registry.yaml").read_text(encoding="utf-8")
    for sid in SEARCH_INDEX_SOURCES:
        assert sid in text, sid