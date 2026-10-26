"""AI named as the subject must not be capped below the relevance floor.

## The bug

The bare-`AI` cap was a flat 0.40 -- under the 0.50 floor. Any headline that named AI as its
subject but no product or technique was cut to 0.40 and then dropped by the gate. Measured
2026-10-26: eight published stories sat at exactly 0.50, and the local run rejected eleven more
at 0.40 --

    Apollo 经济学家称 AI 对科技行业外的多数公司财务回报为零
    塔勒布：白领中产梦将被 AI 重创
    AI 降低攻击成本改变软件安全逻辑
    Ethan Mollick 谈用 AI 要更敢想

That is the "sources plentiful, entries few" complaint: industry analysis, policy and
commentary are exactly the stories that name AI without naming a model.

## The distinction

`AI` as a **subject** (standalone token, or in subject position) == an AI story, capped at the
floor. `AI` as a **feature** ("a Mac budgeting app whose AI models run on-device") == not an AI
story, capped below it. The old rule could not tell those apart.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.focus import focus_multiplier
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _event(title: str) -> Event:
    return Event(
        event_id="e",
        title=title,
        member_item_ids=["m"],
        primary_item_id="m",
        source_ids=["s"],
        all_urls=["https://example.com/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def _focus(title: str) -> float:
    _, comp = focus_multiplier(_event(title), None)
    return float(comp["focus"])


def test_ai_as_the_subject_stays_at_the_floor() -> None:
    """These were cut to 0.40 and dropped."""
    for title in (
        "Apollo 经济学家称 AI 对科技行业外的多数公司财务回报为零",
        "塔勒布：白领中产梦将被 AI 重创",
        "AI 降低攻击成本改变软件安全逻辑",
        "Ethan Mollick 谈用 AI 要更敢想",
    ):
        assert _focus(title) >= 0.50, title


def test_non_ai_content_stays_below_the_floor() -> None:
    """The gate must still reject what it was built for."""
    for title in (
        "Even the best mesh Wi-Fi system can be improved with a simple cable",
        "Dolly Parton Imagination Library",
        "A 3D Printed Marble Clock but it is Scrolling Text",
        "Build a Swashplate-less Helicopter Rotor",
    ):
        assert _focus(title) < 0.50, title


def test_a_named_model_is_unaffected() -> None:
    """`_CORE`/`_LABS` matches never reached the cap; they must still not."""
    assert _focus("OpenAI releases GPT-6") >= 0.50
    assert _focus("Kimi K3.1 Pro 发布") >= 0.50


def test_ai_brand_names_do_not_count_as_the_subject() -> None:
    """`OpenAI` contains `AI`; the standalone-token pattern must not match it."""
    from aidaily.focus import _AI_SUBJECT

    assert not _AI_SUBJECT.search("OpenAI ships a new API")
    assert not _AI_SUBJECT.search("AI-powered budgeting app")
    assert _AI_SUBJECT.search("塔勒布：白领中产梦将被 AI 重创")