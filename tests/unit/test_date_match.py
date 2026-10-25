"""Only items whose publication date is the issue date get in.

「信息源只收纳当天的信息，日期必须对得上，日期对上以后才不用筛选」

## What the rolling window let through

`window_hours: 36` was a rolling cutoff: an issue built at 12:00 on the 25th accepted
anything published after noon on the 24th. Measured on the 2026-10-25 issue: 129 entries, of
which only 22 were published that day. The page led with

    01  Kimi K3.1 Pro 发布              2026-10-22   3 days old
    03  微软宣布 MAI-Base-2 完成预训练     2026-10-16   9 days old
    05  阶跃 Step 5 Preview 开放模型权重    2026-10-16   9 days old

and the tail reached back to 2025-10-08. A date check removes all of that; a 36-hour window
still lets yesterday afternoon in.

## The order the instruction sets

1. The date must match. Nothing else matters for an item from another day.
2. Once the date matches, the source is not relevance-filtered -- a Chinese model-release
   headline scores under the AI floor and still belongs in the issue.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidaily.config import load_config
from aidaily.models import NormalizedItem
from aidaily.select import select_window

#: A fixed instant: 14:00 Beijing on the issue date, so `today` is unambiguous.
NOW = datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)


def _item(i: int, *, days_ago: int, hours_ago: int = 0) -> NormalizedItem:
    title = f"T{i}"
    return NormalizedItem(
        item_id=f"i{i}",
        source_id="rss:x",
        title=title,
        title_norm=title,
        url=f"https://e/{i}",
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        published_at=NOW - timedelta(days=days_ago, hours=hours_ago),
        content_sha256=hashlib.sha256(title.encode()).hexdigest(),
        simhash=0,
        age_bucket="today",
    )


def _cfg():
    return load_config(Path(__file__).resolve().parents[2] / "config" / "daily.yaml")


def test_an_item_published_today_is_kept() -> None:
    result = select_window([_item(0, days_ago=0)], _cfg(), NOW)
    assert len(result.kept) == 1


def test_an_item_published_earlier_today_is_kept() -> None:
    """13 hours ago is 01:00 Beijing -- same calendar day, still today."""
    result = select_window([_item(0, days_ago=0, hours_ago=13)], _cfg(), NOW)
    assert len(result.kept) == 1


def test_yesterdays_item_is_dropped_even_though_it_is_recent() -> None:
    """This is the case a 36-hour rolling window let through."""
    result = select_window([_item(0, days_ago=1)], _cfg(), NOW)
    assert not result.kept
    assert result.dropped_by_bucket.get("wrong_date") == 1


def test_a_nine_day_old_item_is_dropped() -> None:
    """`微软宣布 MAI-Base-2` led the 2026-10-25 issue at 9 days old."""
    result = select_window([_item(0, days_ago=9)], _cfg(), NOW)
    assert not result.kept
    assert result.dropped_by_bucket.get("wrong_date") == 1


def test_the_reason_is_recorded_not_only_counted() -> None:
    """A thin issue and a stale feed look identical without the samples."""
    result = select_window([_item(0, days_ago=3)], _cfg(), NOW)
    assert result.wrong_date_samples
    assert "2026-10-22" in result.wrong_date_samples[0]


def test_a_future_date_is_still_a_separate_rejection() -> None:
    result = select_window([_item(0, days_ago=-20)], _cfg(), NOW)
    assert not result.kept
    assert result.dropped_by_bucket.get("future_dated") == 1


def test_mixed_input_keeps_only_today() -> None:
    items = [
        _item(0, days_ago=0),
        _item(1, days_ago=0, hours_ago=13),
        _item(2, days_ago=1),
        _item(3, days_ago=9),
    ]
    result = select_window(items, _cfg(), NOW)
    assert [i.item_id for i in result.kept] == ["i0", "i1"]


def test_an_item_without_a_date_is_not_silently_kept() -> None:
    """Undated means unprovable; the default must not treat it as today."""
    item = _item(0, days_ago=0)
    item.published_at = None
    item.age_bucket = "unknown"
    result = select_window([item], _cfg(), NOW)
    assert not result.kept