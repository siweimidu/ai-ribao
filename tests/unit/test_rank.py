"""Ranking and diversity.

The behaviour these tests protect is the one that shipped broken: the digest head was
seven angles on one topic from one source, because the score had no notion of source
quality, no floor under recency decay, and the diversity caps were undone by a backfill
step that ignored them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aidaily.entities import extract_entities, topic_overlap
from aidaily.models import Event, NormalizedItem, SourceSpec
from aidaily.rank import (
    RankWeights,
    _recency,
    diversity_report,
    rank_events,
    score_event,
    select_diverse,
)

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)


def spec(source_id: str, category: str = "media", group: str | None = None) -> SourceSpec:
    return SourceSpec(
        source_id=source_id, name=source_id, url=f"https://{source_id}.example/feed",
        normalized_url=f"https://{source_id}.example/feed", domain=f"{source_id}.example",
        category=category, source_type="rss", adapter="RssFetcher",
        dedup_group=group, found_in=["r:f#k"], repositories=["r"],
    )


def item(
    item_id: str, source_id: str, *, body: str = "", title: str = "T",
    published: datetime | None = NOW, metrics: dict | None = None,
) -> NormalizedItem:
    return NormalizedItem(
        item_id=item_id, source_id=source_id, title=title, title_norm=title.lower(),
        url=f"https://{source_id}.example/{item_id}", published_at=published,
        fetched_at=NOW, first_seen_at=NOW, updated_at=NOW,
        summary=body[:400], content_text=body or None, content_sha256="h", simhash=1,
        metrics=metrics or {},
    )


def event(
    event_id: str,
    item_ids: list[str],
    title: str,
    *,
    independent: int = 1,
    published: datetime | None = NOW,
    source_ids: list[str] | None = None,
    urls: list[str] | None = None,
) -> Event:
    """Build an event whose source ids match the `sources` mapping under test.

    Passing the ids explicitly matters: deriving them from item ids produced
    `rss:i1`, which silently missed the `sources` dict and made every source weigh 1.0.
    """
    ids = source_ids or [f"rss:{i}" for i in item_ids]
    return Event(
        event_id=event_id, title=title, member_item_ids=item_ids, primary_item_id=item_ids[0],
        source_ids=sorted(set(ids)),
        all_urls=urls or [f"https://x.example/{item_ids[0]}"],
        independent_source_count=independent, first_seen_at=NOW, last_updated_at=NOW,
        published_range=(published, published) if published else None,
        evidence_level="multi_source" if independent > 1 else "single_source",
    )


WEIGHTS = {"lab-official": 1.5, "zh-media": 1.2, "media": 1.1, "community": 0.9}


# =============================== scoring =========================================
def test_official_source_outranks_a_link_aggregator() -> None:
    """`quality.source_weights` existed in the config for months and was wired to nothing."""
    items = [item("i1", "rss:lab", body="x" * 500), item("i2", "rss:comm", body="x" * 500)]
    sources = {"rss:lab": spec("rss:lab", "lab-official"), "rss:comm": spec("rss:comm", "community")}
    by_id = {i.item_id: i for i in items}
    rank = RankWeights()

    lab = score_event(event("e1", ["i1"], "Lab", source_ids=["rss:lab"]),
                      by_id, sources, WEIGHTS, rank, NOW)
    comm = score_event(event("e2", ["i2"], "Comm", source_ids=["rss:comm"]),
                       by_id, sources, WEIGHTS, rank, NOW)

    assert lab.components["source_weight"] == 1.5
    assert comm.components["source_weight"] == 0.9
    assert lab.score > comm.score


def test_substantive_body_outranks_a_bare_headline() -> None:
    """The 'Title: New Apple TV 4K / Points: 153' problem: no body, no facts."""
    items = [item("i1", "rss:a", body="A real article body. " * 40),
             item("i2", "rss:a", body="")]
    by_id = {i.item_id: i for i in items}
    sources = {"rss:a": spec("rss:a")}

    rich = score_event(event("e1", ["i1"], "Rich"), by_id, sources, WEIGHTS, RankWeights(), NOW)
    bare = score_event(event("e2", ["i2"], "Bare"), by_id, sources, WEIGHTS, RankWeights(), NOW)

    assert rich.components["substance"] > bare.components["substance"]
    assert rich.score > bare.score


def test_stars_today_is_not_engagement() -> None:
    """A repo gaining 1000 stars is not 1000 points of news importance.

    Including it saturated the log-scale signal at 1.0 for every trending repository,
    which is how nine of them reached the top nine slots.
    """
    items = [item("i1", "rss:a", body="x" * 300, metrics={"stars_today": 1500})]
    by_id = {"i1": items[0]}
    scored = score_event(event("e1", ["i1"], "Repo"), by_id, {"rss:a": spec("rss:a")},
                         WEIGHTS, RankWeights(), NOW)
    assert scored.components["h_engagement"] == 0.0


def test_points_do_count_as_engagement() -> None:
    items = [item("i1", "rss:a", body="x" * 300, metrics={"points": 900})]
    scored = score_event(event("e1", ["i1"], "Post"), {"i1": items[0]},
                         {"rss:a": spec("rss:a")}, WEIGHTS, RankWeights(), NOW)
    assert scored.components["h_engagement"] > 0.9


def test_recency_decays_but_never_to_zero() -> None:
    """Without a floor, decay alone re-creates the pure-recency ranking."""
    fresh = event("e1", ["i1"], "Fresh", published=NOW)
    old = event("e2", ["i1"], "Old", published=NOW - timedelta(days=5))
    rank = RankWeights(recency_half_life_hours=12, recency_floor=0.25)

    assert _recency(fresh, NOW, 12, 0.25) == pytest.approx(1.0)
    assert _recency(old, NOW, 12, 0.25) == pytest.approx(0.25, abs=0.01)


def test_undated_entries_get_neutral_recency_not_maximum() -> None:
    """Regression: GitHub Trending has no dates, and recency 1.0 let a repo with a
    40-character description outrank a lab announcement published six hours earlier."""
    undated = event("e1", ["i1"], "Repo", published=None)
    rank = RankWeights(recency_half_life_hours=12, recency_floor=0.25)

    value = _recency(undated, NOW, 12, 0.25)
    assert value == pytest.approx(0.625)
    assert value < 1.0, "unknown freshness is not brand new"


def test_corroboration_raises_the_score() -> None:
    items = [item("i1", "rss:a", body="x" * 300), item("i2", "rss:b", body="x" * 300)]
    by_id = {i.item_id: i for i in items}
    sources = {"rss:a": spec("rss:a"), "rss:b": spec("rss:b")}
    rank = RankWeights()

    single = score_event(event("e1", ["i1"], "T", source_ids=["rss:a"]),
                         by_id, sources, WEIGHTS, rank, NOW)
    multi = score_event(event("e2", ["i1", "i2"], "T", independent=2, source_ids=["rss:a", "rss:b"]),
                        by_id, sources, WEIGHTS, rank, NOW)

    assert multi.score > single.score


# =============================== diversity =======================================
def _many_events() -> tuple[list[Event], list[NormalizedItem], list[SourceSpec]]:
    events, items, sources = [], [], []
    for source_idx, category in ((0, "community"), (1, "lab-official"), (2, "zh-media")):
        sid = f"rss:s{source_idx}"
        sources.append(spec(sid, category))
        for n in range(8):
            iid = f"i{source_idx}_{n}"
            items.append(item(iid, sid, body="x" * 300, title=f"Story {source_idx}-{n}",
                              published=NOW - timedelta(minutes=10 * n)))
            events.append(event(f"e{source_idx}_{n}", [iid], f"Story {source_idx}-{n}",
                                source_ids=[sid]))
    return events, items, sources


def test_one_source_cannot_take_the_whole_digest() -> None:
    """With 8 sources and a 20-slot digest, no single source may dominate.

    The caps have to be satisfiable as well as binding: `max_per_group` also counts here
    because each of these sources is its own group, so the arithmetic is
    `sources * max_per_group` >= limit or the digest cannot be filled at all.
    """
    events, items, sources = [], [], []
    for s in range(8):
        sid = f"rss:s{s}"
        sources.append(spec(sid, "media"))
        for n in range(5):
            iid = f"i{s}_{n}"
            items.append(item(iid, sid, body="x" * 300, title=f"Story {s}-{n}",
                              published=NOW - timedelta(minutes=10 * n)))
            events.append(event(f"e{s}_{n}", [iid], f"Story {s}-{n}", source_ids=[sid]))

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 20, sources, rank=RankWeights(max_per_source=2, max_per_group=3))

    assert len(chosen) == 20, "the digest must still be fillable"
    per_source: dict[str, int] = {}
    for row in chosen:
        for sid in row.event.source_ids:
            per_source[sid] = per_source.get(sid, 0) + 1
    assert max(per_source.values()) <= 5, per_source  # ceil(20 * 20%) = 4, plus max_per_source
    assert len(per_source) >= 5, f"too few sources represented: {per_source}"


def test_backfill_still_respects_a_hard_ceiling() -> None:
    """Regression: the backfill ignored caps entirely, so the 26 slots the strict pass
    could not fill went to whichever feed was most prolific."""
    events, items, sources = [], [], []
    for s in range(6):
        sid = f"rss:s{s}"
        sources.append(spec(sid, "media"))
        for n in range(8):
            iid = f"i{s}_{n}"
            items.append(item(iid, sid, body="x" * 300, title=f"Story {s}-{n}",
                              published=NOW - timedelta(minutes=10 * n)))
            events.append(event(f"e{s}_{n}", [iid], f"Story {s}-{n}", source_ids=[sid]))

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 30, sources, rank=RankWeights(max_per_source=2, max_per_group=5))

    per_source: dict[str, int] = {}
    for row in chosen:
        for sid in row.event.source_ids:
            per_source[sid] = per_source.get(sid, 0) + 1
    # pass 3 removes the per-source ceiling only to fill the digest; the group cap and
    # the 20% share still bound it in practice.
    ceiling = max(2, -(-30 * 40 // 100))
    assert max(per_source.values()) <= ceiling, per_source


def test_feeds_sharing_a_dedup_group_count_as_one_source() -> None:
    """Otherwise the cap is bypassed by a source that merely appears twice."""
    sources = [spec("rss:hn1", group="hackernews"), spec("rss:hn2", group="hackernews"),
               spec("rss:other", "lab-official")]
    items, events = [], []
    for n in range(6):
        iid, sid = f"a{n}", ("rss:hn1" if n % 2 else "rss:hn2")
        items.append(item(iid, sid, body="x" * 300, title=f"HN {n}"))
        events.append(event(f"e{n}", [iid], f"HN {n}", source_ids=[sid]))
    for n in range(3):
        iid = f"o{n}"
        items.append(item(iid, "rss:other", body="x" * 300, title=f"Lab {n}"))
        events.append(event(f"eo{n}", [iid], f"Lab {n}", source_ids=["rss:other"]))

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 9, sources, rank=RankWeights(max_per_source=3, max_per_group=2))

    hn = sum(1 for row in chosen if any(s.startswith("rss:hn") for s in row.event.source_ids))
    assert hn <= 2, f"the group cap should apply across both HN feeds, got {hn}"


# =============================== topic homogeneity ===============================
def test_same_topic_from_different_sources_sinks_below_other_news() -> None:
    """The bug that shipped: nine of the top fourteen were 'Gemini 4 Argon'.

    The penalty *reorders*, it does not remove: a 60-slot digest drawn from 206
    candidates can legitimately contain several entries on one topic. What must not
    happen is that they occupy the head.
    """
    titles = [
        "Gemini 4 Argon: Built to solve your hardest problems",
        "Gemini 4 Argon for Robotics",
        "Google finally releases Gemini 4 Argon",
        "Google 发布 Gemini 4 Argon,面向订阅用户和开发者开放",
        "Gemini 4 Argon 上线 Devin",
    ]
    sources = [spec(f"rss:s{n}", "media") for n in range(len(titles))]
    items, events = [], []
    for n, title in enumerate(titles):
        iid, sid = f"i{n}", f"rss:s{n}"
        items.append(item(iid, sid, body="x" * 300, title=title))
        events.append(event(f"e{n}", [iid], title, source_ids=[sid]))
    items.append(item("ix", "rss:other", body="y" * 120, title="Character.AI files for bankruptcy"))
    sources.append(spec("rss:other", "media"))
    events.append(event("ex", ["ix"], "Character.AI files for bankruptcy", source_ids=["rss:other"]))

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 6, sources, rank=RankWeights(max_per_source=2, max_per_group=3))

    argon_positions = [i for i, row in enumerate(chosen) if "argon" in row.event.title.lower()]
    assert argon_positions, "the topic is still in the digest, just not at the top"
    # The first same-topic entry is unpenalised and keeps its place; every repeat is
    # discounted, so the lower-scoring unrelated story overtakes them.
    assert argon_positions[0] == 0
    assert chosen[1].event.title == "Character.AI files for bankruptcy"
    assert len(argon_positions) == 1 or argon_positions[1] > 1, (
        f"repeats must not follow the leader: {argon_positions}"
    )


def test_a_second_source_on_one_subject_is_not_buried() -> None:
    """Regression from the real digest: a genuine second report was pushed to slot 50.

    "The Verge reports Apple's HomeView launch" and "Apple's own HomeView page" are two
    different articles. Damping them like duplicates is wrong -- the digest is supposed to
    prefer corroboration. Only a shared URL marks the same article, and that is L2's job
    to have merged already.
    """
    sources = [spec("rss:verge", "media"), spec("rss:hn", "community")]
    items = [
        item("i1", "rss:verge", body="z" * 800,
             title="Apple launches HomeView, its first smart display for the home"),
        item("i2", "rss:hn", body="z" * 400, title="Apple HomeView"),
    ]
    events = [
        event("e1", ["i1"], items[0].title, source_ids=["rss:verge"],
              urls=["https://www.theverge.com/tech/1009704/apple-homeview-first-look"]),
        event("e2", ["i2"], items[1].title, source_ids=["rss:hn"],
              urls=["https://www.apple.com/apple-homeview/"]),
    ]

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 2, sources, rank=RankWeights(max_per_source=2, max_per_group=3))

    homeview = [i for i, row in enumerate(chosen) if "homeview" in row.event.title.lower()]
    assert len(homeview) == 2, "both sources belong in the digest"
    # The lighter same-topic penalty should leave the second one near the top, not at the
    # bottom of a 60-slot digest.
    for row in chosen:
        if "homeview" in row.event.title.lower():
            assert row.components["topic_penalty"] >= 0.4, row.components


def test_a_shared_url_is_treated_as_a_duplicate_not_a_second_source() -> None:
    """A URL in both events means L2 let the same article through twice."""
    shared = "https://example.com/story"
    sources = [spec("rss:a", "media"), spec("rss:b", "media")]
    items = [item("i1", "rss:a", body="z" * 300, title="OpenAI ships GPT-6 to all users"),
             item("i2", "rss:b", body="z" * 300, title="GPT-6 rollout reaches every account")]
    events = [
        event("e1", ["i1"], items[0].title, source_ids=["rss:a"], urls=[shared]),
        event("e2", ["i2"], items[1].title, source_ids=["rss:b"], urls=[shared]),
    ]

    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)

    # Two events sharing one URL and one model designation are the same article seen twice.
    # The ranker now collapses them before diversity selection, which is a stronger answer than
    # the original assertion: the duplicate cannot reach the digest at all, so the reader never
    # sees one story counted as two independent sources.
    assert len(ranked) == 1, [r.event.title for r in ranked]
    only = ranked[0]
    assert len(only.event.source_ids) == 2, only.event.source_ids
    assert len(only.event.all_urls) == 1, only.event.all_urls


def test_entity_overlap_is_the_decisive_signal_not_string_similarity() -> None:
    """Why entity overlap was added on top of a string threshold.

    For the Latin pair the string score lands *right at* the 0.55 threshold -- a slightly
    different threshold and it stops firing. For the Chinese headline against a Latin one
    the string score collapses entirely while the shared subject is unmistakable. Entity
    overlap is decisive in both cases.
    """
    from aidaily.normalize import title_similarity

    a = "Gemini 4 Argon: Built to solve your hardest problems"
    b = "Gemini 4 Argon for Robotics"
    c = "Google 发布 Gemini 4 Argon,面向订阅用户和开发者开放"

    assert 0.5 < title_similarity(a.lower(), b.lower()) < 0.6, "marginal, threshold-dependent"
    # Cross-script: the string rule goes quiet (below the configured 0.55) while the
    # shared subject is unmistakable. This is the case that filled the real digest.
    assert title_similarity(a.lower(), c.lower()) < 0.55, "the string rule would not fire"
    assert topic_overlap(a, b) >= 2
    assert topic_overlap(a, c) >= 2, "but the subject is the same"


def test_topic_overlap_ignores_cjk_bigrams() -> None:
    """Two Chinese headlines share plenty of bigrams by accident."""
    assert topic_overlap("量子位报道英伟达新芯片", "机器之心分析苹果新产品") == 0


def test_topic_overlap_finds_a_shared_subject() -> None:
    assert topic_overlap("OpenAI ships GPT-6", "GPT-6 benchmarks leak from OpenAI") >= 2


# =============================== reporting =======================================
def test_diversity_report_exposes_homogeneity() -> None:
    events, items, sources = _many_events()
    ranked = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    chosen = select_diverse(ranked, 9, sources, rank=RankWeights(max_per_source=3, max_per_group=3))

    report = diversity_report(chosen, sources)
    assert report["slots"] == 9
    assert report["distinct_sources"] >= 2
    assert report["max_share"] <= 0.5
    assert report["scores"], "the report should explain individual placements"


def test_rank_events_is_deterministic() -> None:
    events, items, sources = _many_events()
    a = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    b = rank_events(events, items, sources, weights=WEIGHTS, now=NOW)
    assert [r.event.event_id for r in a] == [r.event.event_id for r in b]


def test_extract_entities_covers_the_ai_vocabulary() -> None:
    """`argon` and `antigravity` were added after the real head was full of them."""
    got = extract_entities("Google 发布 Gemini 4 Argon,Antigravity 免费开放")
    assert {"gemini", "argon", "google", "antigravity"} <= got
