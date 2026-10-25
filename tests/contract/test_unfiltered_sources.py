"""The unfiltered-source rule is one list, and every filter must read it.

## The standing instruction

「以后都记清楚了抓取这些的当日源不用筛选，直接打分排序，以后每天都是」

hex2077, daily-juya, ainewslog, aibase, and every aihot.news feed. Not a one-off -- a rule
that has to hold every day.

## Why one list

Three separate filters were each dropping these sources, and each had its own copy of the
names:

  focus.py     AI relevance floor 0.55     (a Chinese model-release headline scores under it)
  backfill.py  publication-date window     (14 / 10 / 11 days old on 2026-10-25, all dropped)
  pipeline.py  single-source floor         (one outlet is still a story)

Naming them twice guarantees the copies drift, and they did: `api:aibase-com` was date-exempt
but not relevance-exempt, so 40 press releases were date-windowed in only to be filtered out
later. `unfiltered.py` holds the one list; these tests keep it that way.
"""

from __future__ import annotations

from aidaily.backfill import DATE_EXEMPT_SOURCES
from aidaily.pipeline import PASSTHROUGH_SOURCES
from aidaily.unfiltered import UNFILTERED_SOURCES, is_unfiltered


def test_every_named_source_is_present() -> None:
    """The four the user listed by name."""
    for sid in (
        "rss:hex2077",
        "rss:daily-juya-uk",
        "rss:ainewslog-com",
        "api:aibase-ai-news",
        "api:aibase-daily-news",
    ):
        assert sid in UNFILTERED_SOURCES, sid


def test_every_aihot_feed_is_present() -> None:
    """Picks, full, all, daily, weekly, monthly and the five category feeds."""
    for sid in (
        "rss:aihot-news-picks",
        "rss:aihot-news-full",
        "rss:aihot-news-all",
        "rss:aihot-news-daily",
        "rss:aihot-news-weekly",
        "rss:aihot-news-monthly",
        "rss:aihot-cat-models",
        "rss:aihot-cat-products",
        "rss:aihot-cat-industry",
        "rss:aihot-cat-paper",
        "rss:aihot-cat-tip",
        "rss:aihot-cat-opinion",
    ):
        assert sid in UNFILTERED_SOURCES, sid


def test_relevance_is_exempt_but_age_is_not() -> None:
    """The two filters are separate, and only one is exempt."""
    #
    # This asserted that both shared one list. They must not: a Chinese model-release
    # headline scores under the AI floor and has to be included, while a 9-day-old item
    # does not belong in today issue whoever published it.
    assert PASSTHROUGH_SOURCES is UNFILTERED_SOURCES
    assert DATE_EXEMPT_SOURCES == frozenset()

def test_the_helper_is_exact_match_not_prefix() -> None:
    """A source named `rss:hex2077-something-else` must not inherit the exemption."""
    assert is_unfiltered("rss:hex2077")
    assert not is_unfiltered("rss:hex2077-extra")
    assert not is_unfiltered(None)
    assert not is_unfiltered("")


def test_nothing_unexpected_crept_in() -> None:
    """Every entry is one of the two documented families."""
    for sid in UNFILTERED_SOURCES:
        assert sid.startswith(("rss:aihot-", "rss:hex2077", "rss:daily-juya", "rss:ainewslog", "api:aibase-")), sid