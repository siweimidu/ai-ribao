"""Words that describe any software must not certify a story as AI.  

Measured 2026-10-24: the GitHub Trending row
`Renhuai123/ziwei-doushu — 紫微斗数开源排盘引擎` scored `focus: 1.0`, the same as
`Anthropic 发布 Claude 5.5`, and was published as entry 36 of the issue. A repository is open
source regardless of subject, so `开源` proves nothing on its own.

There was a second bug hiding behind the first: `_CORE` contains one capture group, and
`findall` returns the *group* rather than the match when a pattern has groups -- so every hit
read as `""` and the context filter saw no words at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.focus import _CONTEXT_DEPENDENT, focus_multiplier
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _focus(title: str) -> float:
    event = Event(
        event_id="e",
        title=title,
        member_item_ids=["i"],
        primary_item_id="i",
        source_ids=["scrape:github-com-trending"],
        all_urls=["https://x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )
    return focus_multiplier(event)[0]


def test_a_divination_tool_is_not_ai() -> None:
    """The reported case: `开源` in "开源排盘引擎" is the only token that matched."""
    score = _focus("Renhuai123/ziwei-doushu — 紫微斗数开源排盘引擎")
    assert score < 0.7, f"紫微斗数 scored {score}"


def test_a_podcast_about_drones_is_not_ai() -> None:
    assert _focus("Hackaday Podcast 第392集：微缩、无人机和DIY综述") < 0.7


def test_a_bi_tool_is_not_ai() -> None:
    assert _focus("Amazon QuickSight 地图层地图支持 GeoJSON 点位可视化") < 0.7


def test_a_real_launch_still_scores_full() -> None:
    """The filter must not have muted genuine AI news."""
    assert _focus("Anthropic 发布 Claude 5.5，编程能力大幅提升") >= 0.9
    assert _focus("OpenAI 完成 300 亿美元融资") >= 0.9


def test_context_words_count_when_an_ai_anchor_is_present() -> None:
    """`DeepSeek 开源新模型` is genuinely AI: the lab name makes `开源` meaningful."""
    assert _focus("DeepSeek 开源新模型 V4") >= 0.9
    assert _focus("月之暗面发布 Kimi K3.1 Pro") >= 0.9


def test_the_context_list_holds_only_generic_words() -> None:
    """A lab or model name here would silently disable the check for that vendor."""
    for word in _CONTEXT_DEPENDENT:
        assert word not in {"openai", "anthropic", "claude", "gpt", "kimi", "deepseek"}, word