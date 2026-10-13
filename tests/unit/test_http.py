"""HTTP layer: retry policy, rate-limit handling, politeness, conditional requests.

`http.py` carried no tests for a long time while holding the logic most likely to be
subtly wrong -- what gets retried and what does not. The distinction matters: retrying a
403 three times annoys the operator and burns the run budget, while *not* retrying a
transient 500 loses a source for the day.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from _async import async_test
from aidaily.http import HttpClient, HostLimiter, _retry_after

SLEPT: list[float] = []


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Backoff must not make the suite slow, but the *sequence* is still worth asserting."""
    SLEPT.clear()

    async def fake_sleep(seconds: float) -> None:
        SLEPT.append(seconds)

    monkeypatch.setattr("aidaily.http.asyncio.sleep", fake_sleep)


def client_for(handler, **kw) -> tuple[HttpClient, httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)
    http = HttpClient(**kw)
    return http, httpx.AsyncClient(transport=transport)


def attach(http: HttpClient, client: httpx.AsyncClient) -> HttpClient:
    http._client = client
    return http


# =============================== the happy path ==================================
@async_test
async def test_successful_get() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello", headers={"Content-Type": "text/plain"})

    http, raw = client_for(handler)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.ok and res.status == 200 and res.text == "hello"
    assert res.attempts == 1


@async_test
async def test_body_is_capped() -> None:
    """A 200 MB response must not be read into memory."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10_000)

    http, raw = client_for(handler, max_bytes=100)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert len(res.body) == 100


# =============================== what must NOT be retried ========================
@pytest.mark.parametrize("code", [400, 403, 404, 410])
@async_test
async def test_client_errors_are_not_retried(code: int) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(code, text="nope")

    http, raw = client_for(handler, retries=3)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert calls["n"] == 1, f"HTTP {code} must not be retried"
    assert res.verdict in ("blocked", "dead")
    assert SLEPT == []


@async_test
async def test_403_is_classified_as_blocked_not_dead() -> None:
    """The two need different fixes, so they must not collapse into one verdict."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    http, raw = client_for(handler)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.verdict == "blocked" and res.status == 403


@async_test
async def test_404_is_classified_as_dead() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="gone")

    http, raw = client_for(handler)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.verdict == "dead"


# =============================== what MUST be retried ============================
@async_test
async def test_server_error_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, text="recovered")

    http, raw = client_for(handler, retries=2)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.ok and res.text == "recovered"
    assert calls["n"] == 2 and res.attempts == 2
    assert SLEPT, "backoff must be applied between attempts"


@async_test
async def test_transport_error_is_retried_then_gives_up_as_dead() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("no route to host")

    http, raw = client_for(handler, retries=2)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert calls["n"] == 3, "initial attempt plus two retries"
    assert res.verdict == "dead" and "ConnectError" in res.detail


@async_test
async def test_429_honours_retry_after_then_gives_up() -> None:
    """A rate limit is worth one polite wait; then the source is done for this run."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")

    http, raw = client_for(handler, retries=1)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.verdict == "blocked"
    assert 7.0 in SLEPT, f"Retry-After was ignored: {SLEPT}"


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 5.0), ("", 5.0), ("not-a-number", 5.0), ("0", 1.0), ("3", 3.0), ("999", 30.0)],
)
def test_retry_after_parsing_and_cap(raw, expected) -> None:
    """A server may ask for an hour; the run cannot wait an hour."""
    assert _retry_after(raw) == expected


# =============================== conditional requests ============================
@async_test
async def test_validators_are_stored_and_replayed() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, text="body", headers={"ETag": 'W/"abc"', "Last-Modified": "Tue, 13 Oct 2026 00:00:00 GMT"})

    http, raw = client_for(handler)
    try:
        attached = attach(http, raw)
        await attached.get("https://example.com/x")
        await attached.get("https://example.com/x")
    finally:
        await raw.aclose()

    assert seen[1].get("if-none-match") == 'W/"abc"'
    assert "if-modified-since" in {k.lower() for k in seen[1]}


@async_test
async def test_304_is_reported_as_not_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    http, raw = client_for(handler)
    try:
        res = await attach(http, raw).get("https://example.com/x")
    finally:
        await raw.aclose()

    assert res.ok and res.verdict == "not_modified"


@async_test
async def test_conditional_can_be_disabled() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers))
        return httpx.Response(200, text="b", headers={"ETag": "x"})

    http, raw = client_for(handler)
    try:
        attached = attach(http, raw)
        await attached.get("https://example.com/x")
        await attached.get("https://example.com/x", conditional=False)
    finally:
        await raw.aclose()

    assert "if-none-match" not in {k.lower() for k in seen[1]}


# =============================== politeness ======================================
@async_test
async def test_per_host_interval_is_enforced() -> None:
    """Twelve Reddit URLs in one run must not look like an attack."""
    limiter = HostLimiter(min_interval=0.05)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    import aidaily.http as http_mod

    original = http_mod.asyncio.sleep
    http_mod.asyncio.sleep = fake_sleep
    try:
        await limiter.wait("https://a.example/1")
        await limiter.wait("https://a.example/2")   # same host -> spaced
        await limiter.wait("https://b.example/1")   # different host -> no wait
    finally:
        http_mod.asyncio.sleep = original

    assert len(waits) == 1 and waits[0] > 0


@async_test
async def test_context_manager_requires_use() -> None:
    http = HttpClient()
    with pytest.raises(RuntimeError, match="context manager"):
        await http.get("https://example.com")
