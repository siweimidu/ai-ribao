"""Two reports of one event, decided pair by pair.

Measured 2026-10-30, both published as separate rows on the page:

    #01  Mistral 发布 1 万亿参数 Mistral Large 4 权重
    #02  Mistral 发布万亿参数模型权重以应对网络安全

    #06  Anthropic 研究：专家 86% 采纳 AI 随机偏好
    #07  Anthropic研究：专家误认AI随机观点为自身见解

One outlet named the product, the other described it. The bucketed merge pass asks the model to
search a list and it missed both. This pass asks about one pair at a time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.pair_merge import candidate_pairs, review_pairs

NOW = datetime.now(timezone.utc)


def _event(event_id: str, title: str, *sources: str) -> Event:
    return Event(
        event_id=event_id,
        title=title,
        member_item_ids=[event_id],
        primary_item_id=event_id,
        source_ids=list(sources) or ["rss:x"],
        all_urls=[f"https://example.com/{event_id}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


class _Judge:
    """Says yes for a chosen pair, no for everything else."""

    def __init__(self, say_yes: bool = True) -> None:
        self.say_yes = say_yes
        self.asked = 0

    async def complete_json(self, messages, **kwargs):
        self.asked += 1
        return {"same": self.say_yes, "why": "test"}


class _Broken:
    async def complete_json(self, messages, **kwargs):
        raise RuntimeError("provider down")


THE_PAIR = (
    _event("a", "Mistral 发布 1 万亿参数 Mistral Large 4 权重"),
    _event("b", "Mistral 发布万亿参数模型权重以应对网络安全", "rss:techcrunch"),
)


def test_the_measured_pair_is_a_candidate() -> None:
    assert candidate_pairs(list(THE_PAIR)) == [(0, 1)]


def test_an_unrelated_headline_is_not_paired() -> None:
    events = [
        _event("a", "Mistral 发布 1 万亿参数 Mistral Large 4 权重"),
        _event("c", "OpenAI 更新 Model Spec，确立五项核心价值观"),
    ]
    assert candidate_pairs(events) == []


def test_a_pair_the_model_accepts_is_folded() -> None:
    events, report = asyncio.run(review_pairs(list(THE_PAIR), _Judge(True)))
    assert len(events) == 1
    assert report["merged"] == 1
    kept = events[0]
    assert set(kept.source_ids) == {"rss:x", "rss:techcrunch"}
    assert len(kept.all_urls) == 2
    assert kept.unique_facts["merged_titles"] == ["Mistral 发布万亿参数模型权重以应对网络安全"]


def test_a_pair_the_model_rejects_is_left_alone() -> None:
    events, report = asyncio.run(review_pairs(list(THE_PAIR), _Judge(False)))
    assert len(events) == 2
    assert report["merged"] == 0


def test_a_provider_failure_never_costs_a_story() -> None:
    events, report = asyncio.run(review_pairs(list(THE_PAIR), _Broken()))
    assert len(events) == 2
    assert report["failed"] is True


def test_no_router_means_no_change() -> None:
    events, report = asyncio.run(review_pairs(list(THE_PAIR), None))
    assert len(events) == 2
    assert report["failed"] is True


def test_the_questions_are_bounded() -> None:
    """A name carried by many events is not evidence, so it produces no pairs."""
    events = [_event(f"e{i}", f"OpenAI 发布第 {i} 项更新") for i in range(8)]
    assert candidate_pairs(events) == []