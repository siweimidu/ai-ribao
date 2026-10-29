"""Two lists, because the two instructions differ.

「以后都记清楚了抓取这些的当日源不用筛选，直接打分排序」  -- hex2077, daily-juya,
ainewslog, aibase.

「aihot.news的信息仍然要筛选一遍，只是来自aihot.news的信息天然要高些」  -- aihot is an
aggregator, filtered but boosted.

## Why they must not share one list

Measured 2026-10-27, with every aihot feed on the exemption list:

    #59  MIT 在 2026 纽约气候周对接全球气候网络     focus 0.50
    #61  Thariq 将在 AIE Code 分享 WoW 萨满配装     focus 0.33

`is_passthrough` short-circuits the relevance gate, so a 0.33 World-of-Warcraft talk published
as AI news. The exemption was written for editorial sources whose judgement is trusted; an
aggregator carries whatever its contributors submitted.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.pipeline import has_aihot_source, is_passthrough
from aidaily.unfiltered import (
    AIHOT_BOOST,
    AIHOT_SOURCES,
    UNFILTERED_SOURCES,
    is_aihot,
    is_unfiltered,
)

NOW = datetime.now(timezone.utc)


def _event(*sids: str) -> Event:
    return Event(
        event_id="e",
        title="t",
        member_item_ids=["m"],
        primary_item_id="m",
        source_ids=list(sids),
        all_urls=["https://example.com/x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_the_named_sources_stay_exempt() -> None:
    """「其他的那几个不要筛选的源保持不变」."""
    for sid in (
        "rss:hex2077",
        "rss:hex2077-dev-rss-zh-cn",
        "rss:daily-juya-uk",
        "rss:ainewslog-com",
        "api:aibase-ai-news",
        "api:aibase-daily-news",
    ):
        assert is_unfiltered(sid), sid
        assert is_passthrough(_event(sid)), sid


#: The three aihot feeds the user named by URL on 2026-10-29.
#:
#: 「这三个RSS算作一个，也加入不用筛选，直接打分的当日信息里面，这些消息只能去重并标注多源
#:   验证，不能删除，不能删除任何一条，这条要写死」
NAMED_AIHOT = frozenset({
    "rss:aihot-news-picks",   # https://aihot.news/feed.xml
    "rss:aihot-news-full",    # https://aihot.news/feed/full.xml
    "rss:aihot-news-daily",   # https://aihot.news/feed/daily.xml
})


def test_the_three_named_aihot_feeds_are_unfiltered() -> None:
    for sid in NAMED_AIHOT:
        assert is_unfiltered(sid), sid
        assert is_passthrough(_event(sid)), sid


def test_the_other_aihot_feeds_are_still_filtered() -> None:
    """Only the three named feeds were exempted; the rest still pass the gate."""
    for sid in AIHOT_SOURCES - NAMED_AIHOT:
        assert not is_unfiltered(sid), sid
        assert not is_passthrough(_event(sid)), sid


def test_aihot_feeds_are_recognised_for_the_boost() -> None:
    for sid in AIHOT_SOURCES:
        assert is_aihot(sid), sid
        assert has_aihot_source(_event(sid)), sid


def test_a_plain_source_gets_neither() -> None:
    for sid in ("rss:axios", "rss:engadget", "rss:semafor"):
        assert not is_unfiltered(sid)
        assert not is_aihot(sid)
        assert not is_passthrough(_event(sid))
        assert not has_aihot_source(_event(sid))


def test_the_boost_cannot_lift_a_story_past_the_gate() -> None:
    """The gate runs before ranking, so a multiplier cannot admit anything."""
    assert 0.33 * AIHOT_BOOST < 0.50


def test_the_boost_is_modest() -> None:
    """Large enough to reorder, small enough not to dominate."""
    assert 1.0 < AIHOT_BOOST <= 1.5


def test_the_only_overlap_is_the_three_named_feeds() -> None:
    """They are unfiltered *and* AI-native, so they take the bonus and the protection.

    An earlier version of this test asserted no overlap at all. The user then named these
    three feeds explicitly, which makes both properties a requirement rather than a
    contradiction -- so the invariant is now "the overlap is exactly the named three".
    """
    assert UNFILTERED_SOURCES & AIHOT_SOURCES == NAMED_AIHOT

def test_the_three_named_feeds_count_as_one_source() -> None:
    """銆岃繖涓変釜RSS绠椾綔涓€涓€?-- they publish the same items to three URLs."""
    from aidaily.unfiltered import distinct_source_groups

    assert distinct_source_groups(sorted(NAMED_AIHOT)) == 1


def test_a_real_second_outlet_still_counts() -> None:
    from aidaily.unfiltered import distinct_source_groups

    assert distinct_source_groups(sorted(NAMED_AIHOT) + ["rss:axios"]) == 2


def test_independence_is_not_inflated_by_the_trio() -> None:
    """Without the collapse, one story on three aihot URLs reads as 3 outlets."""
    from aidaily.unfiltered import distinct_source_groups

    three = sorted(NAMED_AIHOT)
    assert len(set(three)) == 3
    assert distinct_source_groups(three) == 1

