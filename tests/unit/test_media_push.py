"""Media repository pushes must survive being called twice in one issue.

The git-era assertions moved to `test_media_push_union.py`, which checks the Contents API shape.
What remains here is the contract `store_images` keeps regardless of transport.
"""

from __future__ import annotations

import inspect

from aidaily import mediastore


def _lines() -> list[str]:
    return [ln.strip() for ln in inspect.getsource(mediastore.store_images).splitlines()]


def test_a_real_run_pushes_before_returning_urls() -> None:
    """A rejected push must not leave URLs pointing at files that never uploaded."""
    lines = _lines()
    dry = lines.index("if dry_run:")
    push = next(i for i, ln in enumerate(lines) if "_push(root, date)" in ln)
    returns = [i for i, ln in enumerate(lines) if ln == "return urls"]
    assert dry < push, "the push must follow the dry-run exit"
    assert push < max(returns), "urls must not be returned before the push succeeds"


def test_a_dry_run_returns_urls_without_pushing() -> None:
    lines = _lines()
    dry = lines.index("if dry_run:")
    assert lines[dry + 1] == "return urls"


def test_a_failed_push_returns_an_empty_mapping() -> None:
    lines = _lines()
    assert "if not _push(root, date):" in lines
    idx = lines.index("if not _push(root, date):")
    assert lines[idx + 1] == "return {}"