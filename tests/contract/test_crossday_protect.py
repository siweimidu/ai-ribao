"""A widely corroborated story must not be deleted by the cross-day dedup guess.

Measured 2026-10-28: the 06:48 build of the issue dropped `Genie 4`, carried by 20
independent sources -- the DeepMind blog, four aihot feeds, juya, the Verge, TechCrunch,
Hacker News. Nothing named Genie had been published in the previous seven days, so there was
nothing for it to duplicate. The 14:51 rebuild kept it and it published at #03.

The check is a model comparing wording, and a big story has twenty different versions of its
own wording. Source count is the evidence the model does not see.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.crossday_llm import MIN_SOURCES_TO_PROTECT, drop_cross_day_duplicates
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


class _Router:
    """Marks every today-event a duplicate."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, messages, **kwargs):
        self.calls += 1
        today = [
            line.split("id=")[1].split(" ")[0]
            for line in messages[-1]["content"].splitlines()
            if "id=T" in line
        ]
        return {
            "duplicates": [
                {"today": tid, "earlier": "E0", "why": "same story"} for tid in today
            ]
        }


def _event(event_id: str, sources: int) -> Event:
    return Event(
        event_id=event_id,
        title=f"Google DeepMind Genie 4 world model {event_id}",
        member_item_ids=[event_id],
        primary_item_id=event_id,
        source_ids=[f"rss:src{i}" for i in range(sources)],
        all_urls=[f"https://example.com/{event_id}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def _run(events):
    earlier = [("2026-10-21", "Something unrelated that happened last week")]
    return asyncio.run(drop_cross_day_duplicates(events, earlier, _Router()))


def test_a_single_source_event_is_dropped() -> None:
    result = _run([_event("a", 1), _event("b", 1)])
    assert result.dropped == 2
    assert not result.protected


def test_a_widely_reported_event_is_kept() -> None:
    result = _run([_event("a", 1), _event("b", 20)])
    assert result.dropped == 1
    assert [e.event_id for e in result.events] == ["b"]
    assert len(result.protected) == 1
    assert result.protected[0]["sources"] == 20


def test_the_threshold_is_the_documented_one() -> None:
    assert MIN_SOURCES_TO_PROTECT == 3


def test_an_event_at_the_threshold_is_kept() -> None:
    result = _run([_event("t3", MIN_SOURCES_TO_PROTECT)])
    assert result.dropped == 0
    assert len(result.events) == 1


def test_one_below_the_threshold_is_dropped() -> None:
    result = _run([_event("t2", MIN_SOURCES_TO_PROTECT - 1)])
    assert result.dropped == 1


def test_the_label_reports_what_was_protected() -> None:
    result = _run([_event("a", 1), _event("b", 5)])
    assert "保护" in result.label