"""The dedup rules are a specification, kept in a file and tested like one.

Measured 2026-10-24: three headlines describing one launch were published as three entries.
Deterministic signals all missed it (similarity 0.18-0.31, `same_message` False, only one
title named a model), so the merge decision belongs to the model. That makes the instructions
the most consequential text in the project: a wrong rule merges two stories and manufactures
false corroboration; a missing rule repeats one story three times.
"""

from __future__ import annotations

from pathlib import Path

from aidaily.merge_llm import PROMPT_PATH, SYSTEM, _FALLBACK, load_prompt

ROOT = Path(__file__).resolve().parents[2]


def test_the_prompt_lives_in_a_reviewable_file() -> None:
    assert PROMPT_PATH == ROOT / "config" / "dedup_prompt.md"
    assert PROMPT_PATH.exists(), "the dedup rules must be editable as a document"


def test_the_loaded_prompt_is_the_file() -> None:
    on_disk = PROMPT_PATH.read_text(encoding="utf-8").strip()
    assert SYSTEM == on_disk


def test_it_names_what_must_be_merged() -> None:
    """The three-headline Kimi case is the reason this file exists."""
    for case in ("同一款模型", "融资", "事故", "报告"):
        assert case in SYSTEM, case


def test_it_names_what_must_not_be_merged() -> None:
    """False corroboration is the expensive error, so the negatives are explicit."""
    for case in ("不同产品", "评测", "汇总稿"):
        assert case in SYSTEM, case


def test_it_states_the_asymmetry_of_the_two_errors() -> None:
    """Why the rule is conservative: a wrong merge invents proof a story is true."""
    assert "拿不准" in SYSTEM
    assert "不合并" in SYSTEM


def test_it_shows_the_world_largest_rewording() -> None:
    """The exact shape that failed: a Chinese outlet replacing the product name."""
    assert "全球最大" in SYSTEM


def test_it_specifies_the_output_shape() -> None:
    assert "groups" in SYSTEM
    assert "ids" in SYSTEM


def test_an_empty_file_falls_back_instead_of_disabling_dedup(tmp_path) -> None:
    """A packaging mistake must not silently turn dedup off."""
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    assert load_prompt(empty) == "\n".join(_FALLBACK)


def test_a_missing_file_falls_back(tmp_path) -> None:
    assert load_prompt(tmp_path / "nope.md") == "\n".join(_FALLBACK)


def test_the_fallback_still_carries_the_essential_rules() -> None:
    text = "\n".join(_FALLBACK)
    assert "同一件事" in text
    assert "groups" in text