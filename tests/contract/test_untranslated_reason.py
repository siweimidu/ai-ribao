"""The page must not claim a cause it did not check.

The untranslated block used to say, every time:

    「这些条目的来源是外文，且本期模型额度用完、未能逐条译成中文」

That was a constant string, not a judgement. On 2026-10-27 it was false: the run had spent
161,767 of 2,000,000 tokens across 23 working providers, and the real cause was that the
pipeline selected a second time after analysis, so 17 entries were published without ever being
sent to a model.

`_untranslated_reason` reads the digest instead: the budget when it was actually reached, the
warning the analyzer recorded when the model was unavailable, and otherwise a statement of what
is observable.
"""

from __future__ import annotations

from aidaily.site import _untranslated_reason


class _Digest:
    def __init__(self, warnings, llm):
        self.warnings = warnings
        self.llm_usage = llm


def test_it_claims_exhaustion_only_when_calls_are_at_the_cap() -> None:
    reason = _untranslated_reason(
        _Digest([], {"calls": 400, "max_calls": 400, "tokens": 10, "max_tokens": 2000000})
    )
    assert "调用数已达上限" in reason


def test_it_claims_exhaustion_only_when_tokens_are_at_the_cap() -> None:
    reason = _untranslated_reason(
        _Digest([], {"calls": 10, "max_calls": 400, "tokens": 2000000, "max_tokens": 2000000})
    )
    assert "token 用量已达上限" in reason


def test_a_run_under_budget_never_claims_quota() -> None:
    """The exact 2026-10-27 numbers, which produced the false statement."""
    reason = _untranslated_reason(
        _Digest([], {"calls": 101, "max_calls": 400, "tokens": 161767, "max_tokens": 2000000})
    )
    assert "额度" not in reason
    assert "上限" not in reason


def test_a_missing_key_is_named_as_such() -> None:
    reason = _untranslated_reason(
        _Digest(["未配置大模型，本期所有条目为来源原文摘录（规则降级）"], {})
    )
    assert "未配置" in reason


def test_a_failed_call_is_named_as_such() -> None:
    reason = _untranslated_reason(_Digest(["81/120 个事件降级为规则摘录"], {}))
    assert "调用失败" in reason


def test_with_no_evidence_it_states_only_what_is_observable() -> None:
    """No invented cause. The headline is in a language this issue did not translate."""
    reason = _untranslated_reason(_Digest([], {}))
    assert "外文" in reason
    assert "额度" not in reason
    assert "上限" not in reason


def test_the_sentence_is_computed_not_hardcoded() -> None:
    """The renderer must call the helper, not embed a claim."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
    # The block renders whatever the helper returns.
    assert "{_untranslated_reason(digest)}" in source
