"""Two independent scores, and a bar that depends on who published.

Both ideas are taken from AIHOT, and both answer something this project was getting wrong:

* **Two passes.** One model call is one sample of a noisy judgement. Asking twice and averaging
  makes the noise measurable (`disagreement`) and the estimate better. AIHOT selects on the sum
  of two passes; this averages them, because everything else here speaks one number per event.

* **Tier thresholds.** A weight is a multiplier, and a multiplier cannot separate two stories
  that are genuinely close -- which is why promotions kept outranking releases however the
  weights were tuned. A threshold can. First-party sources (tier T1) enter at 60, official-
  adjacent at 66, reported news at 74.
"""

from __future__ import annotations

from aidaily.rubric import RubricResult, to_percent
from aidaily.tiers import (
    CATEGORY_TIER,
    DEFAULT_THRESHOLDS,
    passes,
    threshold_for,
    tier_of,
)


# --- tiers ----------------------------------------------------------------------


def test_first_party_and_media_have_different_bars() -> None:
    """The whole point: the same score is enough for a lab, not for a repost."""
    assert threshold_for("lab-official") < threshold_for("media")
    assert threshold_for("lab-official") < threshold_for("dev") < threshold_for("media")


def test_a_score_between_the_bars_separates_the_two() -> None:
    """A concrete case, so the ordering is not just arithmetic."""
    # Between the lab bar (55) and the media bar (68).
    score = 62.0
    assert passes(score, "lab-official"), "a lab announcement at 62 should enter"
    assert not passes(score, "media"), "the same score from a repost should not"


def test_an_unknown_category_is_treated_as_reported_news() -> None:
    """Fail safe: an unrecognised source is not granted first-party trust."""
    assert tier_of("something-new") == "T2"
    assert tier_of(None) == "T2"
    assert threshold_for("something-new") == DEFAULT_THRESHOLDS["T2"]


def test_every_known_category_maps_to_a_real_tier() -> None:
    for category, tier in CATEGORY_TIER.items():
        assert tier in DEFAULT_THRESHOLDS, (category, tier)


def test_thresholds_are_ordered_t1_lt_t15_lt_t2() -> None:
    assert DEFAULT_THRESHOLDS["T1"] < DEFAULT_THRESHOLDS["T1_5"] < DEFAULT_THRESHOLDS["T2"]


# --- two passes ------------------------------------------------------------------


def test_disagreement_is_zero_when_nothing_was_double_scored() -> None:
    result = RubricResult()
    result.scores["e1"] = 7.0
    assert result.disagreement == 0.0


def test_disagreement_measures_the_gap_between_passes() -> None:
    result = RubricResult()
    result.pair["e1"] = (6.0, 8.0)
    result.pair["e2"] = (5.0, 5.0)
    assert result.disagreement == 1.0, "mean of |8-6|=2 and |5-5|=0"


def test_coverage_reports_how_often_the_second_pass_ran() -> None:
    """A silently single-scored run must be visible in the log."""
    result = RubricResult()
    result.scores = {"e1": 7.0, "e2": 5.0}
    result.pair = {"e1": (6.0, 8.0)}
    result.double_scored = 1
    result.calls = 4
    text = result.coverage
    assert "打了两次" in text
    assert "均差" in text


def test_to_percent_maps_the_two_vocabularies() -> None:
    """The rubric speaks 0-10, the thresholds speak 0-100; they meet in exactly one place."""
    assert to_percent(10) == 100.0
    assert to_percent(6) == 60.0
    assert to_percent(None) is None
    assert to_percent(99) == 100.0, "clamped rather than trusted"


def test_scoring_asks_twice_per_batch() -> None:
    """Source-level check: the second pass must actually be issued, not just declared."""
    import inspect

    from aidaily.rubric import score_events

    source = inspect.getsource(score_events)
    assert "first = await score_once(" in source
    assert "second = await score_once(" in source
    assert "(a + b) / 2.0" in source, "the two passes must be averaged"


# --- configuration ---------------------------------------------------------------


def test_thresholds_come_from_config_not_a_constant() -> None:
    """A reviewer must be able to change the bar without editing code."""
    import inspect

    from aidaily.config import load_config
    from aidaily.pipeline import select_for_digest

    cfg = load_config(env={})
    assert cfg.quality.tier_thresholds, "the table is empty"
    assert set(cfg.quality.tier_thresholds) == {"T1", "T1_5", "T2"}

    # And the pipeline must read that table rather than the module default.
    assert "cfg.quality.tier_thresholds" in inspect.getsource(select_for_digest)


def test_the_number_of_scoring_passes_is_configurable() -> None:
    import inspect

    from aidaily.config import load_config
    from aidaily.rubric import score_events

    cfg = load_config(env={})
    assert cfg.quality.score_passes >= 1
    assert "passes" in inspect.signature(score_events).parameters
