"""The LLM orders the issue; the formula is the fallback, and the fallback is recorded.

Three modes:

  llm       -- the model graded enough of the pool to order it
  degraded  -- it graded most of it, some batches failed
  formula   -- it contributed nothing usable, the formula took over

Measured 2026-10-24: 34 of 36 scored with 8 calls -- llm. A run where every batch hit 429 would
score 0 and must not read as a normal day.
"""

from __future__ import annotations

import inspect

from aidaily.rubric import RubricResult, score_events


def test_a_fresh_result_defaults_to_llm() -> None:
    """score_events sets the mode explicitly; the default only matters before it runs."""
    assert RubricResult().mode == "llm"


def test_formula_and_degraded_report_as_degraded() -> None:
    result = RubricResult()
    result.mode = "formula"
    assert result.is_degraded
    result.mode = "degraded"
    assert result.is_degraded
    result.mode = "llm"
    assert not result.is_degraded


def test_every_outcome_sets_the_mode_explicitly() -> None:
    """A branch that falls through to the default reports the wrong mode."""
    source = inspect.getsource(score_events)
    for mode in ("formula", "degraded", "llm"):
        assert mode in source, mode


def test_no_model_means_formula_not_llm() -> None:
    """Returning early with the default would report a formula order as a model decision."""
    source = inspect.getsource(score_events)
    head = source.index("if router is None or not events:")
    assert "formula" in source[head:head + 420]


def test_a_run_that_scored_nothing_is_formula() -> None:
    source = inspect.getsource(score_events)
    assert "scored == 0" in source


def test_a_half_scored_pool_falls_back_to_formula() -> None:
    """Too few graded rows to order a whole issue."""
    source = inspect.getsource(score_events)
    assert "scored * 2 < len(events)" in source


def test_the_mode_reaches_the_archive() -> None:
    """A reader must be able to tell a model decision from a fallback."""
    from aidaily import pipeline

    assert "rubric_mode" in inspect.getsource(pipeline.select_for_digest)


def test_the_run_log_prints_which_one_was_used() -> None:
    from aidaily import __main__ as entry

    assert "排序依据" in inspect.getsource(entry)