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

「https://aihot.news/feed.xml / feed/full.xml / feed/daily.xml 这三个RSS算作一个，
  也加入不用筛选，直接打分的当日信息里面，这些消息只能去重并标注多源验证，
  不能删除，这些信息价值很高，不能删除任何一条，这条要写死」

That instruction splits aihot in two. Three of its feeds are named -- feed.xml, feed/full.xml
and feed/daily.xml -- and those join the unfiltered set: no relevance gate, and no stage may
delete them. The remaining aihot feeds are still filtered and still boosted.

Those three are the module's one deliberate overlap: they are unfiltered *and* AI-native, so
they earn the bonus as well as the protection. An earlier note here called such an overlap
incoherent -- the user has since made it a requirement, and the contract test records why.

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
    # --- aihot.news, the three feeds the user named -----------------------------------
    #
    # 「这三个RSS算作一个，也加入不用筛选，直接打分的当日信息里面，这些消息只能去重并标注
    #   多源验证，不能删除，不能删除任何一条，这条要写死」
    #
    # They are in AIHOT_SOURCES as well, so they still rank higher; see the module docstring.
    "rss:aihot-news-picks",   # https://aihot.news/feed.xml
    "rss:aihot-news-full",    # https://aihot.news/feed/full.xml
    "rss:aihot-news-daily",   # https://aihot.news/feed/daily.xml
    # NOTE: `api:aibase-com` is deliberately NOT here.
    #
    # It is `https://aibase.com`, the site root, and the scraper harvests the navigation chrome
    # rather than stories. Measured 2026-10-25 once it was exempted: 28 of its 40 items were
    # catalogue links -- `#2 Gemini & Gemini Advanced gemini.google.com`, `AI Tools Directory`,
    # `Full Ranking` -- and two of them ranked into the top ten. The two API feeds above carry
    # the news.
})

#: aihot.news feeds. Ranked higher because the publication is AI-native.
#:
#: Three of them are also in UNFILTERED_SOURCES by name. The other nine are still filtered.
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

def protects(source_ids) -> bool:
    '''True when an event carrying any of these sources may not be deleted.

    **The hard rule.** 「但凡是那几个不要筛选直接进打分的那几个源获得的当日信息，这些消息只能
    去重并标注多源验证，不能删除，这些信息价值很高，不能删除任何一条」

    Those sources are named by the user, one by one. Their items skip the relevance gate, and
    they must also skip every stage that removes an event:

      - cross-day semantic dedup   may merge, may not delete
      - the max_items cut          may not truncate them
      - the fact-check drop        may not remove them

    Deduplication is still allowed and expected -- two outlets covering one launch become one
    entry with both sources listed, which is what 「标注多源验证」 means. What is forbidden is
    the entry disappearing.

    Measured 2026-10-28: `Genie 4` arrived from juya among twenty sources, and a cross-day
    dedup pass deleted the whole event while nothing named Genie had been published in the
    previous seven days. The issue published without the biggest story of the day.
    '''
    return any(is_unfiltered(sid) for sid in (source_ids or ()))

#: The three aihot feeds the user named. 「这三个RSS算作一个」 -- one source, three URLs.
NAMED_AIHOT_FEEDS = frozenset({
    "rss:aihot-news-picks",   # https://aihot.news/feed.xml
    "rss:aihot-news-full",    # https://aihot.news/feed/full.xml
    "rss:aihot-news-daily",   # https://aihot.news/feed/daily.xml
})

#: The identity those three share when counting independent sources.
_AIHOT_GROUP = "aihot.news"


def source_group(source_id: str) -> str:
    '''The independence identity of a feed.

    **The three named aihot feeds are one source.** 「这三个RSS算作一个」. They publish the
    same items to three URLs, so a story carried by all three would otherwise be counted as
    three independent outlets -- and independence is what the page shows as 「多源验证」 and
    what the ranker rewards.

    Every feed that is not one of the three is its own group.'''
    sid = source_id or ''
    return _AIHOT_GROUP if sid in NAMED_AIHOT_FEEDS else sid


def distinct_source_groups(source_ids) -> int:
    '''How many *independent* sources carry an event, collapsing the aihot trio to one.'''
    return len({source_group(sid) for sid in (source_ids or ())})
