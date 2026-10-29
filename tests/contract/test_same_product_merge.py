"""One product launch is one entry.

Measured 2026-10-29: `Gemini 4 Carbon` occupied three positions -- the launch, its benchmark
placement, and a hands-on video. On 2026-10-28 `LFM3` appeared twice, once in English and once
in Chinese. The reader sees the same launch repeatedly and the count overstates the day.

Nothing is deleted: absorbed entries contribute their member items, sources and URLs, and their
headlines are recorded in `merged_titles`, so the card still links to every report --
「只能去重并标注多源验证」.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.pipeline import _merge_same_product, _product_tokens

NOW = datetime.now(timezone.utc)


class _Row:
    def __init__(self, event: Event) -> None:
        self.event = event


def _row(title: str, *sources: str) -> _Row:
    return _Row(
        Event(
            event_id=title[:10],
            title=title,
            member_item_ids=[title[:10]],
            primary_item_id=title[:10],
            source_ids=list(sources) or ["rss:x"],
            all_urls=[f"https://example.com/{abs(hash(title)) % 9999}"],
            first_seen_at=NOW,
            last_updated_at=NOW,
        )
    )


def test_the_token_keeps_the_variant() -> None:
    assert _product_tokens("谷歌发布 Gemini 4 Carbon，登顶") == {"gemini4carbon"}
    assert _product_tokens("Gemini 4 Pro 上线") == {"gemini4pro"}


def test_three_angles_on_one_launch_become_one_entry() -> None:
    rows = [
        _row("谷歌发布 Gemini 4 Carbon，登顶 Artificial Analysis"),
        _row("Gemini 4 Carbon 登顶 Arena 文本榜", "rss:arena"),
        _row("Gemini 4 Carbon 预览版发布早期实测视频", "rss:youtube"),
    ]
    merged = _merge_same_product(rows)
    assert merged == 2
    assert len(rows) == 1
    kept = rows[0].event
    assert set(kept.source_ids) == {"rss:x", "rss:arena", "rss:youtube"}
    assert len(kept.all_urls) == 3
    assert len(kept.unique_facts["merged_titles"]) == 2
    assert kept.independent_source_count == 3


def test_english_and_chinese_coverage_of_one_model_merge() -> None:
    rows = [
        _row("Liquid AI Releases LFM3: 6 Open-Weight Models"),
        _row("Liquid AI 发布 LFM3，六个 2B 级开放权重多模态模型", "rss:daily-juya-uk"),
    ]
    assert _merge_same_product(rows) == 1
    assert len(rows) == 1


def test_two_different_products_are_not_merged() -> None:
    rows = [_row("Gemini 4 Carbon 发布"), _row("LFM3 开源", "rss:y")]
    assert _merge_same_product(rows) == 0
    assert len(rows) == 2


def test_a_named_source_survives_the_merge() -> None:
    """「不能删除任何一条」: the entry stays, it is only folded together."""
    rows = [
        _row("Gemini 4 Carbon 发布"),
        _row("Gemini 4 Carbon 实测", "rss:daily-juya-uk"),
    ]
    _merge_same_product(rows)
    assert len(rows) == 1
    assert "rss:daily-juya-uk" in rows[0].event.source_ids


def test_nothing_to_do_returns_zero() -> None:
    assert _merge_same_product([]) == 0
    assert _merge_same_product([_row("Gemini 4 Carbon 发布")]) == 0