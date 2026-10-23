"""Every story is asked for a picture; none are skipped for being far down the page.

The cap was 40, applied to `digest.top_events[:40]` in published order. On a hundred-story issue
that stopped looking after position forty, so any source with a usable `og:image` below that line
was never tried -- which reads as "this site has no pictures" rather than "we did not ask".

Runtime is bounded by `IMAGE_STAGE_SECONDS`, not by the count: a slow publisher costs the
pictures that did not arrive in time, never the issue.
"""

from __future__ import annotations

import inspect

from aidaily import __main__ as entry
from aidaily.config import OutputConfig


def test_the_configured_cap_does_not_limit_a_normal_issue() -> None:
    """A busy day is a few hundred events; the cap must sit above that."""
    assert OutputConfig().images_max >= 1000


def test_the_fetch_default_does_not_limit_a_normal_issue() -> None:
    signature = inspect.signature(entry._fetch_images)
    assert signature.parameters["limit"].default >= 1000


def test_the_stage_has_a_time_budget() -> None:
    """Something must bound a day when several publishers hang at once."""
    assert 60 <= entry.IMAGE_STAGE_SECONDS <= 1800


def test_the_pool_is_wide_enough_for_the_whole_issue() -> None:
    """At concurrency 24 a hundred events is four batches; wider keeps the stage short."""
    signature = inspect.signature(entry._fetch_images)
    assert signature.parameters["concurrency"].default >= 16


def test_the_budget_is_reported_when_it_bites() -> None:
    """A silent timeout is indistinguishable from "no pictures exist"."""
    source = inspect.getsource(entry._fetch_images)
    assert "超时未完成" in source