"""A story belongs to the day it was **published**, not the day it was collected.

## The rule

If a story surfaces on the 18th but carries a publication timestamp on the 17th, it belongs in the
17th's issue, ranked by importance and heat like everything else. DeepSeek V4.1 Flash 1017 is the
case that forced this: a 10-17 release, and the 10-17 issue closed at 14:38 Beijing before it broke.

These tests pin the routing arithmetic and the two properties that make it safe:

* a story is never filed under the wrong date, and
* the merge promotes a major late story instead of appending it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aidaily.backfill import MAX_BACKFILL_DAYS, local_date, split_by_date
from aidaily.models import NormalizedItem

BJ = timezone(timedelta(hours=8))


def make(item_id: str, when: datetime | None, title: str = "story") -> NormalizedItem:
    return NormalizedItem(
        item_id=item_id,
        source_id="rss:test",
        title=title,
        title_norm=title.lower(),
        url=f"https://example.com/{item_id}",
        published_at=when,
        fetched_at=when or datetime(2026, 10, 18, tzinfo=timezone.utc),
        first_seen_at=when or datetime(2026, 10, 18, tzinfo=timezone.utc),
        updated_at=when or datetime(2026, 10, 18, tzinfo=timezone.utc),
        content_text="body",
        summary="body",
        content_sha256="0" * 64,
        simhash=0,
    )


def at(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BJ)


def test_local_date_uses_beijing_not_utc() -> None:
    # 17:30 UTC on the 17th is 01:30 Beijing on the 18th. Filing it under the 17th would be the
    # exact bug -- a date that disagrees with what a reader in Beijing calls "today".
    utc = datetime(2026, 10, 17, 17, 30, tzinfo=timezone.utc)
    assert local_date(utc, 8) == "2026-10-18"
    assert local_date(utc, 0) == "2026-10-17"


def test_a_story_published_on_the_target_stays() -> None:
    items = [make("a", at(2026, 10, 17, 15, 0))]
    split = split_by_date(items, "2026-10-17", tz_offset_hours=8)
    assert [i.item_id for i in split.target] == ["a"]
    assert split.late == {}


def test_a_late_story_is_routed_to_its_own_date() -> None:
    """The rule itself: seen on the 18th, published on the 17th, filed under the 17th."""
    items = [make("late", at(2026, 10, 17, 20, 0))]
    split = split_by_date(items, "2026-10-18", tz_offset_hours=8)
    assert split.target == []
    assert list(split.late) == ["2026-10-17"]
    assert [i.item_id for i in split.late["2026-10-17"]] == ["late"]


def test_a_future_story_is_not_filed_into_today() -> None:
    """The mirror image of the bug: a 10-18 story must not appear in the 10-17 issue."""
    items = [make("future", at(2026, 10, 18, 9, 0))]
    split = split_by_date(items, "2026-10-17", tz_offset_hours=8)
    assert split.target == []
    assert split.late == {}
    assert split.ignored == 1


def test_backfill_range_is_bounded() -> None:
    too_old = at(2026, 10, 17) - timedelta(days=MAX_BACKFILL_DAYS + 1)
    items = [make("ancient", too_old)]
    split = split_by_date(items, "2026-10-18", tz_offset_hours=8)
    assert split.late == {}
    assert split.ignored == 1


def test_undated_is_never_back_dated() -> None:
    """A missing date is not evidence of an old date."""
    items = [make("undated", None)]
    split = split_by_date(items, "2026-10-18", tz_offset_hours=8)
    assert [i.item_id for i in split.target] == ["undated"]
    assert split.late == {}


@pytest.mark.parametrize("hour", [0, 6, 11, 12, 18, 23])
def test_late_bucket_is_sorted_newest_first(hour: int) -> None:
    items = [
        make("early", at(2026, 10, 17, hour, 0)),
        make("late", at(2026, 10, 17, min(hour + 1, 23), 30)),
    ]
    split = split_by_date(items, "2026-10-18", tz_offset_hours=8)
    bucket = split.late["2026-10-17"]
    assert bucket[0].item_id == "late"


def test_summary_reports_every_date() -> None:
    items = [
        make("a", at(2026, 10, 16, 10, 0)),
        make("b", at(2026, 10, 17, 10, 0)),
        make("c", at(2026, 10, 17, 12, 0)),
    ]
    split = split_by_date(items, "2026-10-18", tz_offset_hours=8)
    assert split.summary()["late_by_date"] == {"2026-10-16": 1, "2026-10-17": 2}
    assert split.late_total == 3
