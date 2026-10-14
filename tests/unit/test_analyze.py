"""The analysis stage, and the two ways it produced English on a Chinese page.

There was no test file for this module, and a `TypeError` in it reached production: the
digest's publish step crashed, GitHub Actions reported the job as successful (the workflow
runs the command under `set +e` and branches on the exit code), and the site kept serving
the previous issue. The failure surfaced only as "the page did not update".

The bug itself was small -- `analyze_events(limit=None)` compared `len(events) > None` --
but the class of bug is not: this module decides what language the digest is written in, and
nothing was checking it.

Covered here:

* `limit=None` means "everything given", and must not raise;
* a cap below the input still works and does not silently drop the warning;
* the model is asked for Chinese, and the fallback marks a foreign headline as a fallback
  rather than presenting it as the digest's own writing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aidaily.analyze import (
    EventInsight,
    fallback_insight,
    needs_translation,
)
from aidaily.analyze import analyze_events
from aidaily.models import Event, NormalizedItem

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)


def make_item(item_id: str = "i1", title: str = "A title", body: str = "A body") -> NormalizedItem:
    return NormalizedItem(
        item_id=item_id, source_id="rss:s", title=title, title_norm=title.lower(),
        url=f"https://example.com/{item_id}", published_at=NOW, fetched_at=NOW,
        first_seen_at=NOW, updated_at=NOW, summary=body, content_text=body,
        content_sha256="h", simhash=1, metrics={},
    )


def make_event(event_id: str = "e1", item_id: str = "i1", title: str = "A title") -> Event:
    return Event(
        event_id=event_id, title=title, member_item_ids=[item_id], primary_item_id=item_id,
        source_ids=["rss:s"], all_urls=[f"https://example.com/{item_id}"],
        independent_source_count=1, first_seen_at=NOW, last_updated_at=NOW,
        published_range=(NOW, NOW), evidence_level="single_source",
    )


# =============================== the shipped crash ===============================
def test_limit_none_means_everything_and_does_not_raise() -> None:
    """`limit=None` reached `len(list(events)) > limit`, which is a TypeError.

    That exception killed the publish step in production. The workflow ran the command under
    `set +e` and reported success, so the only visible symptom was that the site did not
    change -- the worst kind of failure: silent, and indistinguishable from "nothing to do".
    """
    events = [make_event(f"e{i}", f"i{i}") for i in range(3)]
    by_id = {f"i{i}": make_item(f"i{i}") for i in range(3)}

    insights, warnings = asyncio.run(analyze_events(events, by_id, None, limit=None))
    assert len(insights) == 3, "every event given must be analysed"
    assert any("未配置大模型" in w for w in warnings)


def test_a_cap_still_limits_the_work() -> None:
    events = [make_event(f"e{i}", f"i{i}") for i in range(5)]
    by_id = {f"i{i}": make_item(f"i{i}") for i in range(5)}

    insights, _ = asyncio.run(analyze_events(events, by_id, None, limit=2))
    assert len(insights) == 2


def test_no_router_still_produces_one_insight_per_event() -> None:
    """A degraded digest must still cover every published item, or the page falls back to
    the source's own headline -- which for an English feed is an English sentence."""
    events = [make_event(f"e{i}", f"i{i}") for i in range(4)]
    by_id = {f"i{i}": make_item(f"i{i}") for i in range(4)}

    insights, warnings = asyncio.run(analyze_events(events, by_id, None, limit=None))
    assert set(insights) == {e.event_id for e in events}
    assert all(i.rule_based for i in insights.values())
    assert warnings, "a degraded run must say so"


# =============================== language ========================================
@pytest.mark.parametrize("title", [
    "Google DeepMind and Singapore Government announce new AI tool",
    "Redesigning source control at Anthropic",
    "Show HN: Guitoro, a virtual guitar you strum with your keyboard",
])
def test_a_foreign_headline_is_recognised(title: str) -> None:
    assert needs_translation(title)


@pytest.mark.parametrize("title", [
    "OpenAI 发布 GPT-6",
    "Anthropic 团队开发自研源码控制系统 Scion 代替 Git",
    "Xbow 用 GPT-5.6 挖出 Chrome 三个漏洞",
    "Gemini 4 Argon 全面开放",
    "英伟达将宣布20亿美元欧洲AI新投资",
])
def test_a_chinese_headline_is_not_flagged(title: str) -> None:
    """Real titles mix scripts constantly. A strict "no Latin characters" rule would flag
    every one of these, and flagging them would mean needlessly re-translating the digest."""
    assert not needs_translation(title)


def test_an_empty_title_is_not_flagged() -> None:
    assert not needs_translation("")
    assert not needs_translation("   ")


def test_fallback_marks_a_foreign_headline_as_a_fallback() -> None:
    """There is no translator in this module, so the honest options are the original plus a
    note, or the model's translation. Rendering an English sentence as though it were the
    digest's own writing is the one thing that must not happen."""
    event = make_event(title="Redesigning source control at Anthropic")
    insight = fallback_insight(event, [make_item(title="Redesigning source control at Anthropic")])

    assert insight.rule_based
    assert insight.title == "Redesigning source control at Anthropic", "keep the source's words"
    assert any("未翻译" in u for u in insight.uncertainties), (
        "the reader must be able to tell this is a fallback, not the intended output"
    )


def test_fallback_does_not_add_the_translation_note_for_chinese() -> None:
    event = make_event(title="英伟达发布新芯片")
    insight = fallback_insight(event, [make_item(title="英伟达发布新芯片")])

    assert not any("未翻译" in u for u in insight.uncertainties)
    assert any("未调用大模型" in u for u in insight.uncertainties)


def test_fallback_with_no_member_items_still_returns_something() -> None:
    """Defensive: an event whose items were all dropped must not raise."""
    insight = fallback_insight(make_event(), [])
    assert isinstance(insight, EventInsight)
    assert insight.rule_based


# =============================== prompts =========================================
def test_the_prompt_asks_for_chinese_and_names_the_exceptions() -> None:
    """The digest's rule is Chinese on the page, with proper nouns kept in their original
    form -- "Gemini 4 Argon" transliterated is less readable than the original.

    The instruction has to name the exceptions, because "translate everything" produces
    "奥彭艾" and "翻译 everything" produces English.
    """
    from aidaily.analyze import SYSTEM_PROMPT, USER_TEMPLATE

    assert "简体中文" in SYSTEM_PROMPT
    assert "专有名词保留原文" in SYSTEM_PROMPT
    # The examples are what make the rule concrete for the model.
    for example in ("OpenAI", "Gemini 4 Argon", "Scion"):
        assert example in SYSTEM_PROMPT

    assert "中文" in USER_TEMPLATE
    # And the output schema says so at the point of generation, not only in the system text.
    assert "中文一句话概括" in USER_TEMPLATE


def test_the_prompt_keeps_the_no_links_rule() -> None:
    """Links are backfilled from our own records; a model-written URL is unverifiable."""
    from aidaily.analyze import SYSTEM_PROMPT

    assert "不得写出任何链接" in SYSTEM_PROMPT
