"""L3 event clustering and the window's junk filters.

The tests that matter most here are the negative ones: L3 must not merge things it
cannot justify, must never lose a URL, and must not manufacture corroboration out of two
feeds that carry the same content.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from _async import async_test
from aidaily.config import load_config
from aidaily.dedup import units_from_result
from aidaily.dedup import cluster as l2_cluster
from aidaily.l3 import build_events, coarse_clusters, extract_entities
from aidaily.select import select_window

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


def make_item(make_item, **kw):
    """Thin pass-through so the fixture signature stays obvious at call sites."""
    kw.setdefault("published_at", NOW)
    return make_item(**kw)


# =============================== entity extraction ===============================
def test_known_entities_are_recognised() -> None:
    got = extract_entities("OpenAI and Nvidia announce a datacenter partnership")
    assert "openai" in got and "nvidia" in got


def test_chinese_entities_are_recognised() -> None:
    got = extract_entities("智谱发布 GLM-Legal 法律模型")
    assert "智谱" in got


def test_common_capitalised_words_are_not_entities() -> None:
    got = extract_entities("How To Build The Best Thing")
    assert not ({"how", "the", "best", "thing"} & got)


def test_capitalised_names_survive() -> None:
    got = extract_entities("Anthropic shipped Claude and Meta shipped Llama")
    assert {"anthropic", "claude", "meta", "llama"} <= got


# =============================== coarse clustering ===============================
def test_items_sharing_two_entities_in_one_bucket_group(make_item) -> None:
    a = make_item(title="OpenAI ships GPT-6 model", url="https://a.example/1", item_id="i1")
    b = make_item(title="OpenAI GPT-6 benchmarks leak", url="https://b.example/2", item_id="i2")
    c = make_item(title="Something unrelated entirely", url="https://c.example/3", item_id="i3")

    groups = coarse_clusters([a, b, c])
    assert len(groups) == 1
    assert set(groups[0].item_ids) == {"i1", "i2"}


def test_items_in_different_time_buckets_do_not_group(make_item) -> None:
    a = make_item(title="OpenAI ships GPT-6 model", url="https://a.example/1", item_id="i1",
                  published_at=NOW)
    b = make_item(title="OpenAI GPT-6 benchmarks leak", url="https://b.example/2", item_id="i2",
                  published_at=NOW - timedelta(days=3))

    assert coarse_clusters([a, b], time_bucket_hours=6) == []


def test_singletons_are_not_proposed_for_judging(make_item) -> None:
    a = make_item(title="Only one story about OpenAI GPT", url="https://a.example/1", item_id="i1")
    assert coarse_clusters([a]) == []


# =============================== build_events ====================================
@async_test
async def test_events_preserve_every_url_and_source(make_item) -> None:
    """The whole point of an event is that it corroborates without discarding."""
    p = make_item(title="OpenAI ships GPT-6", url="https://openai.com/gpt6",
                  content="body", source_id="rss:openai", item_id="i1")
    q = make_item(title="OpenAI ships GPT-6", url="https://mirror.example/gpt6",
                  content="body", source_id="rss:mirror", item_id="i2")

    stage = l2_cluster([p, q])
    units = units_from_result(stage, [p, q])
    events, _ = await build_events(units, router=None)

    assert len(events) == 1
    event = events[0]
    assert set(event.all_urls) == {"https://openai.com/gpt6", "https://mirror.example/gpt6"}
    assert set(event.source_ids) == {"rss:openai", "rss:mirror"}
    assert event.independent_source_count == 2
    assert event.evidence_level == "multi_source"


@async_test
async def test_feeds_sharing_a_dedup_group_are_one_source(make_item) -> None:
    """Regression: HN Algolia and hnrss carry the same stories.

    Counting them as two sources labelled a single-source story as
    "multi-source cross-verified" -- manufactured corroboration.
    """
    p = make_item(title="A story", url="https://story.example/x", content="b",
                  source_id="api:hn-algolia-com-search", item_id="i1")
    q = make_item(title="A story", url="https://story.example/x", content="b",
                  source_id="rss:hnrss-org-frontpage", item_id="i2")

    stage = l2_cluster([p, q])
    units = units_from_result(stage, [p, q])
    groups = {"api:hn-algolia-com-search": "hackernews", "rss:hnrss-org-frontpage": "hackernews"}
    events, _ = await build_events(units, router=None, source_groups=groups)

    event = events[0]
    assert len(event.source_ids) == 2, "both source ids are still recorded"
    assert event.independent_source_count == 1
    assert event.evidence_level == "single_source", "same content twice is not corroboration"


@async_test
async def test_no_router_merges_only_what_is_unambiguous(make_item) -> None:
    """Policy change, and the reasoning matters.

    This test used to assert that **nothing** merged without the judge -- "degrade to
    singletons rather than guess". The intent was sound but the consequence was not: on a
    real day that left thirteen separate reports of the Gemini 4 Argon launch, and the
    diversity pass then penalised every one of them for repeating a topic, so the day's
    biggest story scattered across positions 1, 41, 55, 56, 57, 59 and 60 of 60.

    The conservative choice is not "merge nothing", it is "merge what is unambiguous". Here
    that means two headlines both dominated by the same subject, with similar wording.

    What has NOT changed is the refusal to guess at genuinely different stories -- asserted
    below, because a policy that merges everything is as wrong as one that merges nothing.
    """
    a = make_item(title="OpenAI ships GPT-6 model", url="https://a.example/1", item_id="i1")
    b = make_item(title="OpenAI GPT-6 benchmarks leak", url="https://b.example/2", item_id="i2")

    stage = l2_cluster([a, b])
    units = units_from_result(stage, [a, b])
    events, result = await build_events(units, router=None)

    assert len(events) == 1, "two reports of one GPT-6 story are one event"
    assert result.judged == 0, "no judge ran, and the result must not claim one did"
    assert result.accepted_without_judge == 1, "the merge is attributed to the fallback"


@async_test
async def test_no_router_keeps_unrelated_stories_apart(make_item) -> None:
    """The other half of the policy: a fallback that merges everything is not a fallback.

    These two share no entity, so no amount of overlap passes the threshold -- which is the
    property that stops the fallback from becoming "assume it is all one story".
    """
    a = make_item(title="Anthropic publishes a safety report", url="https://a.example/1", item_id="i1")
    b = make_item(title="Nvidia announces quarterly earnings", url="https://b.example/2", item_id="i2")

    stage = l2_cluster([a, b])
    units = units_from_result(stage, [a, b])
    events, result = await build_events(units, router=None)

    assert len(events) == 2
    assert result.accepted_without_judge == 0


@async_test
async def test_l3_operates_on_units_not_raw_items(make_item) -> None:
    """Regression: passing raw items to L3 undid L2.

    A story carried by three feeds became three separate "events" because L3 was given
    the raw item list instead of the L2 groups.
    """
    items = [
        make_item(title="Same story", url=f"https://m{i}.example/s", content="identical body",
                  source_id=f"rss:s{i}", item_id=f"i{i}")
        for i in range(3)
    ]
    stage = l2_cluster(items)
    assert len(stage.groups) == 1, "L2 should merge all three"

    units = units_from_result(stage, items)
    events, _ = await build_events(units, router=None)

    assert len(events) == 1, "one L2 group must yield one event, not three"
    assert len(events[0].member_item_ids) == 3


# =============================== window junk filters =============================
def _cfg():
    return load_config(env={})


def test_future_dated_items_are_excluded_and_sampled(make_item) -> None:
    """Ai2's feed dates every entry 17 days ahead; that cannot be today's news."""
    bad = make_item(title="Ai2 future item", url="https://ai2.example/x", item_id="i1",
                    published_at=NOW + timedelta(days=17))
    good = make_item(title="A normal item", url="https://ok.example/y", item_id="i2",
                     published_at=NOW - timedelta(hours=1))

    result = select_window([bad, good], _cfg(), NOW)

    assert [i.item_id for i in result.kept] == ["i2"]
    assert result.dropped_by_bucket["future_dated"] == 1
    assert result.future_dated_samples and "ai2" in result.future_dated_samples[0].lower()


def test_small_timezone_skew_is_tolerated(make_item) -> None:
    """A feed an hour ahead is normal; only a real gap is a defect."""
    slightly_ahead = make_item(title="Ahead by an hour", url="https://ok.example/z", item_id="i1",
                               published_at=NOW + timedelta(hours=1))
    assert len(select_window([slightly_ahead], _cfg(), NOW).kept) == 1


def test_items_without_a_url_are_excluded(make_item) -> None:
    """The digest promises every item links to its source."""
    no_url = make_item(title="Changelog entry", url="", item_id="i1")
    good = make_item(title="A normal item", url="https://ok.example/y", item_id="i2",
                     published_at=NOW - timedelta(hours=1))

    result = select_window([no_url, good], _cfg(), NOW)

    assert [i.item_id for i in result.kept] == ["i2"]
    assert result.dropped_by_bucket["no_url"] == 1
    assert result.no_url_samples


# =============================== critical-source wait gate =======================
def test_wait_window_covers_the_scheduled_triggers() -> None:
    """09:53 / 10:07 / 10:23 / 10:41 Beijing must all arm the freshness gate."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from aidaily.collect import wait_window

    cfg = _cfg()
    tz = ZoneInfo("Asia/Shanghai")
    for hhmm in ("09:53", "10:00", "10:07", "10:23", "10:41", "11:30", "12:59"):
        h, m = (int(x) for x in hhmm.split(":"))
        when = datetime(2026, 10, 14, h, m, tzinfo=tz)
        armed, why = wait_window(cfg, when)
        assert armed, f"{hhmm} should arm the gate ({why})"


def test_wait_window_is_disarmed_outside_the_schedule() -> None:
    """Regression from the first real GitHub run.

    A manual trigger at 02:00 Beijing waited the full 20-minute timeout for juya's
    edition -- which does not exist until 09:48. The gate has to know when a late source
    is even plausible, otherwise it just burns the job's time budget.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from aidaily.collect import wait_window

    cfg = _cfg()
    tz = ZoneInfo("Asia/Shanghai")
    for hhmm in ("02:00", "07:00", "09:00", "14:00", "23:30"):
        h, m = (int(x) for x in hhmm.split(":"))
        when = datetime(2026, 10, 14, h, m, tzinfo=tz)
        armed, why = wait_window(cfg, when)
        assert not armed, f"{hhmm} should not wait"
        assert "调度窗口" in why
