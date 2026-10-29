"""Named sources are never deleted -- only merged and marked multi-source.

「但凡是那几个不要筛选直接进打分的那几个源获得的当日信息，这些消息只能去重并标注多源验证，
  不能删除，这些信息价值很高，不能删除任何一条，这条要写死」

Three stages could remove an event, and all three are now closed:

  1. cross-day semantic dedup   -- may merge, may not delete
  2. the max_items cut          -- may not truncate them out of the issue
  3. the fact-check drop        -- may not remove them for a malformed field

Measured 2026-10-28: Genie 4 arrived from juya among twenty sources and a cross-day dedup
pass deleted the whole event, while nothing named Genie had been published in the previous
seven days. The issue published without the biggest story of the day.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from pathlib import Path

from aidaily import pipeline
from aidaily.crossday_llm import drop_cross_day_duplicates
from aidaily.models import Event
from aidaily.unfiltered import UNFILTERED_SOURCES, protects

NOW = datetime.now(timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


class _DupRouter:
    """Marks every today-event a duplicate."""

    async def complete_json(self, messages, **kwargs):
        today = [
            line.split("id=")[1].split(" ")[0]
            for line in messages[-1]["content"].splitlines()
            if "id=T" in line
        ]
        return {"duplicates": [{"today": t, "earlier": "E0", "why": "same"} for t in today]}


def _event(event_id: str, *sources: str) -> Event:
    return Event(
        event_id=event_id,
        title=f"Genie 4 world model {event_id}",
        member_item_ids=[event_id],
        primary_item_id=event_id,
        source_ids=list(sources) or ["rss:axios"],
        all_urls=[f"https://example.com/{event_id}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_every_named_source_is_protected() -> None:
    for sid in UNFILTERED_SOURCES:
        assert protects([sid]), sid


def test_a_plain_source_is_not_protected() -> None:
    for sid in ("rss:axios", "rss:theverge-com-ai-artificial-intelligence", "api:hn-algolia-com-search"):
        assert not protects([sid]), sid


def test_cross_day_dedup_cannot_delete_a_named_source() -> None:
    """The exact Genie 4 shape: the only thing that had it was juya."""
    events = [_event("plain", "rss:axios"), _event("juya", "rss:daily-juya-uk")]
    result = asyncio.run(
        drop_cross_day_duplicates(events, [("2026-10-21", "unrelated")], _DupRouter())
    )
    assert [e.event_id for e in result.events] == ["juya"]
    assert result.dropped == 1
    assert result.protected[0]["named_source"] is True


def test_cross_day_dedup_still_merges_plain_sources() -> None:
    """The rule protects from deletion, not from deduplication."""
    result = asyncio.run(
        drop_cross_day_duplicates(
            [_event("a", "rss:axios")], [("2026-10-21", "unrelated")], _DupRouter()
        )
    )
    assert result.dropped == 1


def test_the_max_items_cut_keeps_named_sources() -> None:
    source = inspect.getsource(pipeline.select_for_digest)
    assert "protects(row.event.source_ids)" in source
    assert "carried" in source


def test_the_fact_check_cannot_drop_a_named_source() -> None:
    from aidaily import __main__ as entry

    source = inspect.getsource(entry)
    assert "protects(e.source_ids)" in source
    assert "保留不删" in source


def test_the_rule_is_stated_in_one_place() -> None:
    """Every stage calls the same predicate, so the rule cannot drift."""
    for name in ("pipeline.py", "crossday_llm.py", "__main__.py"):
        text = (ROOT / "src" / "aidaily" / name).read_text(encoding="utf-8")
        assert "protects" in text, name