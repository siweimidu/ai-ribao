"""Identical headlines are decided without the model.

Measured over eight issues: three cross-day repeats, every one differing only in the outlet
suffix or the quote characters.

    10-27 <- 10-26  让 AI 从需求一路干到上线，软件开发组织要变了？
    10-29 <- 10-28  当 AI 智能体代表用户行动时，企业治理将面临哪些新问题？
    10-29 <- 10-27  人脑为何比AI更灵活？国科大师生团队破解底层奥秘

The model is asked to judge differently worded headlines describing one event, and it
sometimes says no. For identical text there is nothing to judge, so the check runs first and
without a provider.

A similarity threshold was measured and rejected: the true duplicate `Genie 4` scores 0.167
against its republication, while 31 unrelated adjacent-day pairs score 0.30 or higher.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.crossday_llm import _norm_title, drop_cross_day_duplicates
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


class _SilentRouter:
    """A model that finds nothing -- the case the backstop exists for."""

    async def complete_json(self, messages, **kwargs):
        return {"duplicates": []}


def _event(title: str, *sources: str) -> Event:
    return Event(
        event_id=title[:8],
        title=title,
        member_item_ids=["m"],
        primary_item_id="m",
        source_ids=list(sources) or ["rss:infoq-cn"],
        all_urls=["https://example.com/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_the_outlet_suffix_and_punctuation_are_ignored() -> None:
    a = _norm_title("让 AI 从需求一路干到上线，软件开发组织要变了？ - InfoQ-CN")
    b = _norm_title("让 AI 从需求一路干到上线，软件开发组织要变了？")
    assert a == b


def test_an_identical_headline_is_dropped_even_when_the_model_finds_nothing() -> None:
    events = [_event("让 AI 从需求一路干到上线，软件开发组织要变了？")]
    earlier = [("2026-10-26", "让 AI 从需求一路干到上线，软件开发组织要变了？ - InfoQ-CN")]
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, _SilentRouter()))
    assert result.dropped == 1
    assert result.exact == 1
    assert result.events == []


def test_a_different_headline_is_left_to_the_model() -> None:
    events = [_event("谷歌发布世界模型，AI创造的世界可进入")]
    earlier = [("2026-10-28", "Google DeepMind 发布 Genie 4 世界模型")]
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, _SilentRouter()))
    assert result.dropped == 0
    assert result.exact == 0


def test_a_named_source_is_not_dropped_even_on_an_exact_match() -> None:
    """「不能删除任何一条」 outranks the duplicate check."""
    events = [_event("同一条标题", "rss:daily-juya-uk")]
    earlier = [("2026-10-26", "同一条标题")]
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, _SilentRouter()))
    assert result.dropped == 0


def test_it_runs_without_a_provider() -> None:
    events = [_event("同一条标题")]
    earlier = [("2026-10-26", "同一条标题")]
    result = asyncio.run(drop_cross_day_duplicates(events, earlier, None))
    assert result.exact == 1
    assert result.events == []