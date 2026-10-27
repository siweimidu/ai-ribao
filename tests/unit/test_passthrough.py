"""Allow-listed sources skip the relevance gate but still go through ranking.

These are curated AI digests -- a human already decided every entry is about AI, so applying our
own focus score double-filters work done upstream. The gate stays for everything else: removing
it globally is what let consumer-electronics items into the issue.
"""

from __future__ import annotations

from aidaily.pipeline import PASSTHROUGH_SOURCES, is_passthrough, passes_ai_relevance


class _Event:
    def __init__(self, source_ids: list[str]) -> None:
        self.source_ids = source_ids


def test_the_curated_digests_are_on_the_list() -> None:
    for sid in (
        "rss:hex2077",
        "rss:daily-juya-uk",
        "rss:daily-juya-uk",
        "rss:ainewslog-com",
        "rss:hex2077",
        "api:aibase-daily-news",
    ):
        assert sid in PASSTHROUGH_SOURCES, sid


def test_a_passthrough_event_is_recognised() -> None:
    assert is_passthrough(_Event(["rss:hex2077"]))


def test_one_allow_listed_source_is_enough() -> None:
    """An event carried by a curated digest and an ordinary feed still gets through."""
    assert is_passthrough(_Event(["rss:infoq-cn", "rss:daily-juya-uk"]))


def test_an_ordinary_source_is_not_a_passthrough() -> None:
    assert not is_passthrough(_Event(["rss:infoq-cn"]))
    assert not is_passthrough(_Event([]))


def test_the_gate_still_rejects_a_low_focus_score() -> None:
    """The pass-through must not have disabled the floor for everyone."""
    assert not passes_ai_relevance(0.2)
    assert passes_ai_relevance(0.9)


def test_the_gate_skips_allow_listed_sources_only() -> None:
    import inspect

    source = inspect.getsource(__import__("aidaily.pipeline", fromlist=["x"]).select_for_digest)
    assert "not is_passthrough(row.event)" in source