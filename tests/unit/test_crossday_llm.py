"""Cross-day dedup by model, over the whole seven-day window.

「去重七天内所有资讯，去重交给llm的API来做」

## What the deterministic path missed

Measured 2026-10-25 against the previous six issues, 14 of 120 entries repeated something:

    0.71  Kling 4.0 在 fal 上线并向所有客户开放 API
            [10-24] 可灵 Kling 4.0 上线 fal 平台并开放 API
    0.69  Cohere 发布 Rerank 5 企业检索重排模型，分 Pro 与 Fast 两档
            [10-22] Cohere 发布 Rerank 5 重排序模型
    0.61  Cognition 推出 Devin Oncall，协助诊断和解决生产事故
            [10-24] Cognition 推出焕新版 Devin Desktop

The difference is vocabulary -- 可灵/Kling, 上线/推出, one names the platform and the other
the model. A threshold loose enough to merge those also merges genuinely different releases.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.crossday_llm import CrossDayResult, drop_cross_day_duplicates
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


class _Scripted:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def complete_json(self, messages, **kw):
        self.calls += 1
        return self.answer


def test_a_repeat_in_other_words_is_dropped() -> None:
    """The whole reason this pass exists."""
    events = [_event(0, "Kling 4.0 在 fal 上线并向所有客户开放 API")]
    earlier = [("2026-10-24", "可灵 Kling 4.0 上线 fal 平台并开放 API")]
    router = _Scripted({"duplicates": [{"today": "T0", "earlier": "E0", "why": "同一款"}]})
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, router))
    assert result.dropped == 1
    assert not result.events


def test_an_unmentioned_event_survives() -> None:
    """A partial answer costs nothing; a wrong one costs a hidden story."""
    events = [_event(0, "A"), _event(1, "B"), _event(2, "C")]
    earlier = [("2026-10-24", "A")]
    router = _Scripted({"duplicates": [{"today": "T1", "earlier": "E0", "why": "same"}]})
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, router))
    assert [e.title for e in result.events] == ["A", "C"]


def test_an_invented_id_is_ignored() -> None:
    """The model must not be able to remove something it was not shown."""
    events = [_event(0, "A")]
    earlier = [("2026-10-24", "B")]
    router = _Scripted({"duplicates": [{"today": "T99", "earlier": "E0", "why": "x"}]})
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, router))
    assert result.dropped == 0 and len(result.events) == 1


def test_no_model_means_no_drop_and_no_crash() -> None:
    events = [_event(0, "A")]
    result = asyncio.run(drop_cross_day_duplicates(events, [("2026-10-24", "A")], None))
    assert result.failed and len(result.events) == 1


def test_no_history_means_no_call() -> None:
    events = [_event(0, "A")]
    router = _Scripted({"duplicates": []})
    result = asyncio.run(drop_cross_day_duplicates(events, [], router))
    assert router.calls == 0 and len(result.events) == 1


def test_earlier_headlines_are_chunked() -> None:
    """Seven days is ~700 headlines; one prompt would be enormous."""
    events = [_event(0, "A")]
    earlier = [("2026-10-24", f"历史 {i}") for i in range(250)]
    router = _Scripted({"duplicates": []})
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, router, chunk=100))
    assert result.chunks == 3


def test_a_hanging_provider_costs_the_dedup_not_the_issue() -> None:
    class Hanging:
        async def complete_json(self, messages, **kw):
            await asyncio.sleep(60)

    events = [_event(0, "A")]
    result = asyncio.run(
        drop_cross_day_duplicates(events, [("2026-10-24", "A")], Hanging(), timeout_s=1.0)
    )
    assert result.failed
    assert len(result.events) == 1


def test_the_label_says_what_happened() -> None:
    assert "未运行" in CrossDayResult(events=[], failed=True).label
    assert CrossDayResult(events=[]).label == "无重复"
    assert "剔除 3" in CrossDayResult(events=[], dropped=3).label