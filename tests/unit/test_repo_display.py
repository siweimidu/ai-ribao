"""A repository story keeps its own title and says how old it is.

Measured 2026-10-23: the issue showed
`anthropics/knowledge-work-plugins：Claude Cowork 知识工作插件` -- the slug glued to a model
translation of the description with a full-width colon between them. It reads as a malformed
label rather than a headline, and repeats what the card below already shows.

The same entry said `时间未知`, which is honest but useless: the reader asks how old the news is,
and the answer is "the project is nine months old but it trended this morning".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.models import Event, NormalizedItem
from aidaily.site import _display_title, _is_repository_story, _when

NOW = datetime.now(timezone.utc)
REPO_URL = "https://github.com/anthropics/knowledge-work-plugins"


def _pair(created: str = "", urls: list[str] | None = None):
    urls = urls or [REPO_URL]
    item = NormalizedItem(
        item_id="i1",
        source_id="scrape:github-com-trending",
        title="anthropics/knowledge-work-plugins",
        title_norm="x",
        url=urls[0],
        fetched_at=NOW,
        first_seen_at=NOW,
        updated_at=NOW,
        content_sha256="0" * 64,
        simhash=0,
        published_at=None,
        summary="",
        language="en",
        metrics={"repo_created": created} if created else {},
    )
    event = Event(
        event_id="e1",
        title="anthropics/knowledge-work-plugins",
        member_item_ids=["i1"],
        primary_item_id="i1",
        source_ids=["scrape:github-com-trending"],
        all_urls=urls,
        first_seen_at=NOW,
        last_updated_at=NOW,
        published_range=None,
    )
    return event, {"i1": item}


class _Insight:
    title = "anthropics/knowledge-work-plugins：Claude Cowork 知识工作插件"


def test_a_repository_keeps_its_slug_as_the_title() -> None:
    event, items = _pair("2026-01-23")
    assert _display_title(event, _Insight(), items) == "anthropics/knowledge-work-plugins"


def test_a_repository_without_an_insight_also_keeps_its_slug() -> None:
    event, items = _pair("2026-01-23")
    assert _display_title(event, None, items) == "anthropics/knowledge-work-plugins"


def test_a_non_repository_story_still_gets_the_model_title() -> None:
    """The rewrite is what makes most headlines readable; it must keep working."""
    event, items = _pair("2026-01-23", ["https://www.infoq.cn/article/abc"])
    event.title = "InfoQ 文章"
    assert _display_title(event, _Insight(), items) == _Insight.title


def test_github_topic_pages_are_not_repositories() -> None:
    event, _ = _pair("", ["https://github.com/topics/llm"])
    assert not _is_repository_story(event)


def test_a_real_repository_url_is_recognised() -> None:
    event, _ = _pair()
    assert _is_repository_story(event)


def test_an_old_repository_says_how_old() -> None:
    event, items = _pair("2026-01-23")
    text, known = _when(event, items)
    assert known is True
    assert "Trending" in text and "创建" in text


def test_a_new_repository_says_days() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    event, items = _pair(recent)
    text, _ = _when(event, items)
    assert "天前" in text


def test_an_unknown_age_still_says_unknown() -> None:
    """A wrong age is worse than no age: the reader uses it to judge whether it is news."""
    event, items = _pair("")
    text, known = _when(event, items)
    assert text == "时间未知"
    assert known is False