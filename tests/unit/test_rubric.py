"""The rubric stage: a model's judgement blended into the formula score.

The design constraints this file pins down, each of which is a way the stage could quietly
do harm:

* **It must never remove anything.** No router, a failed call, a malformed response, an id
  that came back missing -- each leaves the event scored by the formula alone. A model
  outage costs ordering quality, not content.
* **An invented id must be dropped, and counted.** The contract from `analyze.py` is that
  the model echoes ids it was given. A response containing an id that was never sent is
  discarded; a nonzero count is still surfaced, because a model making up rows is worth
  knowing about.
* **A bogus score must not be clamped.** Clamping a returned 99 to 10 would silently promote
  a row to the top. Out-of-range values are dropped instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.models import Event
from aidaily.rubric import (
    DEFAULT_PROFILE,
    band,
    load_profile,
    _parse_scores,
    rubric_multiplier,
)

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def make_event(event_id: str = "e1", title: str = "OpenAI releases GPT-6") -> Event:
    return Event(
        event_id=event_id, title=title, member_item_ids=[f"i-{event_id}"],
        primary_item_id=f"i-{event_id}", source_ids=["rss:s"],
        all_urls=[f"https://example.com/{event_id}"], independent_source_count=2,
        first_seen_at=NOW, last_updated_at=NOW, published_range=(NOW, NOW),
        evidence_level="multi_source",
    )


# =============================== response parsing ================================
def test_plain_json_object_is_parsed() -> None:
    got = _parse_scores('{"scores": [{"id": "e1", "score": 9}, {"id": "e2", "score": 3}]}')
    assert got == {"e1": 9.0, "e2": 3.0}


def test_json_wrapped_in_a_code_fence_is_parsed() -> None:
    """Models fence their JSON constantly; refusing it would waste the call."""
    got = _parse_scores('```json\n{"scores": [{"id": "e1", "score": 8}]}\n```')
    assert got == {"e1": 8.0}


def test_json_surrounded_by_prose_is_parsed() -> None:
    got = _parse_scores('Here are the scores:\n{"scores": [{"id": "e1", "score": 7}]}\nDone.')
    assert got == {"e1": 7.0}


def test_a_bare_list_is_not_accepted() -> None:
    """The envelope carries the ids; a bare list has none, so it cannot be applied."""
    assert _parse_scores('[{"id": "e1", "score": 7}]') == {}


def test_out_of_range_scores_are_dropped_not_clamped() -> None:
    """Clamping 99 to 10 would promote a row on a number the model should not have sent."""
    got = _parse_scores(
        '{"scores": [{"id": "e1", "score": 99}, {"id": "e2", "score": -3},'
        ' {"id": "e3", "score": 6}]}'
    )
    assert got == {"e3": 6.0}


def test_non_numeric_and_missing_fields_are_dropped() -> None:
    got = _parse_scores(
        '{"scores": [{"id": "e1", "score": "high"}, {"id": "e2"},'
        ' {"score": 5}, {"id": "e4", "score": 4}]}'
    )
    assert got == {"e4": 4.0}


def test_garbage_returns_nothing_rather_than_raising() -> None:
    for text in ("", "not json at all", "{", "null", '{"scores": "nope"}'):
        assert _parse_scores(text) == {}


def test_float_scores_survive() -> None:
    assert _parse_scores('{"scores": [{"id": "e1", "score": 7.5}]}') == {"e1": 7.5}


# =============================== the multiplier ==================================
def test_a_perfect_score_leaves_the_formula_score_unchanged() -> None:
    assert rubric_multiplier(10.0) == pytest.approx(1.0)


def test_a_zero_score_demotes_but_does_not_erase() -> None:
    """The floor is the whole 'demote, never delete' rule expressed as a number."""
    value = rubric_multiplier(0.0)
    assert 0.0 < value < 1.0
    assert value == pytest.approx(0.30)


def test_an_unscored_event_is_neutral() -> None:
    """`None` must be exactly 1.0, or a failed batch would penalise its own events."""
    assert rubric_multiplier(None) == 1.0


def test_the_multiplier_is_monotonic() -> None:
    values = [rubric_multiplier(s) for s in range(11)]
    assert values == sorted(values), "更高的分会给出更低的乘数"
    assert values[0] < values[5] < values[10]


def test_out_of_range_input_is_clamped_here() -> None:
    """Parsing already rejects these; the function is still total, for direct callers."""
    assert rubric_multiplier(99) == rubric_multiplier(10)
    assert rubric_multiplier(-5) == rubric_multiplier(0)


# =============================== bands ===========================================
@pytest.mark.parametrize(("score", "expected"), [
    (10, "突破性"), (9, "突破性"), (8, "高价值"), (7, "高价值"),
    (6, "有趣"), (5, "有趣"), (4, "低优先"), (3, "低优先"), (2, "噪音"), (0, "噪音"),
])
def test_bands_match_the_rubric_table(score: int, expected: str) -> None:
    assert band(score) == expected


# =============================== the profile file ================================
def test_a_missing_profile_falls_back_and_says_so(tmp_path) -> None:
    """Deleting a markdown file must not stop the pipeline, but it must be visible."""
    text, source = load_profile(tmp_path / "nope.md")
    assert text == DEFAULT_PROFILE
    assert "missing" in source


def test_an_empty_profile_falls_back(tmp_path) -> None:
    path = tmp_path / "profile.md"
    path.write_text("   \n\n", encoding="utf-8")
    text, source = load_profile(path)
    assert text == DEFAULT_PROFILE
    assert "empty" in source


def test_a_real_profile_is_used_verbatim(tmp_path) -> None:
    path = tmp_path / "profile.md"
    path.write_text("# 我的标准\n\n只关心开源模型。\n", encoding="utf-8")
    text, source = load_profile(path)
    assert "只关心开源模型" in text
    assert source == str(path)


def test_the_shipped_profile_exists_and_says_heat_is_not_importance() -> None:
    """The one line that matters most, asserted so a rewrite cannot quietly drop it."""
    from aidaily.rubric import PROFILE_PATH

    text, source = load_profile(PROFILE_PATH)
    assert source == str(PROFILE_PATH), "仓库里应当有 config/profile.md"
    assert "热度 ≠ 重要性" in text
