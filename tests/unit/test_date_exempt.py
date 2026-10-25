"""The date window applies to every source, including the unfiltered ones.

## What went wrong

The 2026-10-25 issue led with:

    01  Kimi K3.1 Pro 发布              2026-10-22   3 days old
    03  微软宣布 MAI-Base-2 完成预训练     2026-10-16   9 days old
    05  阶跃 Step 5 Preview 开放模型权重    2026-10-16   9 days old

Of 129 entries only 22 were published that day. The rest went back to 2025-10-08.

The instruction was 「抓取这些的当日源不用筛选，直接打分排序」 -- *the day's* items,
unfiltered by relevance. Reading "不用筛选" as "no date window either" filled the issue with
a week of backlog.

## The distinction that matters

* **Relevance** -- a Chinese model-release headline scores under the AI floor. These sources
  must bypass it. That exemption stays (`unfiltered.UNFILTERED_SOURCES`).
* **Age** -- old news is old news whoever published it. That exemption is gone.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from aidaily.backfill import DATE_EXEMPT_SOURCES, _date_exempt, split_by_date
from aidaily.config import load_config
from aidaily.models import NormalizedItem
from aidaily.select import select_window

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
        age_bucket="today" if days_ago == 0 else "older",
    )


def _cfg():
    from pathlib import Path

    return load_config(Path(__file__).resolve().parents[2] / "config" / "daily.yaml")


def test_no_source_is_exempt_from_the_date_window() -> None:
    """The list is empty on purpose; see the module docstring."""
    assert DATE_EXEMPT_SOURCES == frozenset()


def test_an_unfiltered_source_with_an_old_item_is_dropped_by_the_window() -> None:
    """`daily-juya` served a 9-day-old item that led the issue."""
    result = select_window([_item("rss:daily-juya-uk", 9)], _cfg(), NOW)
    assert not result.kept


def test_an_unfiltered_source_with_a_today_item_is_kept() -> None:
    """The source is not banned -- only its old items are."""
    result = select_window([_item("rss:daily-juya-uk", 0)], _cfg(), NOW)
    assert len(result.kept) == 1


def test_split_by_date_no_longer_routes_old_items_to_the_target() -> None:
    """This was the first of the two exemptions, and the wrong one."""
    item = _item("rss:hex2077", 14)
    split = split_by_date([item], NOW.strftime("%Y-%m-%d"))
    assert not split.target


def test_the_helper_never_exempts_anything_now() -> None:
    for sid in ("rss:hex2077", "rss:daily-juya-uk", "rss:aihot-news-all", "api:aibase-com"):
        assert not _date_exempt(_item(sid, 30)), sid


def test_relevance_exemption_is_a_separate_concern() -> None:
    """The sources still bypass the AI floor; only the date window changed."""
    from aidaily.unfiltered import UNFILTERED_SOURCES

    for sid in ("rss:hex2077", "rss:daily-juya-uk", "rss:ainewslog-com"):
        assert sid in UNFILTERED_SOURCES, sid