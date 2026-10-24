"""A named-model release leads the issue, and divination is not technology.

Measured 2026-10-24: two failures on the same day.

  1. Moonshot shipped Kimi K3.1 Pro and it was not in the issue at all -- no feed carried it.
     Once collected it would still have ranked by score, and a release carried by one source
     loses to a story carried by four.
  2. `Renhuai123/ziwei-doushu — 紫微斗数开源排盘引擎` shipped as entry 36 with `focus: 1.0`,
     certified by the generic word `开源`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.focus import focus_multiplier
from aidaily.models import Event
from aidaily.pipeline import leads_the_issue

NOW = datetime.now(timezone.utc)


def _focus(title: str) -> float:
    event = Event(
        event_id="e",
        title=title,
        member_item_ids=["i"],
        primary_item_id="i",
        source_ids=["s"],
        all_urls=["https://x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )
    return focus_multiplier(event)[0]


def test_a_named_model_release_leads() -> None:
    """The reported case: Kimi K3.1 Pro shipped and the issue did not carry it."""
    assert leads_the_issue("月之暗面发布 Kimi K3.1 Pro，编程与智能体任务全面升级")
    assert leads_the_issue("Kimi K3.1 Pro 正式上线")


def test_a_verb_between_the_name_and_the_version_still_works() -> None:
    """`DeepSeek 发布 V4` -- one regex over the whole string cannot see them as adjacent."""
    assert leads_the_issue("DeepSeek 发布 V4")


def test_a_mention_without_a_release_verb_does_not_lead() -> None:
    """Commentary on an existing model is ordinary news."""
    assert not leads_the_issue("Kimi K2 实测：效果如何")
    assert not leads_the_issue("Claude 使用技巧分享")


def test_a_funding_round_does_not_lead() -> None:
    assert not leads_the_issue("OpenAI 完成 300 亿美元融资")


def test_divination_is_not_ai() -> None:
    """It shipped as entry 36 with focus 1.0, certified by the generic word 开源."""
    assert _focus("Renhuai123/ziwei-doushu — 紫微斗数开源排盘引擎 — 基于倪海厦天纪体系") < 0.5
    assert _focus("八字排盘工具开源") < 0.5
    assert _focus("塔罗牌占卜小程序上线") < 0.5


def test_a_real_launch_is_untouched_by_the_divination_filter() -> None:
    assert _focus("Anthropic 发布 Claude 5.5，编程能力大幅提升") >= 0.9