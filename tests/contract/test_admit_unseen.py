"""Named sources admit an item on the first issue that can carry it.

「当天每一条从没被报道过的，都收；报道过的一律不再出现」

Measured 2026-10-29: `ainewslog` delivered 662 items and contributed 0 events,
`aibase-daily-news` 20 and 0, `hex2077` 38 and 0. Their items were fine; their timestamps were
older than the issue date, and `select_window` asked 「发布日 == 今天」.

「不收录周刊」 -- a weekly issue drops thirty-odd stories on one date, so `hex2077` and the
aihot weekly/monthly feeds stay on the plain same-day rule.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidaily.config import load_config
from aidaily.models import NormalizedItem
from aidaily.select import select_window
from aidaily.unfiltered import WEEKLY_SOURCES, admits_unseen

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=BJ).astimezone(timezone.utc)


def _item(title: str, source: str, days_ago: int) -> NormalizedItem:
    published = NOW - timedelta(days=days_ago)
    return NormalizedItem(
        item_id=f"{source}-{title[:6]}-{days_ago}",
        source_id=source,
        title=title,
        title_norm=title,
        url=f"https://example.com/{abs(hash(title + str(days_ago))) % 99999}",
        published_at=published,
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        content_text=title,
        content_sha256=hashlib.sha256(title.encode()).hexdigest(),
        simhash=0,
    )


def _kept(items):
    cfg = load_config(Path(__file__).resolve().parents[2] / "config" / "daily.yaml")
    result = select_window(items, cfg, NOW)
    return {i.title for i in result.kept}


def test_a_named_source_is_admitted_a_few_days_late() -> None:
    kept = _kept([_item("三天前的日报条目", "rss:ainewslog-com", 3)])
    assert "三天前的日报条目" in kept


def test_a_plain_source_is_still_refused() -> None:
    kept = _kept([_item("三天前的普通条目", "rss:axios", 3)])
    assert "三天前的普通条目" not in kept


def test_a_weekly_source_is_not_admitted_late() -> None:
    """「不收录周刊」."""
    for sid in WEEKLY_SOURCES:
        kept = _kept([_item("一周前的一期周刊", sid, 3)])
        assert "一周前的一期周刊" not in kept, sid


def test_the_reach_is_bounded() -> None:
    """Old enough to be stale for everyone."""
    kept = _kept([_item("很久以前的条目", "rss:ainewslog-com", 30)])
    assert "很久以前的条目" not in kept


def test_todays_item_is_kept_for_any_source() -> None:
    kept = _kept([
        _item("今天的普通条目", "rss:axios", 0),
        _item("今天的具名条目", "rss:daily-juya-uk", 0),
    ])
    assert "今天的普通条目" in kept
    assert "今天的具名条目" in kept


def test_admits_unseen_covers_exactly_the_daily_named_sources() -> None:
    from aidaily.unfiltered import UNFILTERED_SOURCES

    for sid in UNFILTERED_SOURCES:
        assert admits_unseen(sid) == (sid not in WEEKLY_SOURCES), sid
    assert not admits_unseen("rss:axios")
    assert not admits_unseen(None)