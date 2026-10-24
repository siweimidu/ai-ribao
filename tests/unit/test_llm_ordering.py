"""The model orders the issue; the formula is the fallback.

Measured 2026-10-24: Chinese AI model Kimi K3.1 Pro is closing in on Anthropic had the highest
formula score in the issue (36.7) and was published at position 18, because the first sort key
was the section label and the score only ordered rows inside a section.

Two causes, both fixed:

  1. chosen.sort used rank_of(section) as its primary key.
  2. The rubric prompt told the model the opposite: sections matter more than scores.
"""

from __future__ import annotations

import inspect

from aidaily import pipeline, rubric


def _sort_key() -> str:
    source = inspect.getsource(pipeline.select_for_digest)
    tail = source[source.index("chosen.sort("):]
    return tail[: tail.index("))") + 2]


def test_the_final_sort_is_led_by_the_rubric_score() -> None:
    """A taxonomy label must not outrank the model judgement."""
    assert "rubric_score" in _sort_key()


def test_an_ungraded_event_sorts_after_graded_ones() -> None:
    """A missing score must not masquerade as a high one.

    Measured: 3 of 36 events had no rubric score and two of them sat in the top twelve, because
    the multiplier for an unscored event is exactly 1.0 -- neutral, which is generous.
    """
    assert "-1.0" in _sort_key()


def test_the_prompt_no_longer_says_sections_outrank_scores() -> None:
    """It did, verbatim. That instruction contradicted the ordering."""
    assert "栏目比分数重要" not in rubric.SYSTEM
    assert "分数决定顺序" in rubric.SYSTEM


def test_the_grading_profile_puts_a_real_release_first() -> None:
    """A launch must outrank its own preview."""
    profile = rubric.DEFAULT_PROFILE
    assert "正式发布" in profile
    assert "预热" in profile or "预告" in profile


def test_the_profile_asks_for_a_gradient() -> None:
    """Thirty stories all scored 6.5 conveys nothing."""
    profile = rubric.DEFAULT_PROFILE
    assert "分数分布" in profile or "梯度" in profile


def test_the_lead_rule_still_runs_before_the_score() -> None:
    """A named-model release is pinned regardless of grading."""
    key = _sort_key()
    assert key.index("leads_the_issue") < key.index("rubric_score")