"""A date-only title is not evidence that a story is not about AI.

dailydawn titles an issue by its date: `DailyDawn · 2026-10-15`. Measured against the corpus:

  raw items from dailydawn: 30   (each carrying ~21000 characters of AI analysis)
  items in published issues: 0

`_headline_focus` reads the title, found no lab, no model and no technique word, and returned
0.18. The relevance floor is 0.50, so every dailydawn story was dropped before scoring -- not
because it was bad, but because its title was a date.

The body fallback fixes that, and these tests pin the three things that had to be right at once:

1. the body is consulted when the title carries no signal;
2. the body can *raise* the headline, never lower it;
3. the bare-`AI` cap follows the evidence -- testing `event.title` unconditionally re-capped
   every body-derived score back to 0.40, below the floor, which made (1) change nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.focus import focus_multiplier
from aidaily.models import Event, NormalizedItem

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)

#: A real dailydawn opening: labs, models and a technique noun in the first lines.
AI_BODY = (
    "DailyDawn · 2026-10-15 今天登榜GitHub Trending的 tools 拿到 947 星，可直接把 AI 编码代理的"
    "工具输出体积压缩 98%。Anthropic 以研究预览形式开放 Claude Duet，一款让 Claude 作为主动式"
    "智能体工作的独立应用。OpenAI 称其 GPT-5.6 Sol 模型协助研究者发现 PHP 核心严重漏洞。"
)

#: A body with no AI vocabulary at all.
PLAIN_BODY = "今天整理了三个笔记应用的快捷键，并比较了它们的同步延迟与导出格式。"


def _item(body: str) -> NormalizedItem:
    return NormalizedItem(
        item_id="i1",
        source_id="rss:dailydawn-feed-xml",
        title="DailyDawn · 2026-10-15",
        url="https://dailydawn.dev/zh/2026-10-15",
        canonical_url="https://dailydawn.dev/zh/2026-10-15",
        content_text=body,
        summary="",
        language="zh",
        published_at=NOW,
        first_seen_at=NOW,
        fetched_at=NOW,
        updated_at=NOW,
        title_norm="dailydawn",
        content_sha256="x",
        simhash=0,
    )


def _event() -> Event:
    return Event(
        event_id="e1",
        primary_item_id="i1",
        title="DailyDawn · 2026-10-15",
        member_item_ids=["i1"],
        source_ids=["rss:dailydawn-feed-xml"],
        all_urls=[],
        first_seen_at=NOW,
        last_updated_at=NOW,
        independent_source_count=1,
    )


def test_a_date_only_title_scores_low_on_its_own() -> None:
    """The behaviour that caused the drop, asserted so the fix has a baseline."""
    _, components = focus_multiplier(_event(), sources={})
    assert components["focus"] < 0.5


def test_the_body_lifts_a_date_only_title_above_the_floor() -> None:
    _, components = focus_multiplier(
        _event(), sources={}, items_by_id={"i1": _item(AI_BODY)}
    )
    assert components["focus"] >= 0.5, components


def test_a_body_with_no_ai_content_does_not_lift_anything() -> None:
    """The fallback reads what the text says, not merely that text exists."""
    _, without = focus_multiplier(_event(), sources={})
    _, with_plain = focus_multiplier(
        _event(), sources={}, items_by_id={"i1": _item(PLAIN_BODY)}
    )
    assert with_plain["focus"] <= without["focus"] + 0.01, (without, with_plain)


def test_the_body_never_lowers_a_strong_title() -> None:
    """A certain headline is left alone; only a weak one is lifted."""
    event = _event()
    event.title = "Anthropic 发布 Claude Opus 5.5"
    _, bare = focus_multiplier(event, sources={})
    _, with_body = focus_multiplier(
        event, sources={}, items_by_id={"i1": _item(PLAIN_BODY)}
    )
    assert with_body["focus"] == bare["focus"]
