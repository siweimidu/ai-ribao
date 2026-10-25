"""The recency window must not delete the sources the user asked to run unfiltered.

`window_hours` defaults to 36. Measured 2026-10-25, the newest item per feed:

    rss:hex2077         2026-10-11   14 days
    rss:ainewslog-com   2026-10-14   11 days
    rss:daily-juya-uk   2026-10-15   10 days

None of those fits inside any 36-hour window, so `select_window` discarded all of them --
526 items -- and the issue carried 26 entries instead of a few hundred.

`split_by_date` was fixed first and did not help: it runs earlier, and by the time the window
stage saw the items they were already inside the target date and still too old.

Correctness checks stay: a future date or a missing URL is a defect, not old news.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from aidaily.config import load_config
from aidaily.models import NormalizedItem
from aidaily.select import select_window

NOW = datetime.now(timezone.utc)


def _item(sid: str, days_ago: int, i: int = 0, url: str | None = None) -> NormalizedItem:
    title = f"标题 {i}"
    return NormalizedItem(
        item_id=f"i{i}",
        source_id=sid,
        title=title,
        title_norm=title,
        url=f"https://example.com/{i}" if url is None else url,
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        published_at=NOW - timedelta(days=days_ago),
        content_sha256=hashlib.sha256(title.encode()).hexdigest(),
        simhash=0,
    )


def _cfg():
    from pathlib import Path

    return load_config(Path(__file__).resolve().parents[2] / "config" / "daily.yaml")


def test_an_old_item_from_an_unfiltered_source_is_kept() -> None:
    """The failure: 14 days old against a 36-hour window."""
    result = select_window([_item("rss:hex2077", 14)], _cfg(), NOW)
    assert len(result.kept) == 1


def test_an_old_item_from_another_source_is_still_dropped() -> None:
    """The window must keep doing its job everywhere else."""
    result = select_window([_item("rss:ordinary-feed", 14)], _cfg(), NOW)
    assert not result.kept


def test_a_future_date_is_still_rejected_for_an_unfiltered_source() -> None:
    """A future date is a defect, not old news."""
    item = _item("rss:hex2077", -20)
    result = select_window([item], _cfg(), NOW)
    assert not result.kept
    assert result.dropped_by_bucket.get("future_dated") == 1


def test_a_missing_url_is_still_rejected_for_an_unfiltered_source() -> None:
    """Every entry must link to its source."""
    item = _item("rss:hex2077", 14, url="")
    result = select_window([item], _cfg(), NOW)
    assert not result.kept
    assert result.dropped_by_bucket.get("no_url") == 1


def test_every_named_feed_survives_the_window() -> None:
    for sid in (
        "rss:hex2077",
        "rss:daily-juya-uk",
        "rss:ainewslog-com",
        "api:aibase-ai-news",
        "api:aibase-daily-news",
        "rss:aihot-news-all",
    ):
        result = select_window([_item(sid, 14)], _cfg(), NOW)
        assert len(result.kept) == 1, sid