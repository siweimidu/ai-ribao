"""Retroactively score the pre-focus issues and drop what today's floor would drop.

The 10-14 and 10-15 issues were published before the relevance scorer existed, so their
`rank_components` carry no `focus` value and the purge kept everything. The scorer itself only
needs the event's title and source ids -- both are in the archived digest -- so the honest move
is to rebuild each event and score it with the module as it exists now, which is exactly what a
digest published today would have received.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily.focus import focus_multiplier  # noqa: E402
from aidaily.models import Event  # noqa: E402
from aidaily.registry import apply_overrides, load_overrides, load_registry  # noqa: E402

FLOOR = 0.35


def main() -> int:
    sources, _ = apply_overrides(load_registry(), load_overrides())
    by_id = {s.source_id: s for s in sources}

    for date in ("2026-10-14", "2026-10-15", "2026-10-16"):
        path = ROOT / "data" / "digests" / f"{date}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        events = doc["digest"]["top_events"]
        kept, dropped = [], []
        for raw in events:
            event = Event.model_validate(raw)
            _, comp = focus_multiplier(event, by_id)
            focus = comp["focus"]
            (kept if focus >= FLOOR else dropped).append((raw, focus, comp))
            # Write the score back so the page can show it and the purge is auditable.
            rc = raw.setdefault("rank_components", {})
            rc["focus"] = comp["focus"]
            rc["focus_headline"] = comp["focus_headline"]
            rc["focus_source"] = comp["focus_source"]
            rc["focus_multiplier"] = comp["focus_multiplier"]
        doc["digest"]["top_events"] = [raw for raw, _, _ in kept]
        counts = doc["digest"].get("counts") or {}
        if counts:
            counts["events"] = len(kept)
            counts["with_insights"] = sum(
                1 for raw, _, _ in kept if raw["event_id"] in (doc.get("insights") or {})
            )
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {date}: 保留 {len(kept)}，剔除 {len(dropped)}")
        for raw, focus, _ in dropped[:6]:
            ins = (doc.get("insights") or {}).get(raw["event_id"]) or {}
            title = ins.get("title") or raw["title"]
            print(f"      ✗ focus={focus:.2f}  {title[:52]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
