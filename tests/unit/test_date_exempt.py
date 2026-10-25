"""Sources the user asked to run unfiltered must not be dropped by the date window.

Measured 2026-10-25, the 6-day window against each feed's newest item:

    rss:hex2077         2026-10-11   14 days   all dropped
    rss:daily-juya-uk   2026-10-15   10 days   all dropped
    rss:ainewslog-com   2026-10-14   11 days   all dropped

These serve a rolling archive rather than a today-only feed, so the newest item is often a
week or two old. Judging them by publication date throws away the material that was explicitly
requested. Scoring still separates them: `heat` discounts by age, so an old story ranks low
without being deleted.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from aidaily.backfill import DATE_EXEMPT_SOURCES, _date_exempt, split_by_date
from aidaily.models import NormalizedItem

NOW = datetime.now(timezone.utc)


def _item(sid: str, days_ago: int, i: int = 0) -> NormalizedItem:
    title = f"标题 {i}"
    return NormalizedItem(
        item_id=f"i{i}",
        source_id=sid,
        title=title,
        title_norm=title,
        url=f"https://example.com/{i}",
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        published_at=NOW - timedelta(days=days_ago),
        content_sha256=hashlib.sha256(title.encode()).hexdigest(),
        simhash=0,
    )


def test_an_exempt_source_survives_a_stale_item() -> None:
    """The exact failure: 14 days old, 6-day window, dropped."""
    items = [_item("rss:hex2077", 14)]
    split = split_by_date(items, NOW.strftime("%Y-%m-%d"))
    assert len(split.target) == 1
    assert not split.late and split.ignored == 0


def test_a_non_exempt_source_is_still_windowed() -> None:
    """The window must keep working for everything else."""
    items = [_item("rss:some-other-feed", 30)]
    split = split_by_date(items, NOW.strftime("%Y-%m-%d"))
    assert not split.target
    assert split.ignored == 1


def test_every_requested_source_is_on_the_list() -> None:
    for sid in (
        "rss:hex2077",
        "rss:daily-juya-uk",
        "rss:ainewslog-com",
        "api:aibase-ai-news",
        "api:aibase-daily-news",
    ):
        assert sid in DATE_EXEMPT_SOURCES, sid


def test_the_helper_matches_on_source_id_only() -> None:
    assert _date_exempt(_item("rss:hex2077", 100))
    assert not _date_exempt(_item("rss:other", 100))


def test_a_future_dated_exempt_item_still_joins_the_target() -> None:
    """A wrong clock on one feed must not silently drop the source."""
    item = _item("rss:daily-juya-uk", -3)
    split = split_by_date([item], NOW.strftime("%Y-%m-%d"))
    assert len(split.target) == 1