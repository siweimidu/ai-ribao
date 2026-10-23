"""An undated GitHub entry is not automatically news.

GitHub Trending is a star-delta window, so an old project can top it after one busy morning.
Measured 2026-10-23: `anthropics/knowledge-work-plugins` placed third with heat 0.152; GitHub
says it was created 2026-01-23 -- nine months earlier. It trended because a commit landed that
morning. The reader asked, reasonably, how old this news was.

`_freshness` returned a flat 0.5 for every undated entry, which treats "created two years ago"
and "created last week" as the same thing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.heat import _REPO_AGE_FACTORS, _freshness, _repository_novelty, HeatWeights
from aidaily.models import Event, NormalizedItem

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def _item(created: str = "") -> NormalizedItem:
    return NormalizedItem(
        item_id="i1",
        source_id="scrape:github-com-trending",
        title="anthropics/knowledge-work-plugins — plugins for knowledge workers",
        title_norm="x",
        url="https://github.com/anthropics/knowledge-work-plugins",
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


def _event() -> Event:
    return Event(
        event_id="e1",
        title="anthropics/knowledge-work-plugins",
        member_item_ids=["i1"],
        primary_item_id="i1",
        source_ids=["scrape:github-com-trending"],
        all_urls=["https://github.com/anthropics/knowledge-work-plugins"],
        first_seen_at=NOW,
        last_updated_at=NOW,
        published_range=None,
    )


def test_a_nine_month_old_repository_is_demoted() -> None:
    """The measured case: created 2026-01-23, published 2026-10-23."""
    items = {"i1": _item("2026-01-23")}
    novelty = _repository_novelty(_event(), items)
    assert novelty < 0.5
    assert _freshness(_event(), NOW, HeatWeights(), items) < 0.3


def test_a_week_old_repository_keeps_the_neutral_value() -> None:
    """A genuinely new project must not be punished for being on a windowed list."""
    items = {"i1": _item("2026-10-20")}
    assert _repository_novelty(_event(), items) == 1.0
    assert _freshness(_event(), NOW, HeatWeights(), items) == 0.5


def test_an_unknown_age_keeps_the_neutral_value() -> None:
    """Guessing would silently bury new projects whose metadata the API declined to return."""
    items = {"i1": _item("")}
    assert _repository_novelty(_event(), items) == 1.0


def test_a_malformed_date_keeps_the_neutral_value() -> None:
    items = {"i1": _item("not-a-date")}
    assert _repository_novelty(_event(), items) == 1.0


def test_the_factor_never_reaches_zero() -> None:
    """Zero would delete the entry from consideration rather than demote it."""
    assert all(factor > 0 for _, factor in _REPO_AGE_FACTORS)


def test_the_factors_decrease_with_age() -> None:
    factors = [f for _, f in _REPO_AGE_FACTORS]
    assert factors == sorted(factors, reverse=True)


def test_the_dated_path_is_untouched() -> None:
    """A story with a real publication date never consults the repository age."""
    items = {"i1": _item("2020-01-01")}
    event = _event()
    event.published_range = (NOW, NOW)
    assert _freshness(event, NOW, HeatWeights(), items) > 0.9