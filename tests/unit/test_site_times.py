"""A date shown to a Chinese reader must be the date that reader would call it.

On 2026-10-20 the issue's first entry showed "10-19 21:47 UTC". Every event in that issue was a
Beijing-20th event -- the UTC clock simply reads eight hours earlier -- but the reader saw a
10-19 date inside the 10-20 issue and reasonably concluded that yesterday's news had been
filed under today.

The digest dates themselves were always Beijing dates (that is what `split_by_date` compares),
so the archive was correct; only the label was wrong. That mismatch is the worst kind: it makes
a correct archive look broken.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.models import Event
from aidaily.site import _when

BJ = timezone(timedelta(hours=8))


def _event(ts: datetime) -> Event:
    return Event(
        event_id="e1",
        primary_item_id="i1",
        title="t",
        member_item_ids=["i1"],
        source_ids=["rss:a"],
        all_urls=["https://example.com/a"],
        published_range=(ts, ts),
        first_seen_at=ts,
        last_updated_at=ts,
    )


def test_a_late_utc_hour_shows_the_next_beijing_day() -> None:
    """The exact case: 21:47 UTC on the 19th is 05:47 Beijing on the 20th."""
    ts = datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc)
    label, known = _when(_event(ts))
    assert known
    assert label == "10-20 05:47", label


def test_the_label_never_carries_a_utc_marker() -> None:
    """A bare "UTC" on a Chinese page invites the reader to apply the wrong date."""
    ts = datetime(2026, 10, 19, 16, 41, tzinfo=timezone.utc)
    label, _ = _when(_event(ts))
    assert "UTC" not in label, label


def test_every_rendered_issue_labels_events_in_beijing_time() -> None:
    """Guard on the artefact: no page may present a UTC timestamp as an item date."""
    import re
    from pathlib import Path

    site = Path(__file__).resolve().parents[2] / "data" / "digests" / "site"
    pages = sorted(site.glob("2026-*.html"))
    if not pages:
        return
    for page in pages:
        html = page.read_text(encoding="utf-8")
        # Only the item *label* is constrained: `<span>10-19 21:47 UTC</span>` under a title.
        # A model-written fact may quote a publisher's own UTC timestamp ("…于 2026-10-13
        # 17:05 UTC 发布"), and that is content, not a label.
        body = html.split('class="site__foot"')[0] if 'class="site__foot"' in html else html
        stray = re.findall(r"<span>\d{2}-\d{2} \d{2}:\d{2} UTC</span>", body)
        assert not stray, f"{page.name} labels items with UTC: {stray[:3]}"
