"""A reasoning model needs room to think before it writes anything.

Measured on Groq 2026-10-23:

  max_tokens=8    -> content="" finish_reason="length"  billed 83 tokens
  max_tokens=512  -> content="ok" finish_reason="stop"  billed 109 tokens

The whole budget went to hidden reasoning and not one character of the answer was written.
Downstream that looks like a dead provider, so the client turns an empty completion into an
error and the router tries the next one -- which spends a request to learn what the spec could
have said up front.

`ProviderSpec.reasoning` plus `reasoning_floor` raise the budget before the call.
"""

from __future__ import annotations

from aidaily.llm.client import ProviderSpec
from aidaily.llm.router import is_reasoning_model


def test_known_reasoning_models_are_recognised() -> None:
    for model in (
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "deepseek-r1",
        "qwq-32b",
        "o1-mini",
        "some-model-thinking",
    ):
        assert is_reasoning_model(model), model


def test_ordinary_models_are_not_flagged() -> None:
    """Raising the budget for everything would waste tokens on every call."""
    for model in (
        "agnes-3.0-flash",
        "agnes-2.5-flash",
        "qwen/qwen3.8-27b",
        "gemini-flash-lite-latest",
        "meta-llama/llama-3.3-70b",
    ):
        assert not is_reasoning_model(model), model


def test_the_floor_raises_a_small_budget() -> None:
    spec = ProviderSpec(
        id="t", tier="relay", base_url="https://x", model="openai/gpt-oss-120b",
        reasoning=True,
    )
    assert max(8, spec.reasoning_floor) >= 512, "8 tokens produced an empty answer"


def test_the_floor_never_lowers_a_large_budget() -> None:
    """The rubric already asks for 4000; the floor must not cut that to 1024."""
    spec = ProviderSpec(
        id="t", tier="relay", base_url="https://x", model="openai/gpt-oss-120b",
        reasoning=True,
    )
    assert max(4000, spec.reasoning_floor) == 4000


def test_a_non_reasoning_model_keeps_its_budget() -> None:
    spec = ProviderSpec(id="t", tier="relay", base_url="https://x", model="agnes-3.0-flash")
    assert spec.reasoning is False