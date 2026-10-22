"""Media repository pushes must survive being called twice in one issue.

`store_images` runs twice per issue: article pictures, then repository cards. Each call pushes.
The first version only fetched when `.git` was absent, so the second call kept a HEAD that no
longer matched the remote and its push was rejected as non-fast-forward.

Measured on 2026-10-21: 52 image URLs written to the archive, 49 files in the media repository,
13 missing.
"""

from __future__ import annotations

import inspect

from aidaily import mediastore


def test_push_refetches_before_every_push() -> None:
    """The second call must re-fetch, or its push is rejected as non-fast-forward."""
    source = inspect.getsource(mediastore._push)
    assert "FETCH_HEAD" in source
    fetch_line = next(line for line in source.splitlines() if "--depth" in line and "git(" in line)
    indent = len(fetch_line) - len(fetch_line.lstrip())
    assert indent <= 8, "fetch must run on every push, not only the first"


def test_push_retries_once_after_a_rejected_push() -> None:
    """A concurrent run may push between our fetch and our push."""
    source = inspect.getsource(mediastore._push)
    assert "for attempt in range(2)" in source
    # The retry re-fetches and re-checkouts rather than rebasing: the working tree must still
    # hold the local files after a rejected push.
    assert "fetch" in source


def test_a_failed_push_does_not_report_success() -> None:
    """`store_images` returns {} when the push fails, so no URL outlives its file."""
    source = inspect.getsource(mediastore.store_images)
    assert "if not _push(root, date):" in source


def test_the_real_run_pushes_before_returning_urls() -> None:
    """Order matters: a rejected push must not leave URLs pointing at files never uploaded."""
    lines = [ln.strip() for ln in inspect.getsource(mediastore.store_images).splitlines()]
    dry = lines.index("if dry_run:")
    push = next(i for i, ln in enumerate(lines) if "_push(root, date)" in ln)
    returns = [i for i, ln in enumerate(lines) if ln == "return urls"]
    assert dry < push, "the push must follow the dry-run exit"
    assert push < max(returns), "urls must not be returned before the push succeeds"


def test_a_dry_run_returns_urls_without_pushing() -> None:
    """`dry_run` is for tests and for inspecting what would be stored."""
    lines = [ln.strip() for ln in inspect.getsource(mediastore.store_images).splitlines()]
    dry = lines.index("if dry_run:")
    push = next(i for i, ln in enumerate(lines) if "_push(root, date)" in ln)
    assert dry < push
    assert lines[dry + 1] == "return urls"