"""Ranking: what goes at the top of the digest.

The first version ranked by `(-independent_source_count, -timestamp)`. On a day when no
event had independent corroboration that degenerates to **pure recency**, and the result
was concrete and bad: seven of the top ten entries were different angles on one topic
("Gemini 4 Argon"), all from the same source, while every lab blog sat below them.

Four signals replace it, each one aimed at a failure that was actually observed:

* **source weight** -- `quality.source_weights` already existed in the config and was
  never wired to anything. An official lab announcement outranks a link aggregator.
* **content substance** -- an entry whose body is only a headline cannot produce facts,
  and the digest proved it: "Title: New Apple TV 4K" / "Points: 153". Entries with no
  body are penalised rather than dropped, because they are still real news.
* **recency with a floor** -- exponential decay so fresh news leads, but a floor so a
  strong source's two-day-old post is not zeroed out by a link posted five minutes ago.
* **corroboration** -- several independent sources agreeing is evidence, and two feeds
  carrying the same content must not count twice (see `dedup_group`).

On top of the score, selection enforces **diversity**: a cap on how many entries one
source or one feed group may contribute, and a penalty for entries whose title closely
matches something already chosen. Ranking alone cannot fix homogeneity -- with 40 slots
and 60 candidates from three prolific feeds, the top 40 by score are still those three.

Every component is kept on the event so a ranking decision can be explained after the
fact rather than argued about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .entities import topic_overlap
from .heat import heat
from .models import Event, NormalizedItem, SourceSpec
from .normalize import title_similarity
from .titles import title_quality

#: Metric names read as an engagement signal. Deliberately excludes `stars_today`: a
#: repository gaining 1000 stars in a day is not 1000 points of news importance, and
#: because the scale is logarithmic it saturated at 1.0 for *every* trending repo --
#: which is what pushed nine GitHub repositories into the top nine slots.
_ENGAGEMENT_KEYS = ("points", "score", "ups", "likes", "replies", "num_comments")


@dataclass
class RankWeights:
    recency_half_life_hours: float = 12.0
    #: an old entry keeps this fraction of its score; without a floor, decay alone
    #: re-creates the pure-recency ranking this module exists to replace
    recency_floor: float = 0.25
    corroboration: float = 0.35
    content_substance: float = 0.45
    engagement: float = 0.20
    #: reference body length (characters) at which substance saturates
    substance_reference_chars: int = 600
    max_per_source: int = 2
    max_per_group: int = 3
    #: multiply the score of an entry whose title closely matches one already selected
    topic_similarity_penalty: float = 0.35
    topic_similarity_threshold: float = 0.55
    #: how many shared entities count as "the same topic". Two is the smallest number
    #: that means something: one shared entity is usually just "Google".
    topic_overlap_min: int = 2
    #: penalty applied per same-topic entry already selected
    topic_overlap_penalty: float = 0.45
    #: heavier penalty when the shared topic comes with a shared URL -- that is the same
    #: article, not a second source reporting it
    duplicate_url_penalty: float = 0.10


@dataclass
class RankedEvent:
    event: Event
    score: float
    components: dict[str, float] = field(default_factory=dict)


def _source_weight(source_id: str, sources: dict[str, SourceSpec], weights: dict[str, float]) -> float:
    spec = sources.get(source_id)
    if spec is None:
        return 1.0
    return float(weights.get(spec.category, 1.0))


def _substance(items: list[NormalizedItem]) -> float:
    """How much real text the event carries, 0-1.

    Uses the longest body among its items: one rich member is enough. `summary` counts
    because many feeds carry a meaningful summary and no full text.
    """
    longest = 0
    for item in items:
        longest = max(longest, len(item.content_text or ""), len(item.summary or ""))
    return longest


def _engagement(items: list[NormalizedItem]) -> float:
    best = 0.0
    for item in items:
        for key in _ENGAGEMENT_KEYS:
            value = item.metrics.get(key)
            if isinstance(value, (int, float)) and value > 0:
                best = max(best, float(value))
    if best <= 0:
        return 0.0
    # log scale and a /3 cap: 1000 points is a strong signal, 100000 is not 100x stronger
    return min(math.log10(1.0 + best) / 3.0, 1.0)


def _recency(event: Event, now: datetime, half_life_hours: float, floor: float) -> float:
    """Fraction of the score an entry keeps for being fresh.

    Undated entries get a *neutral* value, not the maximum. GitHub Trending's items have
    no publication date by construction, and handing them recency 1.0 meant a repository
    with a 40-character description outranked a lab announcement published six hours
    earlier -- "unknown freshness" is not "brand new". Neutral here means the same value
    as an entry that is exactly one half-life old.
    """
    when = event.published_range[0] if event.published_range else None
    if when is None:
        return floor + (1.0 - floor) * 0.5
    age_hours = max(0.0, (now - when).total_seconds() / 3600.0)
    decayed = 0.5 ** (age_hours / max(0.5, half_life_hours))
    return floor + (1.0 - floor) * decayed


def score_event(
    event: Event,
    items_by_id: dict[str, NormalizedItem],
    sources: dict[str, SourceSpec],
    weights: dict[str, float],
    rank: RankWeights,
    now: datetime,
) -> RankedEvent:
    """Score one event for placement.

    The shape changed after reading how the reference sites actually order their content
    (`scripts/probe_ordering.py`, and the analysis in `heat.py`):

    **Before** — `source_weight × quality × recency × title × significance`. A product of
    multipliers, where a frontier-lab release and a chat-app point release differed only by
    the 1.5-vs-1.1 source category, and recency was a first-class factor. On a real day that
    put `Gemini 4 Argon: Built to solve your hardest problems` at position 58 of 60.

    **Now** — a normalised `heat` score in [0, 1] is the primary term, and the surviving
    multipliers are demotions rather than promotions:

    * `title_factor` — a container entry (`2026-10-14`) is discounted, never dropped.
    * `source_weight` — kept, but **heavily damped** (`^0.25`). A tier-1 lab still has an
      edge, but it can no longer carry a trivial post past a competitor's launch: with the
      raw weight, a 1.5 lab blog outranked everything from a 1.1 media source regardless of
      what either said.

    Substance (body length) is reported but no longer scored. It measured article *size*,
    and a long aggregator post is not more important than a terse launch announcement --
    which is exactly the error it produced.
    """
    members = [items_by_id[i] for i in event.member_item_ids if i in items_by_id]
    source_weight = max(
        (_source_weight(s, sources, weights) for s in event.source_ids), default=1.0
    )
    # Damped: the ranking must be about the story, not the letterhead.
    damped_source = source_weight ** 0.25

    substance_raw = _substance(members)

    heat_score, heat_components = heat(event, items_by_id, now=now)

    # A feed entry titled `2026-10-14` is a container, not a story. Demoted, never dropped.
    title_factor = title_quality(event.title)

    # `heat` already covers freshness; the old multiplicative recency term is gone, because
    # multiplying an independent decay on top of a normalised score is what made "newest
    # first" the effective rule whenever nothing was corroborated.
    score = heat_score * damped_source * title_factor * 100

    return RankedEvent(
        event=event,
        score=round(score, 6),
        components={
            "source_weight": round(source_weight, 3),
            "source_damped": round(damped_source, 4),
            "substance": round(min(substance_raw / max(1, rank.substance_reference_chars), 1.0), 3),
            "substance_chars": float(substance_raw),
            "title_quality": round(title_factor, 3),
            **heat_components,
            "score": round(score, 6),
        },
    )


def rank_events(
    events: list[Event],
    items: list[NormalizedItem],
    sources: list[SourceSpec],
    *,
    weights: dict[str, float] | None = None,
    rank: RankWeights | None = None,
    now: datetime | None = None,
) -> list[RankedEvent]:
    items_by_id = {i.item_id: i for i in items}
    sources_by_id = {s.source_id: s for s in sources}
    rank = rank or RankWeights()
    now = now or datetime.now(timezone.utc)

    scored = [
        score_event(e, items_by_id, sources_by_id, weights or {}, rank, now) for e in events
    ]
    scored.sort(key=lambda r: (-r.score, r.event.event_id))
    return scored


def _group_of(event: Event, sources: dict[str, SourceSpec]) -> str | None:
    """The feed group an event belongs to, or None when it belongs to no group.

    Only sources that *declare* a `dedup_group` are grouped. Treating every source as its
    own group looked harmless and was not: with ~10 contributing sources and
    `max_per_group=3`, the group cap silently became a hard ceiling of ~30 entries on a
    60-slot digest. The cap exists to stop two feeds carrying the same content from
    occupying several slots as if they were separate sources -- it is not a per-source
    quota, which `max_per_source` already handles.
    """
    groups = {
        sources[s].dedup_group for s in event.source_ids
        if s in sources and sources[s].dedup_group
    }
    return sorted(groups)[0] if groups else None


def select_diverse(
    ranked: list[RankedEvent],
    limit: int,
    sources: list[SourceSpec],
    *,
    rank: RankWeights | None = None,
) -> list[RankedEvent]:
    """Take the top `limit`, enforcing source and topic diversity.

    Greedy with penalties rather than a hard filter: a source that is genuinely the only
    one reporting something still gets in, it just cannot take every slot.

    The first version had a backfill step that ignored the caps entirely, on the theory
    that an under-filled digest is worse than a slightly homogeneous one. It is not. The
    caps admit roughly `sources x max_per_source` entries -- about 34 of a 60-slot
    digest -- so the backfill ran on every single run and handed the remaining 26 slots
    to whichever feeds were most prolific. That is precisely the homogeneity the caps
    exist to prevent, and it is how nine GitHub repositories reached the top nine.

    Backfill now relaxes the per-source cap to a hard share of the digest instead of
    dropping it.
    """
    rank = rank or RankWeights()
    sources_by_id = {s.source_id: s for s in sources}
    per_source: dict[str, int] = {}
    per_group: dict[str, int] = {}
    chosen: list[RankedEvent] = []

    #: no single source may exceed this share of the digest, whatever the caps say.
    #: The 20% floor matters: with few sources, `ceil(limit * 0.2)` can be smaller than
    #: `sources * cap`, and the digest becomes mathematically unfillable -- a 12-slot
    #: digest over 3 sources with a ceiling of 3 can only ever hold 9 entries.
    source_ceiling_floor = max(2, -(-limit // 4))  # at least a quarter of the digest
    hard_source_ceiling = max(rank.max_per_source, min(-(-limit * 20 // 100), source_ceiling_floor))

    def take(candidate: RankedEvent) -> None:
        chosen.append(candidate)
        for source_id in candidate.event.source_ids:
            per_source[source_id] = per_source.get(source_id, 0) + 1
        group = _group_of(candidate.event, sources_by_id)
        if group is not None:
            per_group[group] = per_group.get(group, 0) + 1

    def over_source_cap(candidate: RankedEvent, cap: int) -> bool:
        return any(per_source.get(s, 0) >= cap for s in candidate.event.source_ids)

    def over_group_cap(candidate: RankedEvent, cap: int) -> bool:
        group = _group_of(candidate.event, sources_by_id)
        if group is None:
            return False
        return per_group.get(group, 0) >= cap

    def topic_penalty(candidate: RankedEvent) -> float:
        """How much to discount a candidate that repeats a topic already chosen.

        Entity overlap catches what raw similarity misses. Measured on real output:
        "Gemini 4 Argon: Built to solve your hardest problems" vs "Gemini 4 Argon for
        Robotics" scores 0.557 -- right at the threshold, so the string rule fires or not
        depending on rounding -- while "Google 发布 Gemini 4 Argon..." against the Latin
        headline scores 0.31 and never fires at all. Both are obviously one story.

        Two different things get damped, and they are damped differently:

        * **the same article** (identical URL, which L2 should already have merged):
          a heavy discount, because it is a duplicate that slipped through.
        * **a different article about the same subject**: a lighter discount. "The Verge
          reports Apple's HomeView launch" and "Apple's own HomeView page" are two real
          sources and both belong in the digest; they just should not sit adjacent.

        Treating both the same was too blunt: a genuine second source was pushed from
        position 10 to position 50.

        Applied in **both** passes. Applying it only in the first was worse than not
        applying it at all: penalised entries sank in the final sort, and the second pass
        then re-admitted the very same entries at full score.
        """
        urls = set(candidate.event.all_urls)
        penalty = 1.0
        for already in chosen:
            if title_similarity(already.event.title, candidate.event.title) >= rank.topic_similarity_threshold:
                penalty *= rank.topic_similarity_penalty
            if topic_overlap(already.event.title, candidate.event.title) >= rank.topic_overlap_min:
                if urls & set(already.event.all_urls):
                    penalty *= rank.duplicate_url_penalty
                else:
                    penalty *= rank.topic_overlap_penalty
        return penalty

    def consider(candidate: RankedEvent) -> None:
        penalty = topic_penalty(candidate)
        candidate.components["topic_penalty"] = round(penalty, 4)
        candidate.score = round(candidate.score * penalty, 6)
        candidate.components["final_score"] = candidate.score
        take(candidate)

    # --- pass 1: strict caps --------------------------------------------------------
    for candidate in ranked:
        if len(chosen) >= limit:
            break
        if over_source_cap(candidate, rank.max_per_source) or over_group_cap(candidate, rank.max_per_group):
            continue
        consider(candidate)

    # --- pass 2: relax the per-source cap to the hard ceiling, keep the group cap ------
    # The group cap is NOT relaxed. Relaxing both was the same mistake as the original
    # unbounded backfill: with six candidates from one dedup_group and few alternatives,
    # dropping the group cap let that group take the entire digest. A group is the unit
    # readers actually perceive as repetition.
    if len(chosen) < limit:
        for candidate in ranked:
            if len(chosen) >= limit:
                break
            if any(candidate is c for c in chosen):
                continue
            if over_source_cap(candidate, hard_source_ceiling):
                continue
            if over_group_cap(candidate, rank.max_per_group):
                continue
            consider(candidate)

    # --- pass 3: fill the digest even if that means relaxing the per-source ceiling ----
    # Order matters. Pass 1 enforces both caps; pass 2 relaxes the per-source cap but
    # keeps the group cap; pass 3 relaxes the per-source ceiling entirely but still
    # respects the group cap.
    #
    # The reason pass 3 exists at all: a digest that is half empty is a worse outcome than
    # a slightly repetitive one. Measured on real data, a strict `max_per_group=3` over
    # eight independent sources produced 29 entries for a 60-slot digest -- the ranking
    # work silently halved the product.
    #
    # The group cap is never lifted: a group is the unit a reader perceives as repetition,
    # and letting one group take every slot is the failure this module was written to fix.
    if len(chosen) < limit:
        for candidate in ranked:
            if len(chosen) >= limit:
                break
            if any(candidate is c for c in chosen):
                continue
            if over_group_cap(candidate, rank.max_per_group):
                continue
            consider(candidate)

    chosen.sort(key=lambda r: (-r.score, r.event.event_id))
    return chosen


def diversity_report(chosen: list[RankedEvent], sources: list[SourceSpec]) -> dict[str, object]:
    """Numbers that make homogeneity visible instead of a matter of opinion."""
    sources_by_id = {s.source_id: s for s in sources}
    counts: dict[str, int] = {}
    for row in chosen:
        for source_id in row.event.source_ids:
            counts[source_id] = counts.get(source_id, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
    total = sum(counts.values())
    return {
        "slots": len(chosen),
        "distinct_sources": len(counts),
        "top_sources": [
            {
                "source_id": sid,
                "count": n,
                "category": (sources_by_id[sid].category if sid in sources_by_id else "?"),
            }
            for sid, n in top
        ],
        "max_share": round(top[0][1] / total, 3) if top and total else 0.0,
        "scores": [
            {"title": r.event.title[:60], "score": r.score, **{k: v for k, v in r.components.items() if k != "score"}}
            for r in chosen[:5]
        ],
    }
