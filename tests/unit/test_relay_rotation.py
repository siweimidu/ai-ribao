"""Relay keys must be used round-robin, not in declaration order.

Measured 2026-10-25, 157 LLM calls:

    relay:api.agnes-ai.cn#0    57
    relay:api.agnes-ai.cn#1    25
    relay:api.agnes-ai.cn#2    15
    relay:api.agnes-ai.cn#3     4
    #4 .. #22              0 each

Every call started at the first relay key and only advanced when it died, so three keys
absorbed 97 calls and then all answered HTTP 429 at the same moment. Every groq key was already
429, gemini was 429, and the router raised `LLMUnavailable`.

Consequence: **81 of 120 events fell back to rule-based excerpts** -- and the page moved 31 of
them into a collapsed 待翻译 block, so a reader saw 87 entries where the archive held 118.

All of it while 19 relay keys sat unused and the budget was at 39% of its call cap.
"""

from __future__ import annotations

from collections import Counter

from aidaily.llm.client import ProviderSpec
from aidaily.llm.router import Router, RouterStats


def _relay(i: int) -> ProviderSpec:
    return ProviderSpec(
        id=f"relay:x#{i}", tier="relay", base_url="https://x", model="m", key_literal="k"
    )


def _router(specs: list[ProviderSpec]) -> Router:
    r = Router.__new__(Router)
    r.providers = specs
    r.stats = RouterStats()
    r._relay_calls = 0
    r.relay_max_calls = 1000
    r._rr = 0
    r.env = {}
    return r


def test_first_choice_rotates_across_every_relay_key() -> None:
    """The failure: 19 keys never used."""
    r = _router([_relay(i) for i in range(23)])
    picks = Counter()
    for _ in range(46):
        available = r.available()
        if available:
            picks[available[0].id] += 1
    assert len(picks) == 23, f"only {len(picks)} keys were ever tried first"
    assert max(picks.values()) - min(picks.values()) <= 1


def test_first_party_still_ranks_before_relay() -> None:
    """Rotation must not put a paid relay key ahead of free quota."""
    specs = [
        ProviderSpec(id="relay:a", tier="relay", base_url="https://x", model="m", key_literal="k"),
        ProviderSpec(id="first", tier="free", base_url="https://x", model="m", key_literal="k"),
        ProviderSpec(id="relay:b", tier="relay", base_url="https://x", model="m", key_literal="k"),
    ]
    r = _router(specs)
    for _ in range(6):
        available = r.available()
        assert available[0].id == "first", [s.id for s in available]


def test_dead_keys_are_skipped_within_the_rotation() -> None:
    r = _router([_relay(i) for i in range(4)])
    r.mark_dead("relay:x#1", "429")
    seen = {r.available()[0].id for _ in range(8)}
    assert "relay:x#1" not in seen
    assert len(seen) == 3


def test_a_single_provider_is_returned_unchanged() -> None:
    r = _router([_relay(0)])
    assert [s.id for s in r.available()] == ["relay:x#0"]