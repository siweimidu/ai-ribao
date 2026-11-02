"""A story about the market that says "AI" once is not an AI story.

## The bug

2026-11-02 shipped 107 entries, ten of them like these:

    A股午评：创业板指涨超3%，AI漫剧、白酒概念集体爆发，全市场超4700只个股上涨
    美股进入关键一周，AI股还能重新领涨吗？
    原油、AI与债券：过去一个月市场交易格局彻底生变？
    …迎新晚会暨1024程序员节智能之夜圆满落幕
    moomoo AI 打卡 #2

Each names AI, so each cleared the 0.50 relevance floor, which asks "did this headline name
AI" -- and they all do. What separates them is what the headline is *about*.

## The fix

A headline carrying market, campus or campaign vocabulary is capped at 0.32, under the floor,
unless a lab or model name appears (an actual product story about OpenAI and A-shares stays).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.focus import _OFF_TOPIC, focus_multiplier
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _event(title: str) -> Event:
    return Event(
        event_id="e",
        title=title,
        member_item_ids=["i"],
        primary_item_id="i",
        source_ids=["rss:x"],
        all_urls=["https://example.com/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


@pytest.mark.parametrize(
    "title",
    [
        "A股午评：创业板指涨超3%，AI漫剧、白酒概念集体爆发，全市场超4700只个股上涨",
        "美股进入关键一周，AI股还能重新领涨吗？",
        "原油、AI与债券：过去一个月市场交易格局彻底生变？",
        "moomoo AI 打卡 #2",
        "人工智能与计算机学院2026年迎新晚会暨1024程序员节智能之夜圆满落幕",
    ],
)
def test_off_topic_headlines_are_capped_below_the_floor(title: str) -> None:
    assert _OFF_TOPIC.search(title)
    multiplier, detail = focus_multiplier(_event(title))
    assert detail["focus"] <= 0.32
    assert multiplier < 0.5, title


def test_a_real_ai_story_is_not_caught() -> None:
    title = "OpenAI 发布 GPT-6，上下文扩到 200 万 token"
    assert not _OFF_TOPIC.search(title)
    _multiplier, detail = focus_multiplier(_event(title))
    assert detail["focus"] > 0.32