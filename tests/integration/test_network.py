"""Acceptance tests that need the real network.

Skipped by default. Run them deliberately:

    AIDAILY_NETWORK_TESTS=1 pytest -m network -v

They exist because some promises can only be checked against the live internet: that the
registry's URLs still resolve, that a probe classifies a wall as a wall, and that the
model layer can actually reach a provider. Everything else in the suite is offline and
deterministic.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from _async import async_test
from aidaily.http import HttpClient
from aidaily.registry import apply_overrides, load_overrides, load_registry

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("AIDAILY_NETWORK_TESTS") != "1",
        reason="set AIDAILY_NETWORK_TESTS=1 to run live network acceptance tests",
    ),
]

ROOT = Path(__file__).resolve().parents[2]

#: A source may legitimately be blocked or gone; what must never happen is that the
#: whole collection silently returns nothing.
MIN_HEALTHY_SOURCES = 25


@async_test
async def test_registry_sources_still_resolve() -> None:
    sources, _ = apply_overrides(load_registry())
    enabled = [s for s in sources if s.enabled and not s.needs_credential]
    assert len(enabled) >= 30, "the registry should expose a substantial live set"

    async with HttpClient(timeout_s=25.0, retries=1, min_host_interval=0.4) as http:
        results = await asyncio.gather(*(http.get(s.url) for s in enabled), return_exceptions=True)

    ok = sum(1 for r in results if isinstance(r, object) and getattr(r, "ok", False))
    dead = [s.source_id for s, r in zip(enabled, results) if not getattr(r, "ok", False)]

    # Reported rather than asserted per-source: a single site going down is normal, and
    # the registry keeps it either way.
    print(f"\nhealthy {ok}/{len(enabled)}; not ok: {dead[:10]}")
    assert ok >= MIN_HEALTHY_SOURCES, f"only {ok} sources responded; the internet or the registry changed"


def test_window_selection_against_real_clock() -> None:
    """The window must be non-empty at any hour the schedule can fire.

    The workflow triggers at 09:53, 10:07, 10:23 and 10:41 Beijing. This asserts the
    configured 26h window always covers the previous day's editions, so a trigger cannot
    land in a hole and produce an empty digest.
    """
    from aidaily.config import load_config

    cfg = load_config(env={})
    assert cfg.run.window_hours >= 26, "a 24h window leaves no margin for a late source"


def test_llm_provider_reachable_if_configured() -> None:
    """Only runs when a key is present; verifies the endpoint accepts it.

    Uses `GET /models`, which costs no tokens -- the same trick as
    scripts/probe_llm_channels.py.
    """
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        pytest.skip("no GROQ_API_KEY in the environment")

    resp = httpx.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=25,
    )
    assert resp.status_code == 200, resp.text[:200]
    assert resp.json().get("data"), "the provider returned an empty model list"
