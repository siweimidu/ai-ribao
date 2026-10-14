"""AIHOT integration: the client's contract with the source.

AIHOT's terms shape this module as much as the data does, so several tests assert *behaviour
toward the source* rather than parsing:

  * cache validation (ETag / If-None-Match) and a minimum interval between calls, because
    the terms require respecting cache headers and a minimum poll interval;
  * `Retry-After` honoured on 429 rather than a blind retry;
  * a failure degrades to "no data", never to an exception that stops the digest;
  * the policy headers are kept, because the API exposes them deliberately and attribution
    must survive to the page;
  * `/selected/snapshot` is never called -- that endpoint exists to keep a complete local
    copy, which is the bulk-redistribution case the terms put behind written authorization.

Nothing here touches the network. The client is driven through a fake opener so the tests
are deterministic and cost no quota.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from aidaily.aihot import (
    AihotClient,
    AihotUnavailable,
    Policy,
    activities,
    reset_events,
    reset_summary,
)

# ------------------------------------------------------------------ fixtures


class FakeResponse:
    def __init__(self, payload: dict, headers: dict | None = None, status: int = 200):
        raw = json.dumps(payload).encode("utf-8")
        self._body = gzip.compress(raw) if (headers or {}).get("Content-Encoding") == "gzip" else raw
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(script: list):
    """Return (opener, calls). Each script item is a response dict, an int status, or an exception."""
    calls: list[dict] = []

    def opener(request, timeout=None):
        calls.append({"url": request.full_url, "headers": dict(request.headers)})
        item = script.pop(0) if script else FakeResponse({})
        if isinstance(item, int):
            raise urllib.error.HTTPError(request.full_url, item, "err", Message(), io.BytesIO(b""))
        if isinstance(item, Exception):
            raise item
        return item

    return opener, calls


HEADERS = {
    "ETag": 'W/"v1-test"',
    "X-AIHOT-Policy-Version": "1.1",
    "X-AIHOT-Commercial-Use": "written-authorization-required",
    "X-AIHOT-Contact": "wzglyay@virxact.com",
    "Cache-Control": "public, max-age=60",
    "Content-Encoding": "gzip",
}

CODEX_PAYLOAD = {
    "schemaVersion": 1,
    "timezone": "Asia/Shanghai",
    "today": "2026-10-14",
    "checkedAt": "2026-10-14T12:40:41+08:00",
    "historyFrom": "2026-06-12T00:00:00.000+08:00",
    "count": 3,
    "monitor": {"status": "healthy", "lastCollectedAt": "2026-10-14T12:40:41+08:00",
                "pendingCount": 0, "reviewCount": 0},
    "events": [
        {
            "id": "a", "type": "direct_reset", "label": "全员重置",
            "displayLabel": "额度重置", "status": "confirmed", "title": "Tibo 确认重置",
            "createdAt": "2026-10-13T09:03:25.000+08:00", "confirmedAt": "2026-10-13T13:06:06.000+08:00",
            "scope": "", "schedule": {"label": "北京时间预计 10月13日 15:00 前"},
            "posts": [{"stage": "确认完成", "text": "已经完成了。", "originalText": "It's done.",
                       "fullText": "你的重置要配点什么小菜？已经完成了。",
                       "fullOriginalText": "What would you like with your side of reset? It's done.",
                       "publishedAt": "2026-10-13T13:06:06.000+08:00",
                       "url": "https://x.com/thsottiaux/status/1"}],
        },
        {
            "id": "b", "type": "reset_credit", "label": "发重置卡", "displayLabel": "重置卡发放",
            "status": "confirmed", "title": "重置卡已发放",
            "createdAt": "2026-10-08T03:19:00.000+08:00", "scope": "", "posts": [],
        },
        {
            "id": "c", "type": "direct_reset", "label": "全员重置", "displayLabel": "重置（形式未明确）",
            "status": "confirmed", "title": "Tibo 确认重置",
            "createdAt": "2026-10-07T11:35:00.000+08:00", "scope": "", "posts": [],
        },
    ],
    "activities": [
        {"id": "x", "kind": "related", "text": "希望尽快搞定。", "originalText": "Hope to get it done soon.",
         "url": "https://x.com/thsottiaux/status/9", "publishedAt": "2026-10-13T14:21:26.000+08:00",
         "statusChanged": False, "action": None},
    ],
    "outage": None,
}


@pytest.fixture
def client(tmp_path: Path):
    def build(script: list) -> tuple[AihotClient, list]:
        c = AihotClient(cache_dir=tmp_path / "cache")
        opener, calls = make_opener(script)
        import aidaily.aihot as mod

        original = mod.urllib.request.urlopen
        mod.urllib.request.urlopen = opener  # type: ignore[assignment]
        c._restore = lambda: setattr(mod.urllib.request, "urlopen", original)  # type: ignore[attr-defined]
        return c, calls

    return build


def expire(c: AihotClient, url: str = "https://aihot.news/api/v1/codex-resets") -> None:
    """Age the cached copy so the next call revalidates instead of using the TTL.

    Takes the URL, not the cache path: `_load`/`_save` key on the URL and derive the path
    themselves, so passing a path makes `_cache_path` receive a `Path` and blow up inside
    `str.replace`.
    """
    entry = c._load(url)
    assert entry is not None, "nothing cached to expire"
    entry.fetched_at = 0
    c._save(entry)


# =============================== mapping ========================================
def test_events_are_normalised_and_newest_first() -> None:
    rows = reset_events(CODEX_PAYLOAD)
    assert [r["id"] for r in rows] == ["a", "b", "c"], "newest first"
    assert rows[0]["label"] == "额度重置"
    assert rows[0]["schedule_label"] == "北京时间预计 10月13日 15:00 前"
    assert rows[0]["posts"][0]["url"].startswith("https://x.com/")


def test_full_text_is_preferred_over_the_truncated_one() -> None:
    """The API carries both a short `text` and a `fullText`; the page wants the full one."""
    post = reset_events(CODEX_PAYLOAD)[0]["posts"][0]
    assert post["text"].startswith("你的重置")
    assert post["original"].startswith("What would you like")


def test_credit_events_are_counted_as_cards() -> None:
    """The API's type for a reset-card grant is `reset_credit`, not `reset_card`.

    An earlier version filtered on "card" appearing in the type, which matched nothing and
    reported zero cards granted while thirteen were sitting in the live data.
    """
    stats = reset_summary(CODEX_PAYLOAD)["stats"]
    assert stats["cards90d"] == 1
    assert stats["totalCards"] == 1
    assert stats["totalResets"] == 2


def test_statistics_are_labelled_as_derived() -> None:
    """AIHOT's `monitor` is collector health, not these numbers, so the page must say who
    computed them."""
    summary = reset_summary(CODEX_PAYLOAD)
    assert summary["derived"] is True
    assert summary["collector"]["status"] == "healthy", "the collector state is kept separately"
    assert "status" not in summary["stats"]


def test_median_gap_uses_whole_days() -> None:
    """10-13 and 10-07 are 6 days apart, and there is only one gap, so it is the median."""
    assert reset_summary(CODEX_PAYLOAD)["stats"]["medianGapDays"] == 6


def test_activities_are_mapped() -> None:
    rows = activities(CODEX_PAYLOAD)
    assert len(rows) == 1
    assert rows[0]["url"].startswith("https://x.com/")


def test_empty_payload_yields_an_empty_summary_not_an_error() -> None:
    summary = reset_summary({})
    assert summary["stats"]["resets90d"] == 0
    assert summary["stats"]["lastResetOn"] is None
    assert summary["total_events"] == 0


# =============================== policy =========================================
def test_policy_headers_are_captured() -> None:
    """The API lists these in `access-control-expose-headers`, which is a request to read
    and pass them on."""
    policy = Policy(
        version="1.1",
        commercial_use="written-authorization-required",
        contact="wzglyay@virxact.com",
    )
    assert policy.requires_authorization_for_commercial
    assert policy.describe()["requires_authorization_for_commercial"] is True
    # The stored form must round-trip: it is fed back through Policy(**).
    assert Policy(**policy.as_dict()).version == "1.1"


def test_a_stored_policy_with_unknown_fields_still_loads() -> None:
    """An older cache entry held a field that no longer exists.

    Passing it to the constructor raised `unexpected keyword argument` and made **every**
    cached response unreadable, so the client could not start at all. Unknown keys are
    dropped -- which is also what the API asks of clients.
    """
    from aidaily.aihot import _policy_from_doc

    policy = _policy_from_doc({
        "version": "1.1",
        "commercial_use": "written-authorization-required",
        "requires_authorization_for_commercial": True,   # no longer a constructor field
        "something_new": 42,
    })
    assert policy.version == "1.1"
    assert policy.requires_authorization_for_commercial


def test_summary_carries_attribution_and_policy() -> None:
    summary = reset_summary(CODEX_PAYLOAD, policy=Policy(version="1.1", contact="a@b.c"))
    assert summary["attribution"]["name"] == "AIHOT"
    assert summary["attribution"]["url"].startswith("https://aihot.news/")
    assert summary["policy"]["contact"] == "a@b.c"


# =============================== caching ========================================
def test_a_second_call_within_the_ttl_makes_no_request(client) -> None:
    c, calls = client([FakeResponse(CODEX_PAYLOAD, HEADERS)])
    try:
        first = c.codex_resets()
        second = c.codex_resets()
        assert first == second
        assert len(calls) == 1, "the TTL cache should absorb the second call"
        assert c.stats["cache_hits"] == 1
    finally:
        c._restore()


def test_cache_hit_still_restores_the_policy(client) -> None:
    """Regression: the policy was only assigned on the network path.

    A cache hit returned the data while `client.policy` stayed empty, so the page rendered
    without the terms notice it is required to carry.
    """
    c, _ = client([FakeResponse(CODEX_PAYLOAD, HEADERS)])
    import aidaily.aihot as mod

    try:
        c.codex_resets()
        fresh = AihotClient(cache_dir=c.cache_dir)
        original = mod.urllib.request.urlopen
        mod.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a warm cache must not fetch")
        )
        try:
            fresh.codex_resets()
        finally:
            mod.urllib.request.urlopen = original
        assert fresh.policy.version == "1.1"
        assert fresh.policy.requires_authorization_for_commercial
    finally:
        c._restore()


def header(headers: dict, name: str) -> str | None:
    """Case-insensitive header lookup.

    `urllib` capitalises only the first letter of each word, so a replayed `If-None-Match`
    arrives as `If-none-match`. HTTP header names are case-insensitive, and asserting on the
    exact casing tested `urllib`'s formatting rather than the client's behaviour.
    """
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def test_etag_is_replayed_and_a_304_reuses_the_body(client) -> None:
    c, calls = client([FakeResponse(CODEX_PAYLOAD, HEADERS), 304])
    try:
        c.codex_resets()
        expire(c)

        again = c.codex_resets()
        assert again == CODEX_PAYLOAD, "a 304 must replay the stored body"
        assert c.stats["not_modified"] == 1
        assert header(calls[1]["headers"], "If-None-Match") == 'W/"v1-test"'
    finally:
        c._restore()


def test_minimum_interval_is_enforced(client) -> None:
    """The terms ask for a minimum poll interval; the client must be the one enforcing it."""
    import aidaily.aihot as mod

    c, _ = client([])
    try:
        assert mod.MIN_INTERVAL_SECONDS >= 1.0
        c._last_call = __import__("time").monotonic()
        before = __import__("time").monotonic()
        c._throttle()
        assert __import__("time").monotonic() - before >= mod.MIN_INTERVAL_SECONDS * 0.8
    finally:
        c._restore()


# =============================== failure modes ==================================
def test_a_429_is_retried_after_retry_after(client, monkeypatch) -> None:
    import aidaily.aihot as mod

    slept: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: slept.append(s))

    c, calls = client([429, 429, FakeResponse(CODEX_PAYLOAD, HEADERS)])
    try:
        payload = c.codex_resets()
        assert payload == CODEX_PAYLOAD
        assert c.stats["retries"] == 2
        assert slept, "a 429 must wait rather than retry immediately"
    finally:
        c._restore()


def test_a_persistent_failure_raises_a_typed_error(client, monkeypatch) -> None:
    import aidaily.aihot as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c, _ = client([500, 500, 500])
    try:
        with pytest.raises(AihotUnavailable):
            c.codex_resets()
        assert c.stats["errors"] >= 1
    finally:
        c._restore()


def test_a_404_returns_none_rather_than_raising(client) -> None:
    """A missing endpoint is a configuration fact, not a transport failure.

    `/feed.json` was 404 on the live site; a source written against it would otherwise look
    like an outage forever.
    """
    c, _ = client([404])
    try:
        assert c.codex_resets() == {}
    finally:
        c._restore()


def test_network_failure_with_a_cache_falls_back_to_stale(client, monkeypatch) -> None:
    import aidaily.aihot as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c, _ = client([FakeResponse(CODEX_PAYLOAD, HEADERS)])
    try:
        c.codex_resets()
        expire(c)

        import urllib.error as ue

        mod.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(ue.URLError("down"))
        assert c.codex_resets() == CODEX_PAYLOAD, "stale data beats no data for a cited source"
    finally:
        c._restore()


def test_a_new_client_without_cache_raises_on_failure(client, monkeypatch) -> None:
    import aidaily.aihot as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c, _ = client([500, 500, 500])
    try:
        with pytest.raises(AihotUnavailable):
            c.codex_resets()
    finally:
        c._restore()


# =============================== scope ==========================================
def test_the_bulk_snapshot_endpoint_is_never_used() -> None:
    """`/selected/snapshot` exists to keep a complete local copy of the selected set.

    That is the bulk-public-redistribution case AIHOT's terms put behind prior written
    authorization, so this client must not call it. The assertion is on the source text
    because the point is that the endpoint never appears as a *call*.

    Comments and the module docstring are stripped first: the docstring names the endpoint
    to explain why it is avoided, and a naive scan reports that explanation as a violation.
    """
    import re

    source = (Path(__file__).resolve().parents[2] / "src" / "aidaily" / "aihot.py").read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', " ", source)
    code = re.sub(r"(?m)^\s*#.*$", " ", code)

    assert "selected/snapshot" not in code, "the bulk snapshot endpoint must never be called"
    assert "BASE_URL}/selected" not in code
    # And the reasoning is preserved in the documentation, so a future edit knows why.
    assert "bulk" in source.lower() and "authorization" in source.lower()


def test_changes_endpoint_is_available_for_withdrawals() -> None:
    """The terms require handling retraction; `changes()` is how a deleted entry is seen."""
    source = (Path(__file__).resolve().parents[2] / "src" / "aidaily" / "aihot.py").read_text(encoding="utf-8")
    assert "/selected/changes" in source
    assert "withdraw" in source.lower() or "retract" in source.lower()
