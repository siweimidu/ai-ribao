"""Can the Tibo page be rendered from the committed snapshot alone?

The page depends on a live third-party call, and the CI runner cannot always make it. The
snapshot exists so the page still has a calendar there. Two things have to hold, and neither
is obvious from the code:

1. `load_tibo()` must choose the snapshot when the fresh response carries **no events**.
   Testing `if payload:` was not enough: a successful response with an empty event list is
   truthy, so the first version took the success path and rendered a blank page while the
   snapshot sat unused -- the fallback never ran because, as far as the code could tell,
   nothing had failed.
2. The snapshot's contents must be sufficient for `render_tibo` to produce the grid, which
   `scripts/test_calendars.py` asserts against the rendered file.

This checks both without touching the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "state" / "aihot-codex-snapshot.json"


def load_rerender_module():
    """Import `scripts/rerender_site.py`, which is a script rather than a package module."""
    path = ROOT / "scripts" / "rerender_site.py"
    spec = importlib.util.spec_from_file_location("_rerender_site_probe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_snapshot_has_events() -> None:
    """A snapshot with no events would render the same blank page it exists to prevent."""
    assert SNAPSHOT.exists(), "快照必须提交，否则 CI 渲染出的 Tibo 页永远是空的"
    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    events = doc.get("events") or []
    assert events, "快照里没有事件，等于没有快照"
    # The grid needs dates to place markers on. The reset events carry several; assert at
    # least one is populated rather than naming a single one, so a field rename upstream
    # does not silently empty the calendar.
    date_fields = ("occurred_on", "confirmed_at", "created_at")
    assert any(any(e.get(f) for f in date_fields) for e in events), \
        f"事件里没有可用于日历定位的日期（找过 {date_fields}）"


def test_the_snapshot_renders_a_calendar() -> None:
    """The point of the snapshot: a grid, not an empty state."""
    from aidaily.site import SiteContext, render_tibo

    doc = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    ctx = SiteContext(site_url="https://example.com", archive=[("2026-10-15", 60)])

    html = render_tibo(ctx, doc)
    assert "data-ecal-grid" in html, "快照没有渲染出日历网格"
    assert "ecal" in html


def test_an_event_less_response_falls_back_to_the_snapshot(monkeypatch) -> None:
    """`if payload:` was the bug: a healthy response with no events is still truthy.

    Simulated by making the client return a payload whose events list is empty, which is
    what a reachable-but-empty upstream looks like.
    """
    module = load_rerender_module()

    class FakeClient:
        policy = None
        stats: dict = {}

        def __init__(self, **_kw) -> None:
            pass

        def codex_resets(self):
            return {"data": {"events": []}}

    fake_aihot = type(sys)("aidaily.aihot")
    fake_aihot.AihotClient = FakeClient            # type: ignore[attr-defined]
    fake_aihot.reset_summary = lambda payload, policy=None: {  # type: ignore[attr-defined]
        "total_events": 0, "events": [],
    }
    fake_aihot.reset_events = lambda payload: []   # type: ignore[attr-defined]
    fake_aihot.activities = lambda payload: []     # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "aidaily.aihot", fake_aihot)
    # `from aidaily.aihot import ...` inside the function still consults the real package,
    # so patch the attribute the import binds to.
    import aidaily
    monkeypatch.setattr(aidaily, "aihot", fake_aihot, raising=False)

    summary = module.load_tibo()
    assert summary, "应当回退到快照而不是返回空"
    assert summary.get("events"), "回退到的快照必须带事件"
    assert summary.get("stale"), "回退时必须标记 stale，页面才能说明数据来自缓存"
