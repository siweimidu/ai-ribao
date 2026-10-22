"""Per-source editorial boost, for a source whose coverage is scarce but worth surfacing.

## Why this exists

TheRundownAI publishes one or two stories a day and they are well-reported, but its news is
usually covered by larger outlets too. Measured on the 2026-10-22 issue: its `Anthropic Claude
Duet` story was published as `Anthropic推出Claude Duet人工智能代理`, credited to
`rss:theverge-com-ai` — the same event, carried by a source that `max_per_source` preferred.

On a 36-hour window TheRundownAI contributed **one** candidate. Losing that one to a competitor
means the source contributes nothing at all, which is not what "把这个账号的消息放进来" asks for.

## Why a multiplier and not a filter

`max_per_source` exists so one prolific feed cannot fill the issue. Raising a source above that
cap would be a filter change with broad effects; a multiplier only reorders stories that are
already candidates, and it is capped low enough that a routine item cannot outrank a frontier
model release.

## How the boost is bounded

A 1.25 multiplier has to beat `max_per_source` only when the stories are otherwise close. The
heat model already damps source weight by `** 0.25`, so this is deliberately smaller than the
vendor tiers (DeepSeek 1.45) — a vendor announcement is more important than who reported it.
"""

from __future__ import annotations

#: Source id -> multiplier. Only sources the reader named explicitly belong here, and each entry
#: needs a measured reason: an unexplained boost is indistinguishable from a bug.
SOURCE_BOOST: dict[str, float] = {
    # Reader request, 2026-10-22: "只关注这个账号的消息". Its stories are usually also covered
    # by The Verge and TechCrunch, so without a boost it never wins the slot.
    "rss:therundown-ai": 1.25,
}


def boost_for(source_ids: list[str]) -> tuple[float, str]:
    """`(multiplier, source_id)` for an event, taking the strongest listed source.

    `(1.0, "")` when none of the event's sources is boosted.
    """
    best = 1.0
    which = ""
    for sid in source_ids or []:
        factor = SOURCE_BOOST.get(sid)
        if factor and factor > best:
            best = factor
            which = sid
    return best, which
