"""The page must say what each named source contributed, including zero.

Measured 2026-10-29: ainewslog delivered 662 items and produced 0 events; hex2077 38 and 0.
Nothing on the page distinguished that from a source that was never collected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.site import _NAMED_LABEL, _render_source_coverage

NOW = datetime.now(timezone.utc)


class _Row:
    def __init__(self, sources: list[str]) -> None:
        self.event = Event(
            event_id="e",
            title="t",
            member_item_ids=["m"],
            primary_item_id="m",
            source_ids=sources,
            all_urls=["https://example.com/x"],
            first_seen_at=NOW,
            last_updated_at=NOW,
        )


def _rows(*source_lists: list[str]) -> list:
    return [(i + 1, _Row(s).event) for i, s in enumerate(source_lists)]


def test_counts_are_rendered_per_named_source() -> None:
    html = _render_source_coverage(_rows(["rss:daily-juya-uk"], ["rss:daily-juya-uk"]))
    assert "橘鸦" in html
    assert "2 条" in html


def test_a_source_with_nothing_is_named() -> None:
    html = _render_source_coverage(_rows(["rss:daily-juya-uk"]))
    assert "本期未收录" in html
    assert "AINewsLog" in html


def test_no_named_source_means_no_section() -> None:
    assert _render_source_coverage(_rows(["rss:axios"])) == ""


def test_every_named_source_has_a_label() -> None:
    from aidaily.unfiltered import UNFILTERED_SOURCES

    for sid in UNFILTERED_SOURCES:
        assert sid in _NAMED_LABEL, sid

def test_weekly_absent_is_not_reported_as_missing() -> None:
    """「不收录周刊」 is a rule, not a failure -- the page must say so."""
    html = _render_source_coverage(_rows(["rss:daily-juya-uk"]))
    assert "按规则不收录周刊" in html
    assert "hex2077" in html
    # It must not be listed among the sources that failed to deliver.
    head, _, tail = html.partition("按规则不收录周刊")
    assert "hex2077" not in head
