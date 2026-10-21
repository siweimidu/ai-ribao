"""A sports result with an `#ai模型` tag is not AI news.

Reported from the live site on 2026-10-21:

    #斯图加特 #马德里竞技 #ai足球 #ai模型 #欧冠 - 新浪网

was entry 54 of the issue, labelled 单一来源 · news.google.com, with the text
"本条未调用大模型，内容为来源原文摘录". A football headline reached the digest because the
hashtag `#ai模型` contains 模型, which is a core AI term.

The rule added is narrow on purpose. A football result and a lab analysing football are
different stories, and the obvious version of this fix deleted both.
"""

from __future__ import annotations

import pytest

from aidaily.focus import _headline_focus
from aidaily.pipeline import MIN_AI_RELEVANCE


@pytest.mark.parametrize(
    "title",
    [
        "#斯图加特 #马德里竞技 #ai足球 #ai模型 #欧冠 - 新浪网",
        "欧冠决赛前瞻：AI 模拟预测比分",
        "世界杯赛程公布，球迷热议",
    ],
)
def test_a_sports_story_does_not_reach_the_ai_floor(title: str) -> None:
    """The case that shipped: hashtags carrying `ai` are not a subject."""
    assert _headline_focus(title) < MIN_AI_RELEVANCE, _headline_focus(title)


@pytest.mark.parametrize(
    "title",
    [
        "Google DeepMind 用 AI 分析足球战术",
        "OpenAI 与 NBA 达成合作，用 AI 生成比赛集锦",
        "DeepSeek 发布 V4.1-Flash-1017",
        "Anthropic 发布 Claude Opus 5.5",
    ],
)
def test_real_ai_news_that_mentions_a_sport_is_kept(title: str) -> None:
    """The fix must not delete an AI story because it involves a team or a match.

    The first version added 足球/欧冠 to the off-topic list without asking what else was in the
    headline, and `Google DeepMind 用 AI 分析足球战术` fell to 0.63 -- under the 0.7 floor.
    """
    assert _headline_focus(title) >= MIN_AI_RELEVANCE, _headline_focus(title)


def test_the_sports_term_dilutes_rather_than_vetoes() -> None:
    """A score above zero: this is a demotion, not a blacklist."""
    score = _headline_focus("#斯图加特 #马德里竞技 #ai足球 #ai模型 #欧冠 - 新浪网")
    assert score > 0.0, "an off-topic story should be demoted, not zeroed"
    assert score < 0.5, score
