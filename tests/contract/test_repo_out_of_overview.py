"""The overview's first eight rows never contain an open-source repository.

The reader's rule: a repository is a place, not an event. It may sit anywhere below the head,
but the eight entries the overview shows are for what happened today.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.site import (
    OVERVIEW_HEAD,
    _body_order,
    _is_repository_story,
    _repositories_below_the_head,
)

NOW = datetime.now(timezone.utc)


def _event(event_id: str, title: str, urls: list[str]) -> Event:
    return Event(
        event_id=event_id,
        title=title,
        member_item_ids=[f"i{event_id}"],
        primary_item_id=f"i{event_id}",
        source_ids=["scrape:github-com-trending"],
        all_urls=urls,
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


REPO = _event("r", "openai/whisper — Robust Speech Recognition", ["https://github.com/openai/whisper"])
REPO_TREE = _event(
    "t", "openai/whisper — Robust Speech Recognition", ["https://github.com/openai/whisper/tree/main"]
)
REPO_ANCHOR = _event(
    "a", "openai/whisper — Robust Speech Recognition", ["https://github.com/openai/whisper#readme"]
)
REPO_TITLE_ONLY = _event(
    "y", "openai/whisper — Robust Speech Recognition", ["https://example.com/about-whisper"]
)
NEWS = [
    _event(f"n{i}", f"第 {i} 条真实新闻：OpenAI 发布新模型", [f"https://example.com/{i}"])
    for i in range(1, 13)
]


def test_every_url_shape_counts_as_a_repository() -> None:
    for event in (REPO, REPO_TREE, REPO_ANCHOR, REPO_TITLE_ONLY):
        assert _is_repository_story(event), event.all_urls


def test_a_plain_news_story_is_not_a_repository() -> None:
    assert not _is_repository_story(NEWS[0])


def test_a_repository_at_the_top_trades_places_with_one_below_the_head() -> None:
    shown = [(i + 1, e) for i, e in enumerate([REPO] + NEWS)]
    out = _repositories_below_the_head(shown)
    head = [e.event_id for _n, e in out[:OVERVIEW_HEAD]]
    assert "r" not in head
    assert len(out) == len(shown)
    assert {e.event_id for _n, e in out} == {e.event_id for _n, e in shown}


def test_numbers_stay_sequential_after_the_swap() -> None:
    shown = [(i + 1, e) for i, e in enumerate([REPO] + NEWS)]
    out = _repositories_below_the_head(shown)
    assert [n for n, _e in out] == list(range(1, len(shown) + 1))


def test_the_body_order_itself_honours_the_rule() -> None:
    ordered, _untranslated = _body_order([REPO] + NEWS, {}, None)
    assert "r" not in [e.event_id for _n, e in ordered[:OVERVIEW_HEAD]]


def test_nothing_moves_when_the_head_is_clean() -> None:
    shown = [(i + 1, e) for i, e in enumerate(NEWS)]
    assert [e.event_id for _n, e in _repositories_below_the_head(shown)] == [
        e.event_id for _n, e in shown
    ]
