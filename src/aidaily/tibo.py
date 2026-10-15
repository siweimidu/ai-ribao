"""The Tibo (Codex reset) monitor for a page: live when possible, snapshot when not.

This lives in the package rather than in `scripts/rerender_site.py`, which is where it was
written. That placement was the bug: the production publishing path (`aidaily run` ->
`publish.deliver_all`) never loaded Tibo data at all -- it only *accepted* a `tibo`
parameter. So every CI-deployed Tibo page was the empty state, and fixing the local script
changed nothing about what readers saw.

Two rules, both learned the hard way:

* **A source that is down must not stop the digest from rendering.** The page has an explicit
  empty state and it is honest.
* **But an empty state must mean "there is nothing", not "the request did not work".** The
  two look identical to a reader and only one is true.

The snapshot is committed (outside the gitignored network cache) so a run that cannot reach
the API still has the page's own recent data to draw.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

#: Committed snapshot of the last successful fetch.
SNAPSHOT_NAME = "aihot-codex-snapshot.json"


def _snapshot_path(root: Path) -> Path:
    return root / "data" / "state" / SNAPSHOT_NAME


def load_tibo(root: Path, *, cache_dir: Path | None = None) -> dict:
    """The monitor summary: fresh if it carries events, otherwise the committed snapshot.

    The freshness test is **whether there are events**, not whether the request succeeded.
    Testing `if payload:` was the previous bug: a successful response containing no events is
    truthy, so the code took the success path and returned a summary with an empty calendar
    while the snapshot sat unused. As far as the code could tell, nothing had failed.
    """
    from .aihot import AihotClient, activities, reset_events, reset_summary

    snapshot = _snapshot_path(root)
    cache = cache_dir if cache_dir is not None else root / "data" / "state" / "aihot_cache"

    reason = ""
    try:
        client = AihotClient(cache_dir=cache)
        payload = client.codex_resets()
        if payload:
            summary = reset_summary(payload, policy=client.policy)
            summary["events"] = reset_events(payload)
            summary["activities"] = activities(payload)
            summary["client_stats"] = dict(client.stats)
            if summary.get("events"):
                summary.pop("stale", None)
                _write_snapshot(snapshot, summary)
                return summary
            reason = f"抓取成功但 events 为空（total_events={summary.get('total_events')}）"
        else:
            reason = "抓取返回空载荷"
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {str(exc)[:80]}"

    if snapshot.exists():
        try:
            summary = json.loads(snapshot.read_text(encoding="utf-8"))
            if summary.get("events"):
                summary["stale"] = reason
                return summary
            reason = f"{reason}；快照里也没有事件"
        except (OSError, ValueError) as exc:
            reason = f"{reason}；快照读取失败 {type(exc).__name__}"

    return {"stale": reason, "events": [], "unavailable": True}


def _write_snapshot(path: Path, summary: dict) -> None:
    """Best effort. A read-only checkout must not break rendering."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
