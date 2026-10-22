"""A source the reader named gets a small, bounded lift in the ranking.

## The measurement that motivated it

TheRundownAI publishes one or two well-reported stories a day, and larger outlets usually carry
the same news. On the 2026-10-22 issue its `Anthropic Claude Duet` story appeared as
`Anthropic推出Claude Duet人工智能代理` credited to `rss:theverge-com-ai`; over a 36-hour window
TheRundownAI contributed one candidate and won zero slots. A source that never appears is not
what the reader asked for when naming that account.

## What the boost must not do

* It must not outrank a frontier model release. The vendor tiers top out at 1.45 (DeepSeek) for
  exactly this reason, so a source boost sits below them at 1.25.
* It must not change `max_per_source`. That cap exists so one prolific feed cannot fill an
  issue; a multiplier only reorders candidates that are already eligible.
* It must be keyed on a measured reason. An unexplained boost cannot be told apart from a bug.
"""

from __future__ import annotations

from aidaily.source_boost import SOURCE_BOOST, boost_for


def test_the_named_source_is_boosted() -> None:
    factor, which = boost_for(["rss:therundown-ai"])
    assert factor > 1.0
    assert which == "rss:therundown-ai"


def test_an_unlisted_source_is_not_boosted() -> None:
    factor, which = boost_for(["rss:theverge-com-ai"])
    assert factor == 1.0
    assert which == ""


def test_an_empty_list_is_not_boosted() -> None:
    assert boost_for([]) == (1.0, "")
    assert boost_for(None) == (1.0, "")


def test_a_mixed_event_takes_the_strongest_boost() -> None:
    """When a boosted source joins a multi-source event, the event carries the lift."""
    factor, which = boost_for(["rss:theverge-com-ai", "rss:therundown-ai"])
    assert factor == SOURCE_BOOST["rss:therundown-ai"]
    assert which == "rss:therundown-ai"


def test_the_boost_stays_below_the_vendor_tiers() -> None:
    """Otherwise who reported a story would outrank what the story is."""
    from aidaily.vendor_priority import VENDOR_TIERS

    strongest_vendor = max(VENDOR_TIERS.values())
    assert max(SOURCE_BOOST.values()) < strongest_vendor


def test_the_boost_reaches_the_score() -> None:
    """The multiplier has to be in the product, not merely computed beside it."""
    import inspect

    from aidaily import rank

    source = inspect.getsource(rank)
    assert "boost_factor" in source
    score_line = next(l for l in source.splitlines() if "frequency_factor * boost_factor" in l)
    assert score_line