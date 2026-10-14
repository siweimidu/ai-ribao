"""The ranking model, rebuilt around heat rather than around recency.

## What the three reference sites actually do

Measured, not assumed (`scripts/probe_ordering.py`):

| site | ordering rule |
|---|---|
| `daily.juya.uk` | **hand-edited**. Items carry `#1`, `#2`, … and no score is rendered anywhere. Gemini 4 Argon is `#1` because an editor decided it was the day's most important thing. |
| `ainewslog.com` | one entry per day, newest first. Ordering is purely chronological because the unit is *the issue*, not the story. |
| `hex2077.dev` | grouped by theme (产品与功能更新 / 前沿研究 / 行业展望 / 开源 TOP), with no explicit rank inside a group. |

None of them orders stories by "source category weight × recency decay". juya's ranking is
editorial judgement; hex2077's is thematic. That is the finding: the shape the digest should
imitate is **"the day's hottest thing first"**, and heat is a property of the story, not of
the feed it arrived on.

## What this module computes

`heat` is a bounded score in [0, 1] assembled from six signals, each normalised so that one
loud signal cannot dominate:

1. **corroboration** — how many *independent* sources ran it. This is the single strongest
   evidence that something matters, and it is what the whole dedup pipeline exists to
   measure. Feeds sharing a `dedup_group` count once.
2. **magnitude** — is this a frontier-lab model release (the juya `#1` case), an official
   announcement, or a blog post. Reuses `significance.py`.
3. **engagement** — points and comments where a source exposes them, log-scaled.
4. **reach** — how many distinct domains carried it, which is corroboration the reader can
   see rather than a count we assert.
5. **velocity** — how fast it accumulated coverage relative to its age. A story covered by
   four outlets in three hours is hotter than one covered by four over two days.
6. **freshness** — a *mild* decay with a floor. Deliberately the weakest term: the old
   model's failure was letting recency decide, and a story does not stop being the day's
   headline because it broke eleven hours ago.

The weights are declared in one place and sum to 1.0, so the model can be reasoned about
instead of tuned by feel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Event, NormalizedItem, SourceSpec
from .significance import significance


@dataclass(frozen=True)
class HeatWeights:
    """Signal weights. They sum to 1.0 by construction; `test_rank.py` asserts it."""

    #: Independent sources. The heaviest term: "many people are saying it" is the closest
    #: thing to an objective measure of newsworthiness this pipeline has.
    corroboration: float = 0.28
    #: Frontier-model release / official announcement. This is what makes Gemini 4 Argon
    #: lead the issue, and it is the term a pure engagement model cannot see.
    magnitude: float = 0.25
    #: Points and comments, where the source exposes them.
    engagement: float = 0.13
    #: Distinct domains covering it.
    reach: float = 0.11
    #: Whether there is an article behind the headline at all.
    #:
    #: Small on purpose. It exists to separate a real report from a title-only stub -- the
    #: "New Apple TV 4K / Points: 153" failure -- and *not* to reward length: a long
    #: aggregator post is not more important than a terse launch announcement.
    substance: float = 0.07
    #: How fast coverage accumulated.
    velocity: float = 0.09
    #: How recent. Among the smallest terms on purpose.
    freshness: float = 0.07

    #: Half-life for the freshness term, in hours.
    freshness_half_life_hours: float = 18.0
    #: Freshness never falls below this, so an important story from this morning still
    #: outranks a trivial one from five minutes ago.
    freshness_floor: float = 0.45
    #: Independent sources at which corroboration saturates.
    corroboration_reference: int = 6
    #: Hours over which velocity saturates.
    velocity_reference_hours: float = 6.0
    #: Body characters at which the substance term saturates. Set at roughly one paragraph,
    #: because the question it answers is "is there an article here", not "how long is it".
    substance_reference_chars: int = 400


def _corroboration(event: Event, weights: HeatWeights) -> float:
    """Normalised independent-source count.

    `log2` rather than linear: the step from one source to two is the meaningful one (it
    stops being a single unverified claim), while the step from nine to ten is not.
    """
    n = max(0, event.independent_source_count)
    if n == 0:
        return 0.0
    return min(1.0, math.log2(1.0 + n) / math.log2(1.0 + weights.corroboration_reference))


def _magnitude(event: Event) -> tuple[float, dict]:
    """How big the news itself is, independent of who reported it."""
    score, components = significance(
        event.title,
        independent_sources=event.independent_source_count,
        urls=event.all_urls,
    )
    # `significance` returns a multiplier with a floor of 1.0 and a ceiling of 3.2; map that
    # onto [0, 1] so it composes with the other normalised terms.
    normalised = max(0.0, min(1.0, (score - 1.0) / 2.2))
    return normalised, components


def _engagement(items: list[NormalizedItem]) -> float:
    """Points/comments, log-scaled. `stars_today` is excluded -- see `rank.py`."""
    best = 0.0
    for item in items:
        for key in ("points", "score", "comments", "num_comments", "ups", "votes"):
            value = item.metrics.get(key)
            if isinstance(value, (int, float)) and value > 0:
                best = max(best, float(value))
    if best <= 0:
        return 0.0
    # 1000 points is a strong signal; 10000 is not ten times stronger.
    return min(1.0, math.log10(1.0 + best) / 3.0)


def _reach(event: Event) -> float:
    """Distinct domains. Independent of `corroboration`, which counts sources.

    Two feeds from one publisher are two sources but one domain; the reader sees "how many
    places wrote about this", which is the domain count.
    """
    domains: set[str] = set()
    for url in event.all_urls:
        try:
            host = url.split("//", 1)[1].split("/", 1)[0].lower()
        except IndexError:
            continue
        domains.add(host[4:] if host.startswith("www.") else host)
    if not domains:
        return 0.0
    return min(1.0, math.log2(1.0 + len(domains)) / math.log2(5.0))


def _velocity(event: Event, now: datetime, weights: HeatWeights) -> float:
    """Coverage accumulated per hour of age.

    A story four outlets picked up within three hours is hotter than one four outlets picked
    up over two days. With a single timestamp this is approximated from the published range:
    a tight range with several sources means they moved together, which is what a fast-
    spreading story looks like.
    """
    if not event.published_range:
        return 0.0
    first = event.published_range[0]
    last = event.published_range[1] if len(event.published_range) > 1 else first
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now_cmp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    age_hours = max(0.5, (now_cmp - first).total_seconds() / 3600.0)
    spread_hours = max(0.0, (last - first).total_seconds() / 3600.0)
    sources = max(1, event.independent_source_count)

    # Sources per hour, damped by how long the story has had to accumulate.
    rate = sources / max(0.5, min(age_hours, spread_hours + 1.0))
    return min(1.0, rate / (1.0 / weights.velocity_reference_hours * 3.0))


def _substance(items: list[NormalizedItem], weights: HeatWeights) -> float:
    """Whether there is an article behind the headline.

    Not a length contest: it saturates at about one paragraph. What it rules out is a stub --
    an entry with a title and a point count and nothing else, which the model cannot
    summarise and the reader cannot act on.
    """
    best = 0
    for item in items:
        body = (item.content_text or item.summary or "").strip()
        best = max(best, len(body))
    if best <= 0:
        return 0.0
    return min(1.0, best / max(1, weights.substance_reference_chars))


def _freshness(event: Event, now: datetime, weights: HeatWeights) -> float:
    """Mild decay with a floor.

    The previous model made this the dominant term and the digest degenerated to "newest
    first" whenever nothing was corroborated. Here it is the weakest signal, and the floor
    means a major story from earlier today still outranks a trivial one from minutes ago.
    """
    when = event.published_range[0] if event.published_range else None
    if when is None:
        # Unknown freshness is neutral, not brand new. GitHub Trending has no dates, and
        # treating that as "just published" is how nine repositories reached the top nine.
        return 0.5
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now_cmp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now_cmp - when).total_seconds() / 3600.0)
    decayed = 0.5 ** (age_hours / max(1.0, weights.freshness_half_life_hours))
    return weights.freshness_floor + (1.0 - weights.freshness_floor) * decayed


def heat(
    event: Event,
    items_by_id: dict[str, NormalizedItem],
    *,
    now: datetime,
    weights: HeatWeights | None = None,
) -> tuple[float, dict]:
    """The heat of one event in [0, 1], plus every component that produced it.

    All components are returned so the page and the audit trail can explain a placement
    instead of asserting one. When a reader asks "why is this first", the answer is in the
    archived JSON.
    """
    w = weights or HeatWeights()
    members = [items_by_id[i] for i in event.member_item_ids if i in items_by_id]

    contrib = _corroboration(event, w)
    magnitude, magnitude_parts = _magnitude(event)
    engagement = _engagement(members)
    reach = _reach(event)
    substance = _substance(members, w)
    velocity = _velocity(event, now, w)
    freshness = _freshness(event, now, w)

    total = (
        w.corroboration * contrib
        + w.magnitude * magnitude
        + w.engagement * engagement
        + w.reach * reach
        + w.substance * substance
        + w.velocity * velocity
        + w.freshness * freshness
    )

    return round(total, 6), {
        "heat": round(total, 6),
        "h_corroboration": round(contrib, 4),
        "h_magnitude": round(magnitude, 4),
        "h_engagement": round(engagement, 4),
        "h_reach": round(reach, 4),
        "h_substance": round(substance, 4),
        "h_velocity": round(velocity, 4),
        "h_freshness": round(freshness, 4),
        # Kept for the placement report: the character count explains the substance term,
        # which is otherwise a bare 0..1 number nobody can evaluate.
        "substance_chars": float(max(
            (len((i.content_text or i.summary or "").strip()) for i in members), default=0
        )),
        **magnitude_parts,
    }
