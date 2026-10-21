"""How much a source's own reporting is worth, and what that does to the bar.

## Why tiers exist

A headline from OpenAI's own blog and the same headline re-reported by a content farm are not
the same evidence. The digest already knew that in a crude way -- `category` was used for section
labelling -- but the *selection bar* was one number for everything, so a T2 repost of a rumour
competed on equal terms with a first-party announcement.

AIHOT settles this with tiers that move the threshold: a first-party post enters at 60, a
verified official account at 65, media and individuals at 76. That is the mechanism copied here,
because it fixes a real complaint on this project: commercial activity kept outranking model
releases no matter how the weights were tuned. A weight is a multiplier and a multiplier cannot
separate two things that are genuinely close; a threshold can.

## The three tiers

* **T1 -- first party.** The company or project itself: official blogs, labs, release feeds.
  These are the primary evidence. Threshold is the lowest.
* **T1_5 -- official-adjacent.** A verified account or a well-known project's own channel that
  is not the corporate blog: a maintainer's repo, an engineering team feed.
* **T2 -- everyone else.** Media, aggregators, community, personal blogs. Reported news, not
  primary evidence, so the bar is highest.

Derived from `category` rather than stored per source, so the 124 rows in the registry keep
working without a migration, and a new source inherits the right tier from its category.
"""

from __future__ import annotations

#: category -> tier. Anything not listed falls to T2, which is the safe default: an unknown
#: source is treated as reported news, not as primary evidence.
CATEGORY_TIER: dict[str, str] = {
    # First party.
    "lab-official": "T1",
    "model": "T1",
    "dataset": "T1",
    "product": "T1",
    # Official-adjacent: a project's own channel, not the corporate blog.
    "lab-blog": "T1_5",
    "dev": "T1_5",
    "trend": "T1_5",
    "search": "T1_5",
    # Reported news.
    "media": "T2",
    "zh-media": "T2",
    "news": "T2",
    "community": "T2",
    "social": "T2",
    "paper": "T2",
    "digest": "T2",
    "mixed": "T2",
    "preset": "T2",
    "example": "T2",
}

#: Tier -> the selection threshold a model score must clear.
#:
#: Calibrated on 118 archived events. The model scores cluster at 70 (median), with a quartile at
#: 50, and very little between 55 and 68: a bar of 75 keeps only 25% of what was actually
#: published, which on 2026-10-21 turned 88 candidates into 6.
#:
#:     bar 65 -> 53% kept     bar 70 -> 51% kept     bar 75 -> 25% kept
#:
#: The three tiers sit around the median rather than above it: a tier decides *which bar* a
#: story must clear, not whether real news gets in at all. Re-measure with
#: `scripts/calibrate.py` after changing the scoring prompt -- the distribution decides the
#: number, not the other way round.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "T1": 55.0,
    "T1_5": 60.0,
    "T2": 68.0,
}

Tiers = ("T1", "T1_5", "T2")


def tier_of(category: str | None) -> str:
    """The tier a source belongs to, from its category."""
    return CATEGORY_TIER.get((category or "").strip().lower(), "T2")


def threshold_for(category: str | None, thresholds: dict[str, float] | None = None) -> float:
    """The score a source of this category must reach to be selected."""
    table = thresholds or DEFAULT_THRESHOLDS
    return float(table.get(tier_of(category), table["T2"]))


def passes(score: float, category: str | None, thresholds: dict[str, float] | None = None) -> bool:
    """Whether a score clears the bar for that source's tier."""
    return float(score) >= threshold_for(category, thresholds)
