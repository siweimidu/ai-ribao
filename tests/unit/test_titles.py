"""Title-quality gate.

A real digest put `2026-10-14` at position 3, because the entry was a daily-archive feed
whose *item title is its publication date* and whose body is a whole day of news. It won on
substance — the container holds more text than any article in the digest — so no weight
tuning would have caught it.

The rule is narrow on purpose. It rejects a title only when the title is *provably* not a
title; a short headline is not evidence ("Grok 5" is a title, and a four-character Chinese
headline is normal). A broad "low information" heuristic would punish exactly the terse,
high-signal headlines this digest exists to surface.
"""

from __future__ import annotations

import pytest

from aidaily.titles import is_title_like, title_quality


# =============================== dates as titles =================================
@pytest.mark.parametrize("title", [
    "2026-10-14",
    "2026/10/14",
    "2026.10.14",
    "20261014",
    "10-14",
    "10/14",
    "2026-10-14 09:30",
    "2026-10-14 09:30:45",
    "[2026-10-14]",
    "(2026-10-14)",
    "Oct 14, 2026",
    "  2026-10-14  ",
])
def test_a_bare_date_is_not_a_title(title: str) -> None:
    assert not is_title_like(title), f"{title!r} is a container, not a story"
    assert title_quality(title) < 0.5


# =============================== container labels =================================
@pytest.mark.parametrize("title", [
    "RSS", "feed", "index", "首页", "归档", "每日归档", "untitled", "无标题", "更多",
])
def test_a_container_label_is_not_a_title(title: str) -> None:
    assert not is_title_like(title)


def test_punctuation_only_is_not_a_title() -> None:
    assert not is_title_like("—")
    assert not is_title_like("···")
    assert not is_title_like("")


# =============================== the narrowness is the point ======================
@pytest.mark.parametrize("title", [
    "Grok 5",                                  # terse but real
    "Gemini 4 Argon for Robotics",
    "英伟达发布新芯片",                            # 8 Chinese characters
    "AI",
    "GPT-6",
    "2026 年的 AI 监管",                          # contains a year but is a headline
    "Qwen 3 发布：8 月 14 日开放",                  # contains a date but is a headline
    "Sora 2",
    "为什么 10-14 这天的发布会很重要",                 # the date is part of a sentence
])
def test_real_titles_are_kept(title: str) -> None:
    """A broad heuristic here would drop the terse headlines the digest wants most."""
    assert is_title_like(title), f"{title!r} is a legitimate title"
    assert title_quality(title) == 1.0


def test_a_short_title_is_not_treated_as_low_information() -> None:
    """Length is deliberately not a signal. "AI" is a title; a long container label is not."""
    assert is_title_like("AI")
    assert not is_title_like("2026-10-14")
    assert len("2026-10-14") > len("AI"), "length would have given the wrong answer both ways"


# =============================== demote, never drop ===============================
def test_demotion_still_leaves_the_entry_rankable() -> None:
    """The digest's hard constraint is not losing sources, so a bad title must lower the
    score without removing the entry."""
    assert 0.0 < title_quality("2026-10-14") < 1.0
    assert title_quality("2026-10-14") >= 0.1


def test_the_date_container_ranks_below_a_real_story() -> None:
    """The actual failure, as a regression test.

    Scored with the real numbers from the run that shipped it: the container had
    substance 1.0, source weight 1.2 and recency 0.955; the story had substance 1.0,
    weight 1.2 and recency 0.858. Without the title gate the container won.
    """
    from datetime import datetime, timedelta, timezone

    from aidaily.models import Event, NormalizedItem, SourceSpec
    from aidaily.rank import RankWeights, score_event

    now = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
    spec = SourceSpec(
        source_id="rss:juya", name="juya", url="https://j.example/f",
        normalized_url="https://j.example/f", domain="j.example", category="digest",
        source_type="rss", adapter="RssFetcher", found_in=["r:f#k"], repositories=["r"],
    )
    sources = {"rss:juya": spec}
    weights = {"digest": 1.2}

    def build(item_id: str, title: str, published: datetime) -> tuple[Event, NormalizedItem]:
        body = "x" * 900
        item = NormalizedItem(
            item_id=item_id, source_id="rss:juya", title=title, title_norm=title.lower(),
            url=f"https://j.example/{item_id}", published_at=published, fetched_at=now,
            first_seen_at=now, updated_at=now, summary=body[:400], content_text=body,
            content_sha256="h", simhash=1, metrics={},
        )
        event = Event(
            event_id=f"e-{item_id}", title=title, member_item_ids=[item_id],
            primary_item_id=item_id, source_ids=["rss:juya"],
            all_urls=[f"https://j.example/{item_id}"], independent_source_count=1,
            first_seen_at=now, last_updated_at=now, published_range=(published, published),
            evidence_level="single_source",
        )
        return event, item

    container_event, container_item = build("c", "2026-10-14", now - timedelta(minutes=30))
    story_event, story_item = build("s", "Redesigning source control at Anthropic", now - timedelta(hours=2))
    by_id = {container_item.item_id: container_item, story_item.item_id: story_item}
    rank = RankWeights()

    container = score_event(container_event, by_id, sources, weights, rank, now)
    story = score_event(story_event, by_id, sources, weights, rank, now)

    assert container.components["substance"] == story.components["substance"] == 1.0
    assert container.components["h_freshness"] > story.components["h_freshness"], "it was fresher too"
    assert story.score > container.score, "the real story must win"
    assert container.components["title_quality"] < 1.0
    assert story.components["title_quality"] == 1.0
