"""Every date the reader sees is a Beijing date, and every feed timestamp is correct.

This module exists because the same defect appeared in four different places:

  1. the calendar's "today" (build time, and the runner's UTC zone);
  2. the item label (`10-19 21:47 UTC` inside the 10-20 issue);
  3. the Markdown export (the same UTC label, in a file the reader downloads);
  4. the RSS `pubDate` -- this one was worse than cosmetic: `strftime("... +0000")` formats a
     datetime in *its own* zone and merely prints `+0000`, so a Beijing value was emitted eight
     hours off, and a day off across midnight. Every RSS reader and n8n saw the wrong date.

Fixing them one at a time is how the fourth one survived three rounds. These tests assert the
rule for the whole output surface at once.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pytest

from aidaily.models import Digest, Event, SourceCoverage
from aidaily.render import render_deep
from aidaily.site import _when

BJ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[2]


def _event(ts: datetime | None) -> Event:
    now = ts or datetime(2026, 10, 20, tzinfo=BJ)
    return Event(
        event_id="e1",
        primary_item_id="i1",
        title="一条消息",
        member_item_ids=["i1"],
        source_ids=["rss:a"],
        all_urls=["https://example.com/a"],
        published_range=(ts, ts) if ts else None,
        first_seen_at=now,
        last_updated_at=now,
    )


def test_a_late_utc_hour_shows_the_next_beijing_day() -> None:
    """21:47 UTC on the 19th is 05:47 Beijing on the 20th -- the case that started this."""
    label, known = _when(_event(datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc)))
    assert known and label == "10-20 05:47", label


def test_the_item_label_carries_no_zone_marker() -> None:
    label, _ = _when(_event(datetime(2026, 10, 19, 16, 41, tzinfo=timezone.utc)))
    assert "UTC" not in label


def _digest() -> Digest:
    ev = _event(datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc))
    return Digest(
        date="2026-10-20",
        kind="deep",
        generated_at=datetime(2026, 10, 19, 23, 23, tzinfo=timezone.utc),
        window_start=datetime(2026, 10, 18, 21, 23, tzinfo=timezone.utc),
        window_end=datetime(2026, 10, 19, 23, 23, tzinfo=timezone.utc),
        headline="头条",
        top_events=[ev],
        sections={"要闻": [ev]},
        source_coverage=SourceCoverage(total=1, active=1, failed=0, skipped=0),
        counts={"events": 1, "multi_source_events": 0},
    )


def test_the_markdown_export_labels_in_beijing_time() -> None:
    text = render_deep(_digest(), {}, {}, max_items=1)
    assert "10-20 05:47" in text, text[:400]
    assert "10-19 21:47 UTC" not in text


def test_rss_pubdate_is_actually_utc() -> None:
    """A literal `+0000` does not convert the value; the value must already be UTC.

    Measured before the fix: the instant 2026-10-19T21:47Z was published as
    "Tue, 20 Oct 2026 05:47:00 +0000" -- eight hours later, and a different day.
    """
    import tempfile

    from aidaily.publish import write_rss

    with tempfile.TemporaryDirectory() as tmp:
        write_rss(_digest(), Path(tmp), site_url="https://example.com", insights={})
        xml = (Path(tmp) / "site" / "feed" / "zh.xml").read_text(encoding="utf-8")

    stamps = re.findall(r"<pubDate>(.*?)</pubDate>", xml)
    assert stamps, xml[:400]
    parsed = parsedate_to_datetime(stamps[0])
    expected = datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc)
    assert parsed == expected, f"pubDate {stamps[0]!r} != {expected.isoformat()}"


def test_no_rendered_page_labels_items_in_utc() -> None:
    site = ROOT / "data" / "digests" / "site"
    pages = sorted(site.glob("2026-*.html"))
    if not pages:
        pytest.skip("no rendered pages here")
    for page in pages:
        html = page.read_text(encoding="utf-8")
        stray = re.findall(r"<span>\d{2}-\d{2} \d{2}:\d{2} UTC</span>", html)
        assert not stray, f"{page.name}: {stray[:3]}"
