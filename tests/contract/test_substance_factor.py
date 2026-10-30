"""A headline is not a story.

On 2026-10-30 position #02 was 「中国首个 AI 定义芯片诞生」: a Google News re-index whose whole
body is the headline. Its only fact was 「报道标题称…」 and every 不确定 line read 未提及. It
outranked complete stories because substance was reported but never scored.

The factor is bounded -- a thin entry keeps 35% of its score, so it can still appear at the tail
but cannot lead the issue. Nothing is deleted.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from aidaily.config import load_config
from aidaily.models import Event, NormalizedItem
from aidaily.rank import RankWeights, score_event

NOW = datetime.now(timezone.utc)


def _item(body: str) -> NormalizedItem:
    return NormalizedItem(
        item_id="i",
        source_id="rss:x",
        title="中国首个 AI 定义芯片诞生",
        title_norm="中国首个 AI 定义芯片诞生",
        url="https://example.com/a",
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        content_text=body,
        content_sha256=hashlib.sha256(body.encode()).hexdigest(),
        simhash=0,
    )


def _event() -> Event:
    return Event(
        event_id="e",
        title="中国首个 AI 定义芯片诞生",
        member_item_ids=["i"],
        primary_item_id="i",
        source_ids=["rss:x"],
        all_urls=["https://example.com/a"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def _factor(body: str) -> float:
    item = _item(body)
    row = score_event(
        _event(),
        {"i": item},
        {},
        Counter(),
        RankWeights(),
        NOW,
    )
    return float(row.components["substance_factor"])


def test_a_bare_headline_is_penalised() -> None:
    assert _factor("中国首个 AI 定义芯片诞生") < 0.5


def test_a_full_article_is_not() -> None:
    assert _factor("正文" * 400) == 1.0


def test_the_penalty_never_reaches_zero() -> None:
    """Thin entries may sink; they are never deleted by the ranker."""
    assert _factor("") >= 0.35


def test_the_threshold_is_documented() -> None:
    assert RankWeights().substance_thin_chars == 300