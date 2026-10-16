"""Roundups must become the stories they contain.

The user asked why DeepSeek's five-hour outage and its credit giveaway was missing from a
digest that already ingests 橘鸦's feed. It was not ranked low -- **it was never an event**.

`daily.juya.uk` publishes one item per day titled `2026-10-15` whose body holds the whole day:

    要闻
    Claude Code 桌面版更新优化多会话体验 ↗ #1
    模型发布
    TypeSafe AI 更新 Jev，开放图像与长上下文功能 ↗ #3

The collector produced one `RawItem` for the day, so clustering, scoring and the rubric all saw
a single story called `2026-10-15`. No scoring change could have surfaced the outage, because
there was nothing to score.

The numbers in these tests are the measured ones: that body contains 58 numbered headlines and
splits into 29 stories, one of which is `DeepSeek 网页及 API 出现中断`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import RawItem
from aidaily.roundup import looks_like_roundup, split_all, split_roundup

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)

BODY = """AI 早报 2026-10-15

视频版：YouTube ｜ 哔哩哔哩

概览

要闻

Claude Code 桌面版更新优化多会话体验 ↗ #1
Claude Code 新增闲置会话自动压缩 ↗ #2

模型发布

TypeSafe AI 更新 Jev，开放图像与长上下文功能 ↗ #3
SpaceXSI 发布端到端语音模型 Grok Voice 3.0 ↗ #4
蚂蚁百灵开源 Ling-3.1-flash 模型 ↗ #5
昆仑万维发布并开源 Matrix-Game 4.0 ↗ #6

行业动态

DeepSeek 网页及 API 出现中断 ↗ #29
据报道，DeepSeek 将领投机器人 AI 公司种子轮 ↗ #27
"""


def roundup(title: str = "2026-10-15", body: str = BODY) -> RawItem:
    return RawItem(
        source_id="rss:daily-juya-uk", title=title,
        url="https://daily.juya.uk/issues/2026-10-15/",
        published_at=NOW, summary=body[:360], content_text=body,
        author=None, language="zh", metrics={},
        native_id="https://daily.juya.uk/issues/2026-10-15/",
    )


# =============================== detection =======================================
def test_a_dated_item_with_numbered_headlines_is_a_roundup() -> None:
    assert looks_like_roundup(roundup())


def test_a_normal_article_is_not_a_roundup() -> None:
    """The title has to be a bare date. An article that quotes `#1` keeps its own title."""
    item = roundup(title="DeepSeek 发布 V4，性能提升 30%")
    assert not looks_like_roundup(item)


def test_a_date_titled_item_with_too_few_headlines_is_not_shredded() -> None:
    """A false positive turns one story into many; a false negative leaves it as one item.

    So the bar is a *run* of numbered headlines, not one or two.
    """
    thin = "2026-10-15\n\n只有一条 ↗ #1\n另一条 ↗ #2\n"
    assert not looks_like_roundup(roundup(body=thin))


# =============================== splitting =======================================
def test_the_deepseek_outage_becomes_its_own_story() -> None:
    """The measured case. `#29 DeepSeek 网页及 API 出现中断` was inside the roundup and never
    became an event, so no amount of scoring work could have surfaced it."""
    parts = split_roundup(roundup())
    titles = [p.title for p in parts]
    assert any("DeepSeek" in t and "中断" in t for t in titles), titles


def test_every_headline_becomes_one_item() -> None:
    parts = split_roundup(roundup())
    assert len(parts) == 8
    assert parts[0].title == "Claude Code 桌面版更新优化多会话体验"
    assert parts[-1].title.startswith("据报道，DeepSeek")


def test_section_headings_do_not_become_stories() -> None:
    """`要闻` and `模型发布` are structure, and emitting them would put empty rows in the
    digest under a heading's name."""
    titles = [p.title for p in split_roundup(roundup())]
    for heading in ("要闻", "模型发布", "行业动态", "概览"):
        assert heading not in titles


def test_the_roundup_is_kept_as_the_citation() -> None:
    """Text extraction drops the outgoing href, so the reference a reader can follow and
    verify is the roundup itself at the story's number."""
    parts = split_roundup(roundup())
    assert all(p.url.startswith("https://daily.juya.uk/issues/2026-10-15/#") for p in parts)
    assert all(p.metrics["roundup_of"].endswith("2026-10-15/") for p in parts)


def test_the_index_is_recorded() -> None:
    """The audit trail must show a story came out of a roundup, and where in it."""
    parts = {p.title: p for p in split_roundup(roundup())}
    deepseek = next(p for t, p in parts.items() if "中断" in t)
    assert deepseek.metrics["roundup_index"] == 29


def test_a_non_roundup_is_returned_unchanged() -> None:
    """`split_roundup` is always safe to map over every collected item -- it must not drop one
    and must not need a special case at the call site."""
    item = roundup(title="DeepSeek 发布 V4")
    assert split_roundup(item) == [item]


def test_a_body_with_no_headlines_still_returns_the_item() -> None:
    item = roundup(body="2026-10-15\n\n正文没有任何编号标题。\n")
    assert split_roundup(item) == [item]


def test_split_all_leaves_ordinary_items_alone() -> None:
    ordinary = roundup(title="DeepSeek 发布 V4")
    out = split_all([ordinary, roundup()])
    assert len(out) == 1 + 8
    assert out[0] is ordinary


def test_duplicate_headlines_are_emitted_once() -> None:
    """A roundup that repeats a headline (some do, in a "seen elsewhere" section) must not
    produce two identical events for L2 to merge immediately."""
    body = "2026-10-15\n\n" + "\n".join(
        f"重复的标题内容在这里 ↗ #{n}" for n in range(1, 7)
    )
    assert len(split_roundup(roundup(body=body))) == 1
