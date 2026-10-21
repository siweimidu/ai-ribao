"""A title must lead to the story, not to whoever republished it.

Reported from the live site on 2026-10-21: the entry

    开源工具 Strata 0.2 重磅发布：硬件门槛再降 16GB，本地流畅跑千亿大模型

showed `github.com` and `aibase.com` underneath, and clicking the title opened
`aihot.news/items/h3p20nlx...` -- the aggregator's own page for the story it had copied.

Two causes: `all_urls` was built with a plain `sorted({...})`, so `aihot.news` beat
`github.com` and `aibase.com` on alphabetical order alone; and the renderer took
`all_urls[0]` without asking which URL was primary.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.l3 import _url_directness
from aidaily.models import Event
from aidaily.site import render_item

NOW = datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)


def _event(urls: list[str]) -> Event:
    return Event(
        event_id="e1",
        primary_item_id="i1",
        title="开源工具 Strata 0.2 重磅发布",
        member_item_ids=["i1"],
        source_ids=["rss:aihot-news", "rss:aibase-ai-news"],
        all_urls=urls,
        independent_source_count=2,
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_an_aggregator_url_is_never_primary() -> None:
    """The exact ordering from the archive, which put the aggregator first."""
    event = _event([
        "https://aihot.news/items/h3p20nlx7t5fr27k4viwlnpty",
        "https://www.aibase.com/zh/news/31754",
        "https://github.com/example/strata/releases/v0.2",
    ])
    html = render_item(1, event, None, None)
    first = html.split('target="_blank"')[0]
    assert "aibase.com" in first or "github.com" in first, first[-120:]
    assert "aihot.news/items" not in first, "the title still opens the aggregator"


def test_the_order_puts_originals_before_mirrors() -> None:
    urls = [
        "https://aihot.news/items/a",
        "https://github.com/x/y",
        "https://www.aibase.com/zh/news/1",
    ]
    ordered = sorted(urls, key=lambda u: (_url_directness(u), u))
    assert ordered[-1] == "https://aihot.news/items/a"


def test_this_projects_own_commit_is_never_a_source_link() -> None:
    """The digest cited itself: a chore(daily) commit appeared among Strata's sources."""
    assert _url_directness("https://github.com/siweimidu/ai-ribao/commit/827b089") == 2
    assert _url_directness("https://github.com/someone/other/commit/1") == 0


def test_a_plain_string_sort_would_have_failed_this() -> None:
    """Documents the bug: alphabetical order is what shipped the wrong link."""
    urls = ["https://aihot.news/items/a", "https://github.com/x/y"]
    assert sorted(urls)[0] == "https://aihot.news/items/a", "this is why it broke"
    assert sorted(urls, key=lambda u: (_url_directness(u), u))[0] == "https://github.com/x/y"
