"""Sources that bypass relevance filtering and date windows entirely.

## The instruction

The user set this as a standing rule, not a one-off:

    「以后都记清楚了抓取这些的当日源不用筛选，直接打分排序，以后每天都是」

listed: hex2077, daily-juya, ainewslog, aibase, plus every aihot.news feed
(picks / full / all / daily / weekly / monthly / the five category feeds).

## What "不用筛选" covers, and why each filter had to be named

Three different filters were each silently dropping these sources:

1. **AI relevance** (`focus.py`). `hex2077` carries Chinese dev news, `daily-juya` a daily
   roundup, `aibase` press releases. A Chinese headline about a model release often scores
   under the 0.55 floor because the gate wants AI vocabulary, not an AI story.

2. **The publication-date window** (`backfill.py`, 6 days). These feeds serve a rolling
   archive rather than a today-only stream, so their newest item is routinely one or two
   weeks old. Measured 2026-10-25: 14 / 10 / 11 days -- every item discarded, and the issue
   carried 26 entries instead of the expected few hundred.

3. **The single-source floor** (`pipeline.py`). One outlet reporting a story is still a
   story; the corroboration requirement exists to rank, not to exclude.

Naming them in three separate places guarantees one gets missed on the next edit, which is
exactly what happened. One list, imported everywhere.

## What still applies

Scoring. `heat` discounts by age and by single-source status, so an old one-outlet story
ranks low on the page. The rule is "do not filter", not "do not rank" -- the user asked for
打分排序, and ranking is where these sources are meant to compete.
"""

from __future__ import annotations

#: Never relevance-filtered, never date-windowed, never dropped as a lone source.
UNFILTERED_SOURCES = frozenset({
    # --- named explicitly by the user ------------------------------------------------
    "rss:hex2077",
    "rss:hex2077-dev-rss-zh-cn",
    "rss:daily-juya-uk",
    "rss:ainewslog-com",
    "api:aibase-ai-news",
    "api:aibase-daily-news",
    # NOTE: `api:aibase-com` is deliberately NOT here.
    #
    # It is `https://aibase.com`, the site root, and the scraper harvests the navigation
    # chrome rather than stories. Measured 2026-10-25 once it was exempted: 28 of its 40 items
    # were catalogue links -- `#2 Gemini & Gemini Advanced gemini.google.com`,
    # `#3 Claude 2 claude.ai`, `AI Tools Directory`, `Full Ranking` -- and two of them ranked
    # into the top ten of the issue. The two API feeds below carry the actual news.
    # --- aihot.news, every feed it publishes ----------------------------------------
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
})


def is_unfiltered(source_id: str | None) -> bool:
    """True when this source's items must not be filtered out."""
    return (source_id or "") in UNFILTERED_SOURCES