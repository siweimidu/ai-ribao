"""A bare mention of AI in the body must not carry a non-AI story.

The body fallback exists for digest feeds that title an issue by its date: the headline has no
AI vocabulary but the body does, so the body is consulted. It lifted whenever the body scored
higher -- and a climate story whose facts mentioned 「AI 与气候方程」 once scored 0.50, enough to
publish in an AI digest.

Measured 2026-10-27:

    MIT 在 2026 纽约气候周对接全球气候网络   focus published at 0.50
      headline alone        0.18
      _CORE/_LABS match     none
      _AI_SUBJECT/_PHRASE   none
      AI content in facts   one phrase

The fallback now needs a structural signal in the body -- a model name, a lab, or a technique
word -- rather than the letters `AI`. A real digest issue names its subjects; a climate article
names climate.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from aidaily.focus import focus_multiplier
from aidaily.models import Event, NormalizedItem

NOW = datetime.now(timezone.utc)


def _item(item_id: str, text: str) -> NormalizedItem:
    title = text[:80]
    return NormalizedItem(
        item_id=item_id,
        source_id="rss:x",
        title=title,
        title_norm=title,
        url=f"https://example.com/{item_id}",
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        simhash=0,
        content_text=text,
        summary=text[:300],
    )


def _event(title: str, item: NormalizedItem) -> Event:
    return Event(
        event_id="e",
        title=title,
        member_item_ids=[item.item_id],
        primary_item_id=item.item_id,
        source_ids=["rss:x"],
        all_urls=[item.url],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def _focus(title: str, body: str) -> float:
    item = _item("i", body)
    _, comp = focus_multiplier(
        _event(title, item), None, items_by_id={item.item_id: item}
    )
    return float(comp["focus"])


def test_a_non_ai_story_with_one_ai_mention_is_rejected() -> None:
    """The exact 2026-10-27 case."""
    body = (
        "MIT 在 2026 纽约气候周期间组织了 14 场活动，吸引超过 700 名参会者。"
        "议题涵盖数据中心、超级污染物与气候创新。"
        "副校长 Evelyn Wang 在开幕式讨论了 AI 与气候方程。"
        "MIT 与 Bezos Earth Fund 联合举办了气候创新活动。"
    )
    assert _focus("MIT 在 2026 纽约气候周对接全球气候网络", body) < 0.50


def test_a_real_digest_entry_still_lifts() -> None:
    """The fallback must keep working for what it was built for."""
    body = (
        "本期要闻：OpenAI 发布 GPT-6，上下文窗口扩至 400 万 token。"
        "Anthropic 同期发布 Claude 5.5，重点改进工具调用。"
        "DeepSeek 开源新的 MoE 模型权重。"
    )
    assert _focus("DailyDawn · 2026-10-15", body) >= 0.50


def test_a_body_naming_a_lab_lifts() -> None:
    body = "Anthropic 的新模型在 SWE-bench 上取得最高分，并开放了权重。"
    assert _focus("2026-10-15", body) >= 0.50


def test_the_headline_path_is_unaffected() -> None:
    """A title that names a model never needed the body."""
    assert _focus("OpenAI releases GPT-6", "irrelevant body") >= 0.50