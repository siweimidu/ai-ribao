"""Routing: prefer Agnes and Groq, and rotate keys inside each family.

## The instruction

「这个大模型API密钥，一定要有路由，自动轮换可用的密钥，优先使用Agnes和Groq」

## What went wrong without it

Measured 2026-10-25, 157 calls over 28 relay keys:

    relay:agnes#0   57
    relay:agnes#1   25
    relay:agnes#2   15
    relay:agnes#3    4
    relay:agnes#4..22   0 each

Three keys absorbed 97 calls, then all answered HTTP 429 at once; every groq key was already
429 and gemini was 429, so the router raised `LLMUnavailable` and **81 of 120 events fell back
to rule-based excerpts** -- with 19 unused keys and the budget at 39%.

## What the tests pin down

* Agnes runs before Groq, Groq before other relays, first-party keys last.
* Keys of the same family rotate, so no single key absorbs the run.
* A key marked dead drops out of the rotation without disturbing it.
"""

from __future__ import annotations

from collections import Counter

from aidaily.llm.client import ProviderSpec
from aidaily.llm.router import Router, RouterStats, priority_of


def _spec(pid: str, base: str, tier: str) -> ProviderSpec:
    return ProviderSpec(id=pid, tier=tier, base_url=base, model="m", key_literal="k")


def _router(specs: list[ProviderSpec]) -> Router:
    r = Router.__new__(Router)
    r.providers = specs
    r.stats = RouterStats()
    r._relay_calls = 0
    r.relay_max_calls = 10_000
    r._rr = 0
    r.env = {}
    return r


def _pool() -> list[ProviderSpec]:
    return [
        _spec("gemini", "https://generativelanguage.googleapis.com", "official-free"),
        _spec("groq", "https://api.groq.com/openai/v1", "official-free"),
        *[_spec(f"relay:api.agnes-ai.cn#{i}", "https://api.agnes-ai.cn/v1", "relay") for i in range(4)],
        *[_spec(f"relay:api.groq.com#{i}", "https://api.groq.com/openai/v1", "relay") for i in range(3)],
        _spec("relay:other#0", "https://other.example/v1", "relay"),
    ]


def test_agnes_ranks_before_groq() -> None:
    assert priority_of(_spec("relay:api.agnes-ai.cn#0", "https://api.agnes-ai.cn/v1", "relay")) < \
        priority_of(_spec("groq", "https://api.groq.com/openai/v1", "official-free"))


def test_groq_ranks_before_other_relays() -> None:
    assert priority_of(_spec("relay:api.groq.com#0", "https://api.groq.com/openai/v1", "relay")) < \
        priority_of(_spec("relay:other#0", "https://other.example/v1", "relay"))


def test_other_relays_rank_before_remaining_first_party() -> None:
    assert priority_of(_spec("relay:other#0", "https://other.example/v1", "relay")) < \
        priority_of(_spec("gemini", "https://generativelanguage.googleapis.com", "official-free"))


def test_the_first_choice_rotates_across_every_agnes_key() -> None:
    """The failure: #0 took 57 calls, #4-#22 took none."""
    r = _router(_pool())
    picks = Counter()
    for _ in range(16):
        picks[r.available()[0].id] += 1
    agnes = {k: v for k, v in picks.items() if "agnes" in k}
    assert len(agnes) == 4, f"only {len(agnes)} Agnes keys were tried first"
    assert max(agnes.values()) - min(agnes.values()) <= 1


def test_a_dead_key_leaves_the_rotation_intact() -> None:
    r = _router(_pool())
    r.mark_dead("relay:api.agnes-ai.cn#1", "429")
    seen = {r.available()[0].id for _ in range(12)}
    assert "relay:api.agnes-ai.cn#1" not in seen
    assert len(seen) == 3


def test_the_full_order_puts_agnes_entirely_first() -> None:
    r = _router(_pool())
    order = [s.id for s in r.available()]
    agnes_positions = [i for i, s in enumerate(order) if "agnes" in s]
    other_positions = [i for i, s in enumerate(order) if "agnes" not in s]
    assert max(agnes_positions) < min(other_positions)


def test_a_single_provider_is_returned_unchanged() -> None:
    r = _router([_spec("groq", "https://api.groq.com/openai/v1", "official-free")])
    assert [s.id for s in r.available()] == ["groq"]