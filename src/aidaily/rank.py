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
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .entities import topic_overlap
from .focus import focus_multiplier
from .unfiltered import AIHOT_BOOST, is_aihot, distinct_source_groups
from .frequency import cross_source_score, frequency_index
from .source_boost import boost_for as source_boost_for
from .vendor_priority import components as vendor_components
from .vendor_priority import vendor_priority as vendor_priority_of
from .heat import heat
from .designation import designation
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

    #: Body length below which a story counts as a bare headline.
    #:
    #: Not a deletion test: it caps how far a thin entry can climb.
    substance_thin_chars: int = 300
    max_per_source: int = 2
    max_per_group: int = 3
    #: Entries allowed per model designation in one issue. One: the reader treats a model
    #: name appearing repeatedly as the same news, even when the events differ.
    max_per_model: int = 1
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


#: How much of the neutral recency an old repository keeps.
#:
#: A GitHub Trending entry has no publication date, so the neutral value above applies. But
#: "no date" hides two very different things: a repository created last week (news) and one
#: created two years ago that merely had a busy afternoon (not news). Measured 2026-10-23:
#: `anthropics/knowledge-work-plugins` sat at position 3 with a score of 9.75; GitHub says it
#: was created 2026-01-23 -- nine months earlier. It appeared on Trending because a commit
#: landed that morning, which is a star-delta window, not a release.
#:
#: Keyed on the repository creation date carried in `metrics`, which the fetcher fills from the
#: Trending page and `github_meta` fills from the API. Absent means unknown, and unknown keeps
#: the neutral value: guessing here would silently bury new projects whose metadata the API
#: declined to return.
_REPO_AGE_FACTORS = (
    (14, 1.0),      # two weeks: genuinely new
    (60, 0.75),     # two months: recent
    (365, 0.45),    # a year: an established project having a day
    (10**6, 0.2),   # older than that: an old project trending again
)


def _repository_novelty(
    event: Event, items_by_id: dict[str, NormalizedItem] | None
) -> float:
    """A multiplier for undated entries based on how old the repository itself is."""
    created = ""
    for item_id in event.member_item_ids:
        item = (items_by_id or {}).get(item_id)
        if item is not None:
            created = str((item.metrics or {}).get("repo_created") or "")
            if created:
                break
    if not created:
        return 1.0
    try:
        when = datetime.fromisoformat(created[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return 1.0
    age_days = max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 86400)
    for limit, factor in _REPO_AGE_FACTORS:
        if age_days <= limit:
            return factor
    return _REPO_AGE_FACTORS[-1][1]


def _recency(
    event: Event,
    now: datetime,
    half_life_hours: float,
    floor: float,
    items_by_id: dict[str, NormalizedItem] | None = None,
) -> float:
    """Fraction of the score an entry keeps for being fresh.

    Undated entries get a *neutral* value, not the maximum. GitHub Trending's items have
    no publication date by construction, and handing them recency 1.0 meant a repository
    with a 40-character description outranked a lab announcement published six hours
    earlier -- "unknown freshness" is not "brand new". Neutral here means the same value
    as an entry that is exactly one half-life old.
    """
    when = event.published_range[0] if event.published_range else None
    if when is None:
        return floor + (1.0 - floor) * 0.5 * _repository_novelty(event, items_by_id)
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
    frequency: Counter[str] | None = None,
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
    # `focus_multiplier` needs a lookup by id, and the caller passes a list.
    source_index = {s.source_id: s for s in sources} if not isinstance(sources, dict) else sources
    members = [items_by_id[i] for i in event.member_item_ids if i in items_by_id]
    source_weight = max(
        (_source_weight(s, sources, weights) for s in event.source_ids), default=1.0
    )
    # Damped: the ranking must be about the story, not the letterhead.
    damped_source = source_weight ** 0.25

    substance_raw = _substance(members)
    # **A headline is not a story.**
    #
    # Substance used to be reported but never scored, and the cost is visible on the page: on
    # 2026-10-30 position #02 was 「中国首个 AI 定义芯片诞生」, a Google News re-index whose
    # whole body is the headline. Its facts were 「报道标题称…」 and every 不确定 line read 未提及.
    # The reader learned nothing, and it outranked complete stories.
    #
    # The factor is bounded: a thin entry keeps 35% of its score, so it can still appear at the
    # tail of the issue but cannot lead it. Nothing is deleted.
    substance_factor = 0.35 + 0.65 * min(
        1.0, substance_raw / max(1, rank.substance_thin_chars)
    )


    heat_score, heat_components = heat(event, items_by_id, now=now)

    # A feed entry titled `2026-10-14` is a container, not a story. Demoted, never dropped.
    title_factor = title_quality(event.title)

    # **Is this story about AI at all?**
    #
    # Every other term in the heat model measures attention -- corroboration, engagement,
    # reach, velocity -- and none of them asks what the story is about. Measured against
    # `daily.juya.uk` for 2026-10-14: of this digest's top twenty, five were AI stories and
    # the rest included an Apple smart speaker, Xbox game ports, Ray-Ban glasses, a DLSS
    # patch, and V2EX chatter about mortgage debt and splitting a Wi-Fi network into two
    # bands -- all of them scoring 0.36, level with real AI news.
    #
    # Applied as a multiplier rather than a rank term because relevance is closer to a
    # precondition than to a peer of "how many outlets covered it". It never reaches zero:
    # demote, never delete, so a quiet day still prints and a borderline item can still lead
    # if it is genuinely the day's biggest thing.
    # `items_by_id` lets the focus score read the body when the title carries no signal.
    # Digest feeds title an issue by its date (`DailyDawn · 2026-10-15`), which measured 0.18
    # against the 0.70 relevance floor while the body held 20941 characters of AI text.
    focus_factor, focus_components = focus_multiplier(
        event, source_index, items_by_id=items_by_id
    )

    # **Editorial priority for Chinese model vendors** (explicit user instruction):
    # DeepSeek > Kimi > GLM > MiniMax/Qwen/豆包/阶跃星辰/元宝, all above the rest.
    #
    # A multiplier, not a sort key: ordering by vendor before looking at the news would put a
    # routine version bump above a frontier release. And it is keyed on the vendor being the
    # *subject* of the headline -- UCSD 用 DeepSeek V4.1-Flash 做机械臂 is a robotics story
    # that happens to use DeepSeek, and boosting it would outrank DeepSeek's own news.
    vendor_factor = 1.0
    for candidate in (event.title, *(m.title for m in members[:3] if hasattr(m, "title"))):
        factor, vendor = vendor_priority_of(candidate)
        if factor > vendor_factor:
            vendor_factor = factor
            vendor_components_result = vendor_components(candidate)
    if vendor_factor == 1.0:
        vendor_components_result = {"vendor_priority": 1.0, "vendor_subject": ""}

    # `heat` already covers freshness; the old multiplicative recency term is gone, because
    # multiplying an independent decay on top of a normalised score is what made "newest
    # first" the effective rule whenever nothing was corroborated.
    # **Cross-source keyword frequency, taken from TrendRadar.**
    #
    # `heat._corroboration` counts publishers carrying *this* event. It cannot see that
    # a model name is turning up in unrelated stories all over the day -- which is what a
    # reader means by "this is the thing right now".
    #
    # Damped hard (`^0.15` on a 0.85-1.0 band): it breaks ties between stories of similar
    # weight, and must never lift a routine post above a frontier release. Measured on the
    # 2026-10-21 issue, a full-strength term promoted one press release above every model
    # announcement that day.
    # **Per-source editorial boost** (reader request: surface one specific account).
    #
    # Kept below the vendor tiers: `DeepSeek 1.45` says a vendor announcement matters more than
    # which outlet carried it. This term only reorders candidates that are already close, which
    # is what it takes for a source publishing one story a day to win a slot against outlets
    # that cover the same event.
    boost_factor, boost_source = source_boost_for(event.source_ids or [])

    frequency_factor = 1.0
    frequency_terms: list[str] = []
    if frequency:
        raw_freq, frequency_terms = cross_source_score(event.title, frequency)
        frequency_factor = 0.85 + 0.15 * raw_freq

    # **aihot items are still filtered, but they rank higher.**
    #
    # 「aihot.news的信息仍然要筛选一遍，只是来自aihot.news的信息天然要高些」. The boost
    # is a multiplier, so it cannot lift a story past the relevance gate -- that gate runs
    # before ranking and stays. It only reorders what already qualified.
    aihot_factor = AIHOT_BOOST if any(is_aihot(sid) for sid in (event.source_ids or ())) else 1.0

    score = (
        heat_score * damped_source * title_factor * focus_factor * vendor_factor
        * frequency_factor * boost_factor * aihot_factor * substance_factor * 100
    )

    return RankedEvent(
        event=event,
        score=round(score, 6),
        components={
            "source_weight": round(source_weight, 3),
            "source_damped": round(damped_source, 4),
            "substance": round(min(substance_raw / max(1, rank.substance_reference_chars), 1.0), 3),
            "substance_chars": float(substance_raw),
            "substance_factor": round(substance_factor, 3),
            "title_quality": round(title_factor, 3),
        "source_boost": round(boost_factor, 3),
            "aihot_boost": round(aihot_factor, 3),
            **heat_components,
            **focus_components,
            **vendor_components_result,
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

    # **One title per event, not per article.** Five outlets covering one press release is
    # corroboration, which `heat` already measures; feeding those five titles here would count
    # the same fact twice and promote a single announcement to "the industry is talking about
    # this". Measured on the 2026-10-21 issue: article-level titles made 物理 the top term with
    # five hits, all five from the same conference.
    frequency = frequency_index([e.title for e in events if e.title])

    scored = [
        score_event(e, items_by_id, sources_by_id, weights or {}, rank, now, frequency)
        for e in events
    ]
    scored.sort(key=lambda r: (-r.score, r.event.event_id))

    # One entry per release: the several phrasings of one launch collapse into the best-scoring
    # one and carry the union of their sources. Without this the digest repeats the same news
    # down the page.
    # The surviving row keeps its **own** components. Returning empty ones wiped `focus`
    # for every event, and `select_for_digest` then dropped all of them as
    # `missing_or_invalid_focus` -- on 2026-10-19 that published 0 of 220 events while the
    # titles were plainly AI ("MiniMax 将发布 M3.1-Flash", "DeepSeek上新AI模型").
    #
    # The merge only unions member ids, sources and URLs onto the survivor; its score and
    # components were computed from its own text and remain valid for it.
    by_id = {r.event.event_id: r for r in scored}
    collapsed = collapse_by_designation([r.event for r in scored])
    if len(collapsed) != len(scored):
        return [by_id[e.event_id] for e in collapsed if e.event_id in by_id]
    return scored


#: Reports further apart than this are treated as separate events even when they name the same
#: model. 72 hours matches the L2 deduplicator's own publish window, so the two stages agree
#: about what "the same coverage" means.
SAME_STORY_WINDOW_HOURS = 72


def _within_same_story_window(left: Event, right: Event) -> bool:
    a = left.first_seen_at or left.last_updated_at
    b = right.first_seen_at or right.last_updated_at
    if a is None or b is None:
        return True
    return abs((a - b).total_seconds()) <= SAME_STORY_WINDOW_HOURS * 3600


def collapse_by_designation(events: list[Event]) -> list[Event]:
    """Merge events that report the same model release into one.

    ## The problem, measured

    On 2026-10-17 four entries described the DeepSeek V4.1 Flash launch and occupied positions 2,
    3, 4 and 13. The reader sees one piece of news four times; the cause is that each outlet
    phrased the headline differently, so `coarse_clusters` -- which needs two shared entities
    inside a 6-hour bucket -- never grouped them.

    ## Why designation rather than title similarity

    Similarity would also fold "DeepSeek opens its own search API" into the launch, since the two
    share a vendor. The designation key is absent from the API story, so that one stays its own
    event -- exactly the separation the user asked for.

    ## What merging does

    Member ids, source ids and URLs are unioned so the surviving entry carries the full
    corroboration. The **title and score are left untouched**: re-scoring a merged event against
    a rewritten headline decoupled the number from what was ranked (measured: rewriting the
    title dropped a launch from 93.8 to 61.4 and handed first place to an unrelated story).
    """
    from .designation import designation, designations

    kept: list[Event] = []
    index: dict[str, int] = {}
    for event in events:
        # A headline naming two releases is a roundup, not a report of one: it must neither take
        # a designation nor be merged into either launch it lists.
        if len(designations(event.title)) > 1:
            kept.append(event)
            continue
        key = designation(event.title)
        if key is None or key not in index:
            if key is not None:
                index[key] = len(kept)
            kept.append(event)
            continue

        target = kept[index[key]]
        if not _within_same_story_window(target, event):
            kept.append(event)
            continue

        for member in event.member_item_ids:
            if member not in target.member_item_ids:
                target.member_item_ids.append(member)
        for source in event.source_ids:
            if source not in target.source_ids:
                target.source_ids.append(source)
        for url in event.all_urls:
            if url not in target.all_urls:
                target.all_urls.append(url)
        # **Recompute, do not take the max.**
        #
        # `max` was right while every event here came from deterministic clustering, where a
        # merge could only be as corroborated as its best member. After the LLM pass unions
        # source lists first, this pass can join two events that are *each* already
        # multi-source, so the union is the honest number.
        target.independent_source_count = distinct_source_groups(target.source_ids)
        if target.independent_source_count >= 2:
            target.evidence_level = "multi_source"

        # **Carry forward what the LLM pass already merged.**
        #
        # This rebuilt the list from the two titles joined here, discarding the ones the
        # earlier merge had recorded. Measured 2026-10-24: the log said "4 条 Kimi 合并成 1 条"
        # while the archive held `merged_titles: 0` for that entry -- the evidence was dropped
        # on the way through, so the page could not show what the other outlets called it.
        candidates = list(target.unique_facts.get("merged_titles") or [])
        candidates += list(event.unique_facts.get("merged_titles") or [])
        for title in (target.title, event.title):
            if title and title not in candidates:
                candidates.append(title)
        target.unique_facts["merged_titles"] = candidates
        if event.first_seen_at and target.first_seen_at:
            target.first_seen_at = min(target.first_seen_at, event.first_seen_at)
        if event.last_updated_at and target.last_updated_at:
            target.last_updated_at = max(target.last_updated_at, event.last_updated_at)
    # **Every surviving event, not only the merged ones.**
    #
    # The correction above runs inside the merge branch, so an event that passed through
    # unmerged kept whatever label it arrived with. Measured 2026-10-24: the LLM pass unioned
    # three sources onto the Kimi entry and left `evidence_level` at `single_source`; `factcheck`
    # rejects exactly that combination, and the whole issue failed to publish three times.
    for event in kept:
        event.independent_source_count = distinct_source_groups(event.source_ids)
        if event.independent_source_count >= 2:
            event.evidence_level = "multi_source"
        elif event.evidence_level == "multi_source":
            # A claim of corroboration must not survive a recount that finds one source.
            event.evidence_level = "single_source"
    return kept


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

    #: Identity is `event_id`, not object identity.
    #:
    #: Measured 2026-10-27: the published issue carried **10 events twice**. `top_events` held
    #: 130 rows for 120 stories, so the page rendered two `<li id="e-...">` with the same id and
    #: every `href="#e-..."` resolved to the first of them. The user reported it as the table of
    #: contents jumping to the wrong story: clicking entry 32 landed on entry 3.
    #:
    #: The cause was here. Pass 1 had no duplicate check at all, and passes 2 and 3 compared with
    #: `candidate is c` -- object identity -- which cannot see two RankedEvent objects built for
    #: the same event. `consider()` also re-applies a topic penalty, so the two copies ended up
    #: with *different* scores and were sorted far apart: positions 3 and 32, not side by side.
    def already_chosen(candidate: RankedEvent) -> bool:
        return any(c.event.event_id == candidate.event.event_id for c in chosen)

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

    #: model designation -> how many entries already chosen from it.
    #:
    #: The user reads "Gemini 4 Argon" three times in one issue as repetition even when the
    #: three entries are genuinely different events (robotics model, general availability,
    #: safety write-up -- measured pairwise similarity 0.38..0.52, so no similarity rule fires).
    #: A model is the unit a reader perceives as "this again", so it gets a hard cap: one per
    #: issue. The cap is not applied to sources or groups, which already have their own.
    per_model: dict[str, int] = {}
    model_cap = rank.max_per_model

    def over_model_cap(candidate: RankedEvent) -> bool:
        model = designation(candidate.event.title)
        if model is None:
            return False
        return per_model.get(model, 0) >= model_cap

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
        model = designation(candidate.event.title)
        if model:
            per_model[model] = per_model.get(model, 0) + 1
        take(candidate)

    # --- pass 1: strict caps --------------------------------------------------------
    for candidate in ranked:
        if len(chosen) >= limit:
            break
        if already_chosen(candidate):
            continue
        if (
            over_source_cap(candidate, rank.max_per_source)
            or over_group_cap(candidate, rank.max_per_group)
            or over_model_cap(candidate)
        ):
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
            if already_chosen(candidate):
                continue
            if over_source_cap(candidate, hard_source_ceiling):
                continue
            if over_group_cap(candidate, rank.max_per_group):
                continue
            if over_model_cap(candidate):
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
            if already_chosen(candidate):
                continue
            if over_group_cap(candidate, rank.max_per_group):
                continue
            if over_model_cap(candidate):
                continue
            consider(candidate)

    chosen.sort(key=lambda r: (-r.score, r.event.event_id))
    # Belt and braces: the page numbers its rows and its table of contents from this list, and a
    # repeated event_id makes the two disagree about where a story is.
    unique: list[RankedEvent] = []
    seen_ids: set[str] = set()
    for entry in chosen:
        if entry.event.event_id in seen_ids:
            continue
        seen_ids.add(entry.event.event_id)
        unique.append(entry)
    return unique


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
