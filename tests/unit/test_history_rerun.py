"""Re-running a date must replace its history row, not append another one.

Measured 2026-10-24, after four re-runs of the same date:

    10-24 history: 36 events
    10-24 history: 88 events
    10-24 history: 98 events
    10-24 history: 108 events

`record` appended unconditionally, so each run deduplicated its own stories against the
previous run's output. The merged Kimi K3.1 Pro entry -- four headlines folded into one with
multi-source corroboration -- was removed as "already published" by the history of the run
that had produced it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from aidaily.history import PublishedHistory
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _event(i: int, title: str) -> Event:
    return Event(
        event_id=f"e{i}",
        title=title,
        member_item_ids=[f"m{i}"],
        primary_item_id=f"m{i}",
        source_ids=["s"],
        all_urls=[f"https://x/{i}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def _rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_recording_the_same_date_twice_keeps_one_row(tmp_path) -> None:
    """The bug: four runs of one date left four rows."""
    path = tmp_path / "h.jsonl"
    for run in range(4):
        history = PublishedHistory(path)
        history.load()
        history.record([_event(run, f"标题 {run}")], date="2026-10-24")
    assert len(_rows(path)) == 1


def test_the_surviving_row_is_the_latest_run(tmp_path) -> None:
    """A re-run publishes a different issue; the file must describe that one."""
    path = tmp_path / "h.jsonl"
    for run in range(3):
        history = PublishedHistory(path)
        history.load()
        history.record([_event(run, f"标题 {run}")], date="2026-10-24")
    row = _rows(path)[0]
    assert row["events"][0]["title"] == "标题 2"


def test_other_dates_are_untouched(tmp_path) -> None:
    path = tmp_path / "h.jsonl"
    history = PublishedHistory(path)
    history.load()
    history.record([_event(1, "第一天")], date="2026-10-23")
    history.record([_event(2, "第二天")], date="2026-10-24")
    history.record([_event(3, "第二天重跑")], date="2026-10-24")
    dates = sorted(r["date"] for r in _rows(path))
    assert dates == ["2026-10-23", "2026-10-24"]


def test_a_rerun_does_not_match_its_own_previous_output(tmp_path) -> None:
    """The real consequence: the merged entry was dropped as already published."""
    path = tmp_path / "h.jsonl"
    first = PublishedHistory(path)
    first.load()
    first.record([_event(1, "Moonshot AI Releases Kimi K3.1 Pro")], date="2026-10-24")

    rebuilt = PublishedHistory(path)
    rebuilt.load()
    # The archive is authoritative; the row for today describes *this* run, so nothing
    # inside it should count as cross-day repetition.
    assert rebuilt.find_repeat(
        _event(2, "Moonshot AI Releases Kimi K3.1 Pro"), today="2026-10-24", now=NOW
    ) is None