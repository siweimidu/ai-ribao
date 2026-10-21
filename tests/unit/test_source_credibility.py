"""The page must not claim more corroboration than it can show.

Reported from the live site on 2026-10-21: an entry read

    多源交叉验证 · 7 个独立来源 · aihot.news  aihot.news  aihot.news  aihot.news  另有 6 个来源

Seven sources, one domain. The badge and the links contradicted each other on the same row.

Two separate defects produced that:

1. the *links* were built from `event.all_urls[1:5]` with no de-duplication, so one publisher\'s
   several feeds produced several identical-looking entries;
2. the *count* came from the archived `independent_source_count`, which older pipeline versions
   computed over **feeds** rather than publishers -- AIHOT alone is registered as twelve feeds.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.l3 import _publisher_of
from aidaily.models import Event
from aidaily.site import render_item

NOW = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)


def _event(source_ids: list[str], urls: list[str], count: int) -> Event:
    return Event(
        event_id="e1",
        primary_item_id="i1",
        title="Gemini 车载个人智能上线",
        member_item_ids=["i1"],
        source_ids=source_ids,
        all_urls=urls,
        independent_source_count=count,
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_feeds_from_one_publisher_collapse_to_one_source() -> None:
    """The registry has twelve AIHOT feeds; they are one publisher."""
    ids = [
        "rss:aihot-news",
        "rss:aihot-news-full",
        "rss:aihot-news-picks",
        "rss:aihot-cat-models",
    ]
    assert len({_publisher_of(i, {}) for i in ids}) == 1


def test_the_badge_is_recomputed_not_trusted_from_the_archive() -> None:
    """An old issue renders honestly without being regenerated.

    The archived count says 3; the sources say 1. The page must say nothing rather than repeat
    a claim its own links cannot support.
    """
    event = _event(
        ["rss:aihot-news-full", "rss:aihot-news-picks", "rss:aihot-cat-products"],
        ["https://aihot.news/items/a", "https://aihot.news/items/b"],
        count=3,
    )
    html = render_item(1, event, None, None)
    assert "3 个独立来源" not in html, "the archived (wrong) count was trusted"
    assert "个独立来源" not in html, "one publisher must not read as corroboration"


def test_the_links_list_one_entry_per_domain() -> None:
    """Four AIHOT feeds on one story must not print four links."""
    event = _event(
        ["rss:aihot-news", "rss:aihot-news-full", "rss:aihot-news-picks", "rss:aihot-cat-models"],
        [
            "https://aihot.news/items/a",
            "https://aihot.news/items/b",
            "https://aihot.news/items/c",
            "https://aihot.news/items/d",
        ],
        count=4,
    )
    html = render_item(1, event, None, None)
    marker = '<div class="item__links">'
    row = html.split(marker)[-1]
    # The first URL becomes the title link; the remaining three collapse to one, because they
    # share a host. The old code printed every one of them.
    assert row.count("aihot.news</a>") == 1, row[:200]
    assert "另有" not in row, "one domain is one source, so there is nothing in reserve"


def test_mirrors_are_not_listed_as_sources() -> None:
    """An aggregator is a copy, not a witness.

    The story was carried by theverge and techcrunch; aihot merely relayed it. Listing aihot in
    the source row credits it with reporting it did not do, and sends a reader who wants the
    original to a page that copied it. Only direct publishers are named.
    """
    event = _event(
        ["rss:aihot-news", "rss:theverge-com-ai", "rss:techcrunch-com-ai"],
        [
            "https://aihot.news/items/a",
            "https://www.theverge.com/x",
            "https://techcrunch.com/y",
        ],
        count=3,
    )
    html = render_item(1, event, None, None)
    assert "3 个独立来源" in html
    row = html.split('<div class="item__links">')[-1]
    assert "theverge.com" in row
    assert "aihot.news" not in row, "the aggregator must not be presented as a source"
