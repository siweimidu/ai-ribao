"""A rewrite that splits a technical term is worse than the English original.

Measured 2026-10-24: `Kimi 3.1 Pro 104BA-2.8T: Fable-5.1-Class Open Weights narrows
Closed-Weighted gap` was published as

    Kimi 3.1 Pro 104BA-2.8T: Fable-5.1-公开组重量差距缩小，AI领先优势缩至1个月

`Open Weights` became 公开组重量 -- `open` read as 公开, `weights` as 重量 -- so the sentence
claims something about physical mass. A reader cannot tell it is a translation error.

The prompt now forbids it. This is the check that enforces the prompt: when the rewrite splits
a term, the original English title is published instead. Losing the translation is a smaller
cost than publishing a confident sentence that says something false.
"""

from __future__ import annotations

from aidaily.analyze import _safe_title, title_is_safe

ORIGINAL = (
    "[AINews] Kimi 3.1 Pro 104BA-2.8T: Fable-5.1-Class Open Weights narrows Closed-Weighted gap"
)


def test_the_reported_split_is_rejected() -> None:
    """The exact sentence from the issue."""
    ok, reason = title_is_safe(ORIGINAL, "Fable-5.1-公开组重量差距缩小，AI领先优势缩至1个月")
    assert not ok
    assert "公开组重量" in reason


def test_a_correct_translation_passes() -> None:
    assert title_is_safe(ORIGINAL, "Kimi K3.1 Pro 发布，开放权重缩小与 Fable-5.1 的差距")[0]


def test_keeping_the_term_verbatim_passes() -> None:
    """Leaving Open Weights in English is the safest option and must not be punished."""
    assert title_is_safe(ORIGINAL, "Kimi 3.1 Pro：Open Weights 追近 Closed-Weighted 水平")[0]


def test_other_split_terms_are_caught_too() -> None:
    """The table is not one string; the same failure has many spellings."""
    for bad in ("上下文窗户", "长凳标记", "封闭重量", "零射击"):
        ok, _ = title_is_safe(ORIGINAL, f"测试{bad}标题")
        assert not ok, bad


def test_an_empty_rewrite_is_rejected() -> None:
    assert not title_is_safe(ORIGINAL, "")[0]


def test_an_overlong_rewrite_is_rejected() -> None:
    """A headline past 120 characters is not a headline."""
    assert not title_is_safe(ORIGINAL, "测试" * 70)[0]


def test_a_rejected_rewrite_falls_back_to_the_original() -> None:
    """The point of the check: publish the English rather than a wrong Chinese sentence."""
    out = _safe_title(ORIGINAL, "Fable-5.1-公开组重量差距缩小")
    assert out == ORIGINAL[:200]


def test_an_accepted_rewrite_is_used() -> None:
    good = "Kimi K3.1 Pro 发布，开放权重缩小差距"
    assert _safe_title(ORIGINAL, good) == good


def test_the_prompt_forbids_the_split() -> None:
    """The check is a backstop; the instruction is the first line of defence."""
    from aidaily import analyze

    prompt = analyze.SYSTEM_PROMPT
    assert "Open Weights" in prompt
    assert "不能拆成" in prompt or "不译" in prompt