"""Cross-day repetition is removed, not merely demoted.

The user's rule: "之前报道过的消息，不得再次出现，可以检查近一个星期的".

The mechanism that existed could not enforce it, and the failure is measurable in the
archive: 2026-10-16 published "Gemini 4 Argon 向正价 Google AI Pro 用户开放" and 2026-10-17
published "Gemini 4 Argon 向 Google AI Pro 开放". Fingerprints were exact hashes of the whole
headline, so inserting one word made the second look new. Gemini 4 appeared nine times across
four issues.
"
These tests pin the three properties that make the rule workwithout over-deleting:

* an exact repeat (same headline or URL) is a repeat;
* the same thing reworded is also a repeat -- that is what the similarity check is for;
* a different event about the same model is NOT a repeat, or one busy day would erase itself.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.history import (
    NEAR_MATCH_RATIO,
    PublishedHistory,
    _fold,
    _is_near_match,
    fingerprint,
)
from aidaily.models import Event

NOW = datetime(2026, 10, 18, 4, 0, tzinfo=timezone.utc)


def event(title: str, *, url: str | None = None, event_id: str = "e1") -> Event:
    url = url or "https://example.com/" + event_id
    return Event(
        event_id=event_id,
        primary_item_id=event_id + "-i",
        title=title,
        member_item_ids=[event_id + "-i"],
        source_ids=["rss:a"],
        all_urls=[url],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def history_with(*entries: tuple[str, list[str]], path) -> PublishedHistory:
    """A history populated directly, so a test does not depend on the archive on disk."""
    lines = []
    for date, titles in entries:
        events = [
            {"id": "%s-%d" % (date, i), "title": t, "keys": sorted(fingerprint(event(t))), "fold": _fold(t)}
            for i, t in enumerate(titles)
        ]
        lines.append((date, events))
    path.write_text(
        "\n".join(
            '{"date": "%s", "events": %s}' % (date, __import__("json").dumps(events, ensure_ascii=False))
            for date, events in lines
        ),
        encoding="utf-8",
    )
    h = PublishedHistory(path, window_days=7)
    h.load()
    return h


def test_the_same_announcement_reworded_is_a_repeat(tmp_path) -> None:
    """The exact case that shipped twice: one word inserted."""
    h = history_with(
        ("2026-10-16", ["Gemini 4 Argon 向正价 Google AI Pro 用户开放"]),
        path=tmp_path / "h.jsonl",
    )
    repeat = h.find_repeat(
        event("Gemini 4 Argon 向 Google AI Pro 开放", event_id="probe"), today="2026-10-18", now=NOW
    )
    assert repeat is not None, "the reworded repeat was not recognised"
    # "reworded", not "designation": the wording was compared and matched, so the
    # evidence is proof rather than the bare "this model appeared before" signal.
    assert repeat.matched_on == "reworded"
    assert repeat.days_ago == 2


def test_a_different_event_about_one_model_is_not_a_repeat(tmp_path) -> None:
    """Three separate Gemini 4 stories on one day are legitimate; none may delete another."""
    h = history_with(
        ("2026-10-16", ["Gemini 4 Argon 机器人模型发布"]),
        path=tmp_path / "h.jsonl",
    )
    repeat = h.find_repeat(
        event("Gemini 4 Argon 在 ARC-AGI-3 获 97.5%", event_id="probe2"), today="2026-10-18", now=NOW
    )
    assert repeat is None, "a different story about the same model was called a repeat"


def test_todays_own_issue_is_not_cross_day_repetition(tmp_path) -> None:
    """A second trigger of the same day must not see itself as yesterday's news."""
    h = history_with(("2026-10-18", ["Gemini 4 Argon 向 Google AI Pro 开放"]), path=tmp_path / "h.jsonl")
    repeat = h.find_repeat(
        event("Gemini 4 Argon 向 Google AI Pro 开放", event_id="probe"), today="2026-10-18", now=NOW
    )
    assert repeat is None


def test_the_window_is_respected(tmp_path) -> None:
    """Outside the window a story is news again."""
    h = history_with(("2026-09-01", ["DeepSeek 发布 V4.1-Flash-1017"]), path=tmp_path / "h.jsonl")
    repeat = h.find_repeat(
        event("DeepSeek 发布 V4.1-Flash-1017", event_id="probe3"), today="2026-10-18", now=NOW
    )
    assert repeat is None, "a story older than the window was still treated as a repeat"


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("Gemini 4 Argon 向正价 Google AI Pro 用户开放", "Gemini 4 Argon 向 Google AI Pro 开放", True),
        ("DeepSeek 发布 V4.1-Flash-1017，性能更强", "DeepSeek 发布 V4.1-Flash-1017，输出更省 token", True),
        ("Gemini 4 Argon 机器人模型发布", "Gemini 4 Argon 在 ARC-AGI-3 获 97.5%", False),
        ("OpenAI 发布 GPT-6 Astra Pro", "DeepSeek 发布 V4.1-Flash", False),
    ],
)
def test_the_threshold_separates_reworded_repeats_from_new_stories(
    left: str, right: str, expected: bool
) -> None:
    """0.80 sits between the measured pairs with room on both sides.

    Measured ratios: 0.923, 0.807 (same event) against 0.545, 0.333 (different events).
    """
    assert _is_near_match(_fold(left), [_fold(right)]) is expected

def test_another_outlets_digest_is_recognised() -> None:
    """A feed entry that is itself a digest must not enter the issue.

    It restates events the digest already carries under their own headlines, so the reader sees
    one story twice no matter how the ranking behaves. Five such entries appeared across
    2026-10-14..18.
    """
    from aidaily.designation import is_roundup

    assert is_roundup("AI 早报：Gemini 4 Argon 全球开放，多家厂商发布新模型")
    assert is_roundup("AIHOT 日报 · 2026-10-15 — Gemini 4 Argon 向全球 Google AI Pro")
    assert is_roundup("2026-10-17 AI 日报 · 中国拟收紧大模型出口管制")


def test_a_real_story_is_not_mistaken_for_a_digest() -> None:
    """The words 日报/早报 must appear as the masthead, not anywhere in the sentence.

    A first version matched them as substrings and removed two genuine stories:
    "华尔街拟转让380亿美元AI数据中心债务" and "DeepSeek发布V4.1-Flash-1017并开放搜索接口".
    """
    from aidaily.designation import is_roundup

    assert not is_roundup("DeepSeek发布V4.1-Flash-1017并开放搜索接口")
    assert not is_roundup("Gemini 4 Argon 向 Google AI Pro 开放")
    assert not is_roundup("华尔街拟转让380亿美元AI数据中心债务，多州起诉OpenAI")

def test_a_query_string_that_carries_the_article_id_is_kept() -> None:
    """WeChat article identity lives in the query string, and stripping it collapsed the host.

    This shipped as a real failure: every `mp.weixin.qq.com/s?...` URL reduced to
    `mp.weixin.qq.com/s`, so an unrelated Meta story from 10-16 and the DeepSeek V4.1 launch
    from 10-17 shared a URL fingerprint. The launch was then dropped as a repeat -- the most
    important story of the day, deleted by its own deduplicator.
    """
    from aidaily.history import _canonical_url

    a = _canonical_url("https://mp.weixin.qq.com/s?__biz=MzA3&mid=265&idx=3&sn=d54")
    b = _canonical_url("https://mp.weixin.qq.com/s?__biz=MzI3&mid=2652&idx=1&sn=7da")
    assert a != b, "two WeChat articles collapsed to one identity"
    assert "mid=265" in a and "mid=2652" in b


def test_tracking_parameters_are_still_dropped() -> None:
    """The fix must not stop ordinary canonicalisation working."""
    from aidaily.history import _canonical_url

    assert _canonical_url("https://example.com/a?utm_source=x&utm_medium=y") == "example.com/a"
    assert _canonical_url("http://example.com/a/") == "example.com/a"


def test_a_release_and_an_earlier_promo_about_it_are_different_events(tmp_path) -> None:
    """The launch must survive even though a promotion mentioned the same model the day before.

    10-16 carried "DeepSeek V4.1 Flash 在 OpenCode 限时免费" and 10-17 carried the launch itself.
    They share a designation but are not the same story, and the launch is the one that matters.
    """
    h = history_with(
        ("2026-10-16", ["DeepSeek V4.1 Flash 在 OpenCode 限时免费"]),
        path=tmp_path / "h.jsonl",
    )
    repeat = h.find_repeat(
        event("DeepSeek 发布 V4.1-Flash-1017，性能更强", event_id="launch"),
        today="2026-10-17",
        now=NOW,
    )
    assert repeat is None, "the launch was treated as a repeat of a promotion"
