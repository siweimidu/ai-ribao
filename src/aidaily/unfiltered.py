"""Which sources bypass the relevance gate, and which merely get a boost.

## Two different instructions, two different lists

「以后都记清楚了抓取这些的当日源不用筛选，直接打分排序，以后每天都是」

named hex2077, daily-juya, ainewslog and aibase. Those skip the relevance gate entirely: their
editorial judgement is trusted, and the instruction is that score decides position, not
admission.

「aihot.news的信息仍然要筛选一遍，只是来自aihot.news的信息天然要高些」

aihot is different. It is an aggregator -- it carries whatever its own contributors submitted,
including a World of Warcraft transmog talk and a climate-week recap. Its items are still
filtered, but they are AI-native material from an AI publication, so they carry a modest bonus
rather than an exemption.

## Why the split matters

Measured 2026-10-27, with every aihot feed exempt:

    #59  MIT 在 2026 纽约气候周对接全球气候网络     focus 0.50
    #61  Thariq 将在 AIE Code 分享 WoW 萨满配装     focus 0.33

Both published. `is_passthrough` short-circuited the gate for any event carrying an aihot
source, so a 0.33 score was as good as a 1.00.
"""

from __future__ import annotations

#: Sources whose items are never relevance-filtered. Named by the user, one by one.
UNFILTERED_SOURCES = frozenset({
    "rss:hex2077",
    "rss:hex2077-dev-rss-zh-cn",
    "rss:daily-juya-uk",
    "rss:ainewslog-com",
    "api:aibase-ai-news",
    "api:aibase-daily-news",
    # NOTE: `api:aibase-com` is deliberately NOT here.
    #
    # It is `https://aibase.com`, the site root, and the scraper harvests the navigation chrome
    # rather than stories. Measured 2026-10-25 once it was exempted: 28 of its 40 items were
    # catalogue links -- `#2 Gemini & Gemini Advanced gemini.google.com`, `AI Tools Directory`,
    # `Full Ranking` -- and two of them ranked into the top ten. The two API feeds above carry
    # the news.
})

#: aihot.news feeds. Still filtered; ranked higher because the publication is AI-native.
AIHOT_SOURCES = frozenset({
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

#: Multiplier applied to an aihot story's score.
#:
#: Small on purpose. A boost large enough to lift a marginal story over the relevance gate
#: would be an exemption by another name -- and the gate is exactly what removed the WoW talk.
#: 1.25 lifts an already-AI story a place or two without changing what gets in.
AIHOT_BOOST = 1.25


def is_unfiltered(source_id: str | None) -> bool:
    """True when this source's items are never relevance-filtered."""
    return (source_id or "") in UNFILTERED_SOURCES


def is_aihot(source_id: str | None) -> bool:
    """True when this source is an aihot.news feed."""
    return (source_id or "") in AIHOT_SOURCES