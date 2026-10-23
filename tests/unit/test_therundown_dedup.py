"""One publisher with two feeds must count as one witness.

## The measured case

The Rundown AI is reachable two ways: its beehiiv feed (`rss:rss-beehiiv-com-2r3c6bt5wj`, in the
registry from the audited ledger) and its site feed (`rss:therundown-ai`, added 2026-10-22).
Both carry the same newsletter. On the 2026-10-22 run,
`Sam Altman's three endings for the AI safety race` matched itself at title similarity **1.00**
across the two ids.

Without a shared `dedup_group` the publisher recovery labelled them differently --
`agg:rss.beehiiv.com` (a beehiiv feed is read as an aggregator) versus `p:therundown-ai` -- so one
article became two independent witnesses. `heat`'s heaviest term is corroboration, so that
inflates the score of exactly the story the duplicate came from.

## What this pins

* both ids resolve to one publisher;
* the override is what does it, not an accident of the ids;
* no other source silently joins the group.
"""

from __future__ import annotations

from pathlib import Path

from aidaily.l3 import _publisher_of
from aidaily.registry import apply_overrides, load_overrides, load_registry

BEEHIIV = "rss:rss-beehiiv-com-2r3c6bt5wj"
SITE = "rss:therundown-ai"
GROUP = "therundown"


def _specs():
    return apply_overrides(load_registry(Path("sources/registry.yaml")), load_overrides())[0]


def test_both_feeds_declare_the_same_group() -> None:
    by_id = {s.source_id: s for s in _specs()}
    assert by_id[BEEHIIV].dedup_group == GROUP
    assert by_id[SITE].dedup_group == GROUP


def test_one_publisher_after_recovery() -> None:
    """The point of the group: publisher recovery must agree for the two ids."""
    specs = _specs()
    groups = {s.source_id: s.dedup_group for s in specs if s.dedup_group}
    assert _publisher_of(BEEHIIV, groups) == _publisher_of(SITE, groups)


def test_the_group_holds_only_these_two() -> None:
    """A third source joining by accident would make unrelated新闻 count as one witness."""
    members = sorted(s.source_id for s in _specs() if s.dedup_group == GROUP)
    assert members == sorted([BEEHIIV, SITE])


def test_the_group_is_declared_in_the_override_layer() -> None:
    """`local.yaml` cannot carry it: the beehiiv id comes from the audited ledger."""
    ov = load_overrides()
    assert ov[BEEHIIV]["dedup_group"] == GROUP
    assert ov[SITE]["dedup_group"] == GROUP
    # A disabled source must say why; this one stays enabled, but the reason must exist anyway
    # so the grouping can be reviewed later.
    assert ov[BEEHIIV].get("reason")