"""Optional stages yield to the clock.

Measured 2026-10-30: a publish took 31-37 minutes and one run was cancelled at its limit -- the
day published nothing. Pairwise dedup, images and the analysis retry are improvements; they must
not decide whether the issue ships.
"""

from __future__ import annotations

import time

from aidaily import __main__ as entry


def test_the_clock_starts_at_zero_and_advances(monkeypatch) -> None:
    ticks = iter([100.0, 100.0, 100.0 + 90.0])
    monkeypatch.setattr(entry.time, "monotonic", lambda: next(ticks, 100.0))
    entry._start_budget()
    assert entry._elapsed_minutes() == 0.0
    assert abs(entry._elapsed_minutes() - 1.5) < 0.01


def test_without_a_start_the_elapsed_is_zero() -> None:
    entry._BUDGET_START = None
    assert entry._elapsed_minutes() == 0.0


def test_the_budgets_are_ordered() -> None:
    """Dedup drops first, then images, then the issue must still go out."""
    assert entry.PAIR_REVIEW_BUDGET_MIN < entry.IMAGE_BUDGET_MIN
    assert entry.IMAGE_BUDGET_MIN < entry.PUBLISH_SOFT_BUDGET_MIN


def test_the_publish_budget_is_well_under_the_job_limit() -> None:
    """The job is cancelled at 55 minutes; the budget must leave room for collect + deploy."""
    assert entry.PUBLISH_SOFT_BUDGET_MIN <= 20