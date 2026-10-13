"""LLM router tests: fallback, blacklisting, parameter degradation, budget breaking.

All offline: `httpx.MockTransport` stands in for the network, so the routing logic is
verified without spending a single token.
"""

from __future__ import annotations

import asyncio
import functools
import json
from typing import Any

import httpx
import pytest

from aidaily.llm import (
    Budget,
    BudgetExceeded,
    LLMUnavailable,
    ProviderSpec,
    Router,
    extract_json,
    providers_from_env,
)


def async_test(fn):
    """Run a coroutine test without pytest-asyncio.

    One less dev dependency, and the failure mode is obvious: the test is simply a sync
    function that drives the event loop.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


ENV = {"GEMINI_API_KEY": "k-gemini", "GROQ_API_KEY": "k-groq", "CEREBRAS_API_KEY": "k-cerebras"}


def make_provider(pid: str, tier: str = "official-free", weight: int = 0, **kw: Any) -> ProviderSpec:
    """A provider with a literal key, so tests do not depend on which env vars exist."""
    kw.setdefault("key_literal", "test-key")
    return ProviderSpec(
        id=pid, tier=tier, base_url=f"https://{pid}.example/v1", model=f"{pid}-model",
        weight=weight, **kw,
    )


def ok_body(text: str = "hello", prompt: int = 10, completion: int = 5) -> dict:
    return {
        "model": "m", "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class FakeNet:
    """A scripted transport: per-provider queue of (status, body) responses."""

    def __init__(self, script: dict[str, list[tuple[int, Any]]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        pid = host.split(".")[0]
        payload = json.loads(request.content) if request.content else {}
        self.requests.append((pid, payload))
        queue = self.script.get(pid)
        if not queue:
            return httpx.Response(500, json={"error": "no scripted response"})
        status, body = queue.pop(0)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)


def make_router(script: dict[str, list[tuple[int, Any]]], providers: list[ProviderSpec], **kw: Any):
    fake = FakeNet(script)
    transport = httpx.MockTransport(fake.handler)
    client = httpx.AsyncClient(transport=transport)
    router = Router(providers, client, env=ENV, **kw)
    return router, fake, client


# --- basic routing ---------------------------------------------------------------
@async_test
async def test_first_provider_is_used_and_usage_is_recorded() -> None:
    router, _, client = make_router({"gemini": [(200, ok_body())]}, [make_provider("gemini")])
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert resp.text == "hello"
    assert resp.provider_id == "gemini"
    assert router.budget.calls == 1
    assert router.budget.prompt_tokens == 10
    assert router.budget.completion_tokens == 5


@async_test
async def test_provider_order_follows_tier_then_weight() -> None:
    """A relay must never be tried before an official free tier."""
    providers = [
        make_provider("relay1", tier="relay", weight=0),
        make_provider("gemini", tier="official-free", weight=5),
    ]
    router, fake, client = make_router({"gemini": [(200, ok_body())]}, providers)
    try:
        await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert fake.requests[0][0] == "gemini"


# --- fallback and blacklisting ---------------------------------------------------
@async_test
async def test_daily_quota_blacklists_the_provider_and_falls_through() -> None:
    """daybrief's `mark_down` behaviour: a per-day quota must not be retried in-run."""
    script = {
        "gemini": [(429, {"error": "You exceeded your current quota, per day limit"})],
        "groq": [(200, ok_body("from groq")), (200, ok_body("from groq again"))],
    }
    router, fake, client = make_router(
        script, [make_provider("gemini", weight=0), make_provider("groq", weight=1)]
    )
    try:
        first = await router.complete([{"role": "user", "content": "hi"}])
        second = await router.complete([{"role": "user", "content": "again"}])
    finally:
        await client.aclose()

    assert first.text == "from groq"
    assert "gemini" in router.stats.dead
    assert "rate_limited" in router.stats.dead["gemini"]
    # The second call must not even try gemini again.
    assert [pid for pid, _ in fake.requests].count("gemini") == 1
    assert router.stats.used == {"groq": 2}


@async_test
async def test_auth_error_blacklists_permanently() -> None:
    script = {"gemini": [(401, {"error": "bad key"})], "groq": [(200, ok_body("ok"))]}
    router, _, client = make_router(
        script, [make_provider("gemini", weight=0), make_provider("groq", weight=1)]
    )
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert resp.provider_id == "groq"
    assert "auth" in router.stats.dead["gemini"]


@async_test
async def test_all_providers_failing_raises_unavailable() -> None:
    script = {"gemini": [(500, {})], "groq": [(500, {})]}
    router, _, client = make_router(
        script, [make_provider("gemini", weight=0), make_provider("groq", weight=1)]
    )
    try:
        with pytest.raises(LLMUnavailable):
            await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()


@async_test
async def test_provider_without_a_key_is_skipped_not_called() -> None:
    providers = [
        ProviderSpec(id="nvidia", tier="official-free", base_url="https://nvidia.example/v1",
                     model="m", key_env="NVIDIA_KEY_THAT_DOES_NOT_EXIST", weight=0),
        make_provider("gemini", weight=1),
    ]
    router, fake, client = make_router({"gemini": [(200, ok_body())]}, providers)
    try:
        await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert "nvidia" not in [pid for pid, _ in fake.requests]


# --- parameter degradation -------------------------------------------------------
@async_test
async def test_json_mode_is_dropped_and_retried_when_rejected() -> None:
    """A provider that cannot do JSON mode can still answer in prose."""
    script = {
        "gemini": [
            (400, {"error": "response_format json_object is not supported"}),
            (200, ok_body('{"ok": true}')),
        ]
    }
    router, fake, client = make_router(script, [make_provider("gemini")])
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}], json_mode=True)
    finally:
        await client.aclose()

    assert resp.text == '{"ok": true}'
    assert fake.requests[0][1].get("response_format") == {"type": "json_object"}
    assert "response_format" not in fake.requests[1][1]
    assert router.stats.used == {"gemini": 1}, "the retry is one logical call"


@async_test
async def test_json_mode_is_not_sent_to_a_provider_without_the_capability() -> None:
    spec = make_provider("plain", capabilities={"system_role"})
    router, fake, client = make_router({"plain": [(200, ok_body('{"ok":1}'))]}, [spec])
    try:
        await router.complete([{"role": "user", "content": "hi"}], json_mode=True)
    finally:
        await client.aclose()

    assert "response_format" not in fake.requests[0][1]


@async_test
async def test_system_role_is_folded_into_user_when_unsupported() -> None:
    spec = make_provider("nosys", capabilities={"json_object"})
    router, fake, client = make_router({"nosys": [(200, ok_body())]}, [spec])
    try:
        await router.complete([
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": "hi"},
        ])
    finally:
        await client.aclose()

    sent = fake.requests[0][1]["messages"]
    assert len(sent) == 1 and sent[0]["role"] == "user"
    assert "be terse" in sent[0]["content"], "the instruction must survive, not be dropped"


# --- budget ----------------------------------------------------------------------
@async_test
async def test_budget_exhaustion_raises_instead_of_calling_out() -> None:
    router, fake, client = make_router(
        {"gemini": [(200, ok_body()), (200, ok_body())]},
        [make_provider("gemini")],
        budget=Budget(max_calls=1, max_tokens=10_000),
    )
    try:
        await router.complete([{"role": "user", "content": "1"}])
        with pytest.raises(BudgetExceeded):
            await router.complete([{"role": "user", "content": "2"}])
    finally:
        await client.aclose()

    assert len(fake.requests) == 1, "the second call must not reach the network"


@async_test
async def test_token_budget_is_enforced_too() -> None:
    script = {"gemini": [(200, ok_body(prompt=9000, completion=9000))]}
    router, _, client = make_router(
        script, [make_provider("gemini")], budget=Budget(max_calls=100, max_tokens=10_000)
    )
    try:
        await router.complete([{"role": "user", "content": "1"}])
        assert router.budget.tokens == 18_000
        with pytest.raises(BudgetExceeded):
            await router.complete([{"role": "user", "content": "2"}])
    finally:
        await client.aclose()


# --- relay cap -------------------------------------------------------------------
@async_test
async def test_relay_tier_is_capped_per_run() -> None:
    """Untrusted relays get a hard call cap even if they keep working."""
    providers = [make_provider("relay1", tier="relay", weight=0)]
    script = {"relay1": [(200, ok_body()) for _ in range(5)]}
    router, fake, client = make_router(script, providers, relay_max_calls=2)
    try:
        await router.complete([{"role": "user", "content": "1"}])
        await router.complete([{"role": "user", "content": "2"}])
        with pytest.raises(LLMUnavailable):
            await router.complete([{"role": "user", "content": "3"}])
    finally:
        await client.aclose()

    assert len(fake.requests) == 2


# --- JSON extraction -------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here you go: {"a": 1} Hope that helps.', {"a": 1}),
        ('[1, 2, 3]', [1, 2, 3]),
        ('Result:\n[{"x": 1}]\nDone.', [{"x": 1}]),
    ],
)
def test_extract_json_tolerates_model_chatter(raw: str, expected: Any) -> None:
    """Both audited implementations needed this: models wrap JSON in fences constantly."""
    assert extract_json(raw) == expected


@async_test
async def test_provider_json_validation_failure_degrades_instead_of_abandoning() -> None:
    """Regression found by the live smoke test against Groq.

    Groq answers a `response_format: json_object` request whose generation failed
    validation with `400 Failed to validate JSON. Please adjust your prompt.` -- a
    message containing neither "response_format" nor "json_object". The first classifier
    therefore treated it as a provider fault and dropped a healthy provider; it must
    instead retry once without JSON mode.
    """
    script = {
        "groq": [
            (400, {"error": {"message": "Failed to validate JSON. Please adjust your prompt. "
                                        "See 'failed_generation' for more details.",
                             "type": "invalid_request_error", "code": "json_validate_failed"}}),
            (200, ok_body('{"ok":true}')),
        ]
    }
    router, fake, client = make_router(script, [make_provider("groq")])
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}], json_mode=True)
    finally:
        await client.aclose()

    assert resp.text == '{"ok":true}'
    assert "response_format" in fake.requests[0][1]
    assert "response_format" not in fake.requests[1][1]
    assert router.stats.dead == {}, "a healthy provider must not be blacklisted"


@async_test
async def test_plain_400_still_counts_as_a_provider_error() -> None:
    """The broadened classifier must not swallow genuine malformed-request errors."""
    script = {"groq": [(400, {"error": {"message": "messages: field required"}})]}
    router, _, client = make_router(script, [make_provider("groq")])
    try:
        with pytest.raises(LLMUnavailable):
            await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()


@async_test
async def test_empty_completion_is_a_failure_not_a_result() -> None:
    """Regression from the live smoke test.

    `openai/gpt-oss-20b` on Groq is a reasoning model; with `max_tokens=16` the whole
    budget went to reasoning tokens and `content` came back as `""`. Returning that as
    success would have shipped an empty summary that looked like a completed call.
    """
    empty = {"model": "m", "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
             "usage": {"prompt_tokens": 30, "completion_tokens": 16}}
    script = {"reasoner": [(200, empty)], "groq": [(200, ok_body("real answer"))]}
    router, _, client = make_router(
        script, [make_provider("reasoner", weight=0), make_provider("groq", weight=1)]
    )
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert resp.text == "real answer"
    assert resp.provider_id == "groq"


@async_test
async def test_whitespace_only_completion_is_also_a_failure() -> None:
    script = {"a": [(200, ok_body("   \n  "))], "b": [(200, ok_body("ok"))]}
    router, _, client = make_router(
        script, [make_provider("a", weight=0), make_provider("b", weight=1)]
    )
    try:
        assert (await router.complete([{"role": "user", "content": "hi"}])).text == "ok"
    finally:
        await client.aclose()


@async_test
async def test_retired_model_is_recorded_and_blacklisted() -> None:
    """Regression from the live run: Gemini answered 404 on every call and said nothing.

    `gemini-2.5-flash-lite` was retired for new users; the router treated the 404 as an
    ordinary provider error, so the run reported only "provider failed" and the real
    cause was invisible in the output.
    """
    script = {
        "oldmodel": [(404, {"error": {"message": "This model is no longer available to new users"}})],
        "groq": [(200, ok_body("from the fallback"))],
    }
    router, _, client = make_router(
        script, [make_provider("oldmodel", weight=0), make_provider("groq", weight=1)]
    )
    try:
        resp = await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert resp.text == "from the fallback"
    assert "oldmodel" in router.stats.failures, "the error must be recorded"
    assert "404" in router.stats.failures["oldmodel"]
    assert "oldmodel" in router.stats.dead, "a retired model must not be retried"


@async_test
async def test_transient_provider_error_is_recorded_but_not_permanent() -> None:
    script = {"flaky": [(400, {"error": {"message": "messages: field required"}})]}
    router, _, client = make_router(script, [make_provider("flaky")])
    try:
        with pytest.raises(LLMUnavailable):
            await router.complete([{"role": "user", "content": "hi"}])
    finally:
        await client.aclose()

    assert "flaky" in router.stats.failures
    assert router.stats.dead == {}, "a plain 400 is not evidence of a dead provider"


def test_extract_json_raises_on_non_json() -> None:
    from aidaily.llm import LLMError

    with pytest.raises(LLMError):
        extract_json("I cannot help with that.")


@async_test
async def test_complete_json_repairs_a_non_json_reply_once() -> None:
    script = {"gemini": [(200, ok_body("I think the answer is yes.")), (200, ok_body('{"answer": "yes"}'))]}
    router, fake, client = make_router(script, [make_provider("gemini")])
    try:
        got = await router.complete_json([{"role": "user", "content": "q"}])
    finally:
        await client.aclose()

    assert got == {"answer": "yes"}
    assert len(fake.requests) == 2


@async_test
async def test_complete_json_repair_survives_a_caller_supplied_temperature() -> None:
    """Regression from the live run: `complete_json(..., temperature=0.2)` raised
    KeyError on the repair turn, because the repair call passed `temperature` twice."""
    script = {
        "gemini": [
            (200, ok_body("I think the answer is yes.")),
            (200, ok_body('{"answer": "yes"}')),
        ]
    }
    router, fake, client = make_router(script, [make_provider("gemini")])
    try:
        got = await router.complete_json(
            [{"role": "user", "content": "q"}], temperature=0.2, max_tokens=100, purpose="t"
        )
    finally:
        await client.aclose()

    assert got == {"answer": "yes"}
    assert fake.requests[0][1]["temperature"] == 0.2
    assert fake.requests[1][1]["temperature"] == 0.0, "the repair turn is deterministic"


# --- provider assembly -----------------------------------------------------------
def test_providers_from_env_only_includes_keys_that_exist() -> None:
    got = providers_from_env({"GEMINI_API_KEY": "x"}, include_relay=False)
    assert [p.id for p in got] == ["gemini"]
    assert got[0].tier == "official-free"


def test_providers_from_env_parses_relay_json_and_dedupes() -> None:
    relay = json.dumps([
        {"baseUrl": "https://a.example/v1", "key": "k1", "label": "A"},
        {"baseUrl": "https://a.example/v1", "key": "k2", "label": "A dup"},
        {"baseUrl": "https://b.example/v1", "key": "k3", "label": "B"},
    ])
    got = providers_from_env({"RELAY_KEYS_JSON": relay}, include_relay=True)
    assert len(got) == 2
    assert all(p.tier == "relay" for p in got)
    assert all(p.key_literal for p in got)


def test_providers_from_env_ignores_malformed_relay_json() -> None:
    assert providers_from_env({"RELAY_KEYS_JSON": "{not json"}, include_relay=True) == []
