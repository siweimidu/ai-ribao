"""A failed analysis is retried once before it becomes a quality drop.

Measured across recent builds: 44/114 and 62/110 events fell back to rule-based excerpts. Those
entries lose their translated headline and their facts, and the page has to move them into the
待翻译 block -- so a transient provider error becomes a visible defect in the issue.

The retry runs slower than the first pass, because the usual cause is a burst of rate limits.
Only events that actually fell back are retried.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from aidaily import analyze as analyze_module
from aidaily.analyze import EventInsight, analyze_events
from aidaily.models import Event, NormalizedItem

NOW = datetime.now(timezone.utc)


def _item() -> NormalizedItem:
    return NormalizedItem(
        item_id="i1",
        source_id="rss:x",
        title="Gemini 4 Carbon",
        title_norm="Gemini 4 Carbon",
        url="https://example.com/a",
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        content_text="body",
        content_sha256=hashlib.sha256(b"body").hexdigest(),
        simhash=0,
    )


def _event() -> Event:
    return Event(
        event_id="e1",
        title="Gemini 4 Carbon",
        member_item_ids=["i1"],
        primary_item_id="i1",
        source_ids=["rss:x"],
        all_urls=["https://example.com/a"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_a_transient_failure_is_retried_and_counted(monkeypatch) -> None:
    calls = {"n": 0}

    async def flaky(router, event, members):
        calls["n"] += 1
        if calls["n"] == 1:
            raise analyze_module.LLMUnavailable("burst")
        return EventInsight(event_id=event.event_id, title="Gemini 4 Carbon 发布")

    monkeypatch.setattr(analyze_module, "analyze_event", flaky)

    insights, warnings = asyncio.run(
        analyze_events([_event()], {"i1": _item()}, router=object())
    )

    assert calls["n"] == 2
    assert insights["e1"].title == "Gemini 4 Carbon 发布"
    assert not insights["e1"].rule_based
    assert any("补跑恢复 1/1 条" in w for w in warnings)


def test_a_persistent_failure_still_reports_the_degraded_count(monkeypatch) -> None:
    async def broken(router, event, members):
        raise analyze_module.LLMUnavailable("down")

    monkeypatch.setattr(analyze_module, "analyze_event", broken)

    insights, warnings = asyncio.run(
        analyze_events([_event()], {"i1": _item()}, router=object())
    )

    assert insights["e1"].rule_based
    assert any("1/1 个事件降级为规则摘录" in w for w in warnings)


def test_a_healthy_run_does_not_retry(monkeypatch) -> None:
    calls = {"n": 0}

    async def fine(router, event, members):
        calls["n"] += 1
        return EventInsight(event_id=event.event_id, title="正常")

    monkeypatch.setattr(analyze_module, "analyze_event", fine)

    _, warnings = asyncio.run(analyze_events([_event()], {"i1": _item()}, router=object()))

    assert calls["n"] == 1
    assert not any("降级" in w for w in warnings)


def test_the_retry_pass_is_bounded(monkeypatch) -> None:
    """An unbounded retry pushed publish past its 40-minute limit on 2026-10-30 and GitHub
    cancelled the job -- the issue never published at all."""
    from aidaily.analyze import RETRY_BUDGET_SECONDS, RETRY_LIMIT

    assert RETRY_LIMIT > 0 and RETRY_LIMIT <= 50
    assert RETRY_BUDGET_SECONDS > 0 and RETRY_BUDGET_SECONDS <= 180

    seen = {"n": 0}

    async def broken(router, event, members):
        seen["n"] += 1
        raise analyze_module.LLMUnavailable("down")

    monkeypatch.setattr(analyze_module, "analyze_event", broken)

    events = []
    items = {}
    for i in range(RETRY_LIMIT + 10):
        item = _item()
        item = item.model_copy(update={"item_id": f"i{i}", "url": f"https://example.com/{i}"})
        items[item.item_id] = item
        events.append(_event().model_copy(
            update={"event_id": f"e{i}", "title": f"T{i}", "member_item_ids": [f"i{i}"],
                    "primary_item_id": f"i{i}", "all_urls": [f"https://example.com/{i}"]}
        ))

    asyncio.run(analyze_events(events, items, router=object()))

    # One first attempt per event, plus at most RETRY_LIMIT retries.
    assert seen["n"] == len(events) + RETRY_LIMIT
