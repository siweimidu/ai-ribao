"""A GitHub Trending row must say what the repository is, not just its slug.

Measured 2026-10-23: the issue showed a row headed `anthropics/knowledge-work-plugins` and
nothing else. The description was already fetched and already went into `summary`; it just was
not in the one field a reader sees first.
"""

from __future__ import annotations

from aidaily.fetchers.github_trending import _headline


REAL = (
    "Open source repository of plugins primarily intended for knowledge workers to use in"
    " Claude Cowork"
)


def test_the_slug_is_followed_by_the_description() -> None:
    headline = _headline("anthropics/knowledge-work-plugins", REAL)
    assert headline.startswith("anthropics/knowledge-work-plugins — ")
    assert "plugins" in headline


def test_a_repository_without_a_description_keeps_its_slug() -> None:
    assert _headline("owner/repo", "") == "owner/repo"
    assert _headline("owner/repo", "   ") == "owner/repo"


def test_a_long_description_is_cut_at_a_word_boundary() -> None:
    """No partial word survives the cut."""
    long = " ".join(["alpha"] * 40)
    headline = _headline("a/b", long)
    assert headline.endswith("…")
    body = headline.split(" — ", 1)[1][:-1]
    words = body.split(" ")
    assert all(word == "alpha" for word in words)


def test_a_short_description_is_left_whole() -> None:
    assert _headline("a/b", "Short desc.") == "a/b — Short desc."


def test_whitespace_in_the_description_is_collapsed() -> None:
    assert _headline("a/b", "two lines") == "a/b — two lines"