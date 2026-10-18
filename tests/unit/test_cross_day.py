"""One message is one message, however it is worded.

The rule the user stated: "无论他语言怎么表达，它是一条消息，就是一条消息，重复的就是重复的".

The mechanism that shipped did not enforce it, and the archive shows both failures:

   10-17  deepseek-v4.1-flash-1017 发布了
   10-18  DeepSeek发布V4.1-Flash-1017并开放搜索接口

   10-17  WorkBuddy Intl 更新支持 DeepSeek-V4.1-Flash-1017，10 月 31 日前免费
   10-18  WorkBuddy国际版限免DeepSeek模型

Both were reported twice. The first pair failed because the identity was the *model designation*
and the second headline parsed as "flash" (the verb sat flush against the vendor). The second
pair failed because a promotion word excluded both headlines from the model rule entirely, so
they never took part in deduplication.

These tests pin the replacement: identity is **who did what**, compared across languages, word
orders and version strings.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.history import PublishedHistory, _canonical_url, _fold, fingerprint
from aidaily.models import Event
from aidaily.samestory import actors, event_types, same_message, subjects

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


def history_with(*entries, path) -> PublishedHistory:
    """A history populated directly, so a test does not depend on the archive on disk."""
    import json

    lines = []
    for date, titles in entries:
        rows = []
        for i, title in enumerate(titles):
            eid = "%s-%d" % (date, i)
            rows.append({
                "id": eid,
                "title": title,
                "keys": sorted(fingerprint(event(title, event_id=eid))),
                "fold": _fold(title),
            })
        lines.append(json.dumps({"date": date, "events": rows}, ensure_ascii=False))
    path.write_text("\n".join(lines), encoding="utf-8")
    h = PublishedHistory(path, window_days=7)
    h.load()
    return h


# --- the two pairs that shipped twice -------------------------------------------


@pytest.mark.parametrize(
    "earlier,later",
    [
        (
            "deepseek-v4.1-flash-1017 发布了",
            "DeepSeek发布V4.1-Flash-1017并开放搜索接口",
        ),
        (
            "WorkBuddy Intl 更新支持 DeepSeek-V4.1-Flash-1017，10 月 31 日前免费",
            "WorkBuddy国际版限免DeepSeek模型",
        ),
    ],
)
def test_the_two_pairs_the_reader_reported_are_one_message(earlier: str, later: str) -> None:
    """Reported from the live site on 2026-10-18: both ran on 17 and again on 18."""
    assert same_message(earlier, later), f"not matched:\n  {earlier}\n  {later}"


@pytest.mark.parametrize(
    "left,right",
    [
        ("Anthropic 员工对人工智能能力的预期更高", "Anthropic 递交 AI 安全法案草案"),
        ("Anthropic 将支付 10% 高息 AI 债券", "Anthropic 初级技术员工占比降至 14%"),
        ("DeepSeek 近五小时停服", "DeepSeek 发布 V4.1-Flash-1017"),
        ("OpenAI 发布 GPT-6 Astra Pro", "Anthropic 发布 Claude Opus 5.5"),
        ("DeepSeek 发布 V4.1-Flash-1017", "WorkBuddy国际版限免DeepSeek模型"),
        # A commentary piece that mentions a vendor is not that vendor's next launch.
        ("Meta 开源权重模型竞争力展望", "Meta发布Muse Spark Open：816B开源模型，1M上下文"),
    ],
)
def test_different_news_is_not_collapsed(left: str, right: str) -> None:
    """Over-merging is the opposite failure, and an earlier rule hit it: thirteen unrelated
    Anthropic stories were deleted as duplicates of each other."""
    assert not same_message(left, right), f"wrongly matched:\n  {left}\n  {right}"


def test_a_vendor_alias_is_not_a_subject() -> None:
    """`claude` names a vendor, not a story.

    Including bare aliases as subjects made four unrelated Claude items on 2026-10-17 look like
    one message. Only a product *with a version* is specific enough.
    """
    assert not subjects("Claude Code 团队发文披露内部代码审查流程")
    assert not subjects("Anthropic 如何在 Claude 写下 90% 代码后重新设计评审")
    assert subjects("Claude Opus 5.5 发布")
    assert subjects("DeepSeek 发布 V4.1-Flash-1017")


def test_identity_ignores_language_and_separators() -> None:
    """The same release written four ways produces one actor set and one subject set."""
    variants = [
        "DeepSeek 发布 V4.1-Flash-1017",
        "deepseek-v4.1-flash-1017 发布了",
        "DeepSeek: DeepSeek v4.1 Flash 1017",
        "DeepSeek发布V4.1-Flash-1017并开放搜索接口",
    ]
    for a in variants:
        for b in variants:
            assert same_message(a, b), f"{a!r} vs {b!r}"


# --- history integration --------------------------------------------------------


def test_a_reworded_repeat_is_dropped(tmp_path) -> None:
    h = history_with(
        ("2026-10-17", ["deepseek-v4.1-flash-1017 发布了"]),
        path=tmp_path / "h.jsonl",
    )
    repeat = h.find_repeat(
        event("DeepSeek发布V4.1-Flash-1017并开放搜索接口", event_id="probe"),
        today="2026-10-18",
        now=NOW,
    )
    assert repeat is not None, "the reworded repeat was not recognised"
    assert repeat.matched_on == "message"
    assert repeat.days_ago == 1


def test_a_different_story_about_one_vendor_is_kept(tmp_path) -> None:
    h = history_with(
        ("2026-10-16", ["Anthropic 员工对人工智能能力的预期更高"]),
        path=tmp_path / "h.jsonl",
    )
    repeat = h.find_repeat(
        event("Anthropic 递交 AI 安全法案草案", event_id="probe2"),
        today="2026-10-18",
        now=NOW,
    )
    assert repeat is None, "two different Anthropic stories were treated as one"


def test_todays_own_issue_is_not_cross_day_repetition(tmp_path) -> None:
    h = history_with(("2026-10-18", ["DeepSeek 发布 V4.1-Flash-1017"]), path=tmp_path / "h.jsonl")
    repeat = h.find_repeat(
        event("DeepSeek 发布 V4.1-Flash-1017", event_id="probe3"), today="2026-10-18", now=NOW
    )
    assert repeat is None


def test_the_window_is_respected(tmp_path) -> None:
    """Outside the window a story is news again."""
    h = history_with(("2026-09-01", ["DeepSeek 发布 V4.1-Flash-1017"]), path=tmp_path / "h.jsonl")
    repeat = h.find_repeat(
        event("DeepSeek 发布 V4.1-Flash-1017", event_id="probe4"), today="2026-10-18", now=NOW
    )
    assert repeat is None, "a story older than the window was still treated as a repeat"


# --- URL identity ----------------------------------------------------------------


def test_a_query_string_that_carries_the_article_id_is_kept() -> None:
    """Every WeChat URL used to collapse to `mp.weixin.qq.com/s`, so unrelated articles shared a
    fingerprint and the day's biggest story was deleted as a repeat of another."""
    a = _canonical_url("https://mp.weixin.qq.com/s?__biz=MzA3&mid=265&idx=3&sn=d54")
    b = _canonical_url("https://mp.weixin.qq.com/s?__biz=MzI3&mid=2652&idx=1&sn=7da")
    assert a != b
    assert "mid=265" in a and "mid=2652" in b


def test_tracking_parameters_are_still_dropped() -> None:
    assert _canonical_url("https://example.com/a?utm_source=x&utm_medium=y") == "example.com/a"
    assert _canonical_url("http://example.com/a/") == "example.com/a"


# --- actor and event extraction --------------------------------------------------


def test_actors_are_found_across_languages() -> None:
    assert actors("DeepSeek 发布新模型") == actors("深度求索 ships a new model")
    assert "alibaba" in actors("阿里 Qwen 开源新基准")
    assert "google" in actors("Google DeepMind announces Gemini 4")


def test_event_types_separate_a_release_from_an_outage() -> None:
    assert "release" in event_types("DeepSeek 发布 V4.1-Flash-1017")
    assert "outage" in event_types("DeepSeek 近五小时停服")
    assert "pricing" in event_types("WorkBuddy 国际版限免 DeepSeek 模型")
