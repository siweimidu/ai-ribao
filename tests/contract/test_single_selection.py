"""Every published event must have an insight, or its headline stays untranslated.

Measured 2026-10-27: insights 59 / events 73. Seventeen published entries had no insight, so
_display_title fell back to the source headline and the page showed English:

    Dutch government to cut 16 percent of workforce
    Anthropic opens its books for Wall Street
    Groundhog Day for AI agents: Prompt caching patterns

## The cause

Selection happened TWICE. _analyze_async ran select_for_digest, analysed that list, and
returned events; build_digest then ran select_for_digest again on the same events and published
its own answer. The two agreed until they did not, and each divergence publishes entries whose
analysis is attached to an event nobody sees.

Passing rubric_scores and rubric_sections through was the previous patch for this exact bug --
which is the tell that the design, not the arguments, was wrong. There is now one selection:
build_digest(preselected=...) uses the caller list and skips the second pass.
"""

from __future__ import annotations

import inspect

from aidaily import pipeline


def test_build_digest_accepts_a_preselected_list() -> None:
    signature = inspect.signature(pipeline.build_digest)
    assert "preselected" in signature.parameters


def test_the_preselected_path_skips_the_second_selection() -> None:
    """One selection, so insights and top_events cannot disagree."""
    source = inspect.getsource(pipeline.build_digest)
    assert "if preselected is not None:" in source
    assert "ordered = list(preselected)" in source


def test_the_caller_passes_its_selected_list() -> None:
    from aidaily import __main__ as entry

    source = inspect.getsource(entry)
    assert "preselected=selected" in source


def test_the_caller_returns_the_selected_list() -> None:
    """_analyze_async analysed selected; that is what it must hand back."""
    from aidaily import __main__ as entry

    source = inspect.getsource(entry)
    assert "selection_report, selected)" in source


def test_a_preselected_digest_still_reports_its_head_figures() -> None:
    """distinct_sources / max_share describe the published list, not the ranking pass."""
    source = inspect.getsource(pipeline.build_digest)
    assert "distinct_sources" in source
    assert "max_share" in source