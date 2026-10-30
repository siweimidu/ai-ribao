"""The morning slot cannot carry the morning paper.

juya publishes its edition around 08:39 Beijing. The first collection is at 04:00, so its issue
is built before juya exists -- and the gate refuses every later trigger in that same slot, so
juya stays absent all day unless the 12:00 slot happens to fire. GitHub delays schedules by
hours, so it often does not.

Measured 2026-10-30: generated 07:01 Beijing, juya 0 events, page said
「本期未收录：橘鸦」 at noon.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.__main__ import SOURCE_READY_HOUR, _morning_rebuild_due

BJ = timezone(timedelta(hours=8))


def _bj(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 30, hour, minute, tzinfo=BJ)


def test_an_issue_built_before_the_ready_hour_is_rebuilt() -> None:
    assert _morning_rebuild_due(_bj(10), "2026-10-29T23:01:39Z")


def test_an_issue_already_built_after_the_ready_hour_is_not() -> None:
    assert not _morning_rebuild_due(_bj(10), "2026-10-30T01:30:00Z")


def test_nothing_happens_before_the_ready_hour() -> None:
    assert not _morning_rebuild_due(_bj(8), "2026-10-29T23:01:39Z")


def test_the_rule_fires_once_per_day() -> None:
    """After the rebuild the stamp is past the hour, so it cannot fire again."""
    assert _morning_rebuild_due(_bj(10), "2026-10-29T23:01:39Z")
    assert not _morning_rebuild_due(_bj(11), "2026-10-30T02:05:00Z")


def test_a_missing_stamp_is_rebuilt() -> None:
    assert _morning_rebuild_due(_bj(10), "")


def test_a_malformed_stamp_is_left_alone() -> None:
    """An unreadable archive is not evidence of staleness; do not churn on it."""
    assert not _morning_rebuild_due(_bj(10), "not-a-date")


def test_the_ready_hour_is_nine() -> None:
    assert SOURCE_READY_HOUR == 9