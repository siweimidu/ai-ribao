"""Purge sub-floor stories from the published issues, judged on the title readers actually see.

## The bug in the previous version

It scored `event.title` -- the **source's raw headline**, e.g.
`可灵AI新一代模型Kling 4.0正式上线 - 21财经`. The page does not show that; it shows the
model-written title from `insights`, e.g. `可灵AI新一代模型Kling 4.0正式上线`. Scoring the raw
title meant the purge decided on text no reader ever sees, so a vocabulary fix to the *displayed*
string had no effect on the outcome.

Both are now scored and a story is kept when **either** clears the floor. That is the honest rule:
the digest is an AI digest if the story is about AI, and a trailing outlet name or an English
original should not be the thing that decides.

The floor is imported from `pipeline.MIN_AI_RELEVANCE` so the archive and the live pipeline cannot
drift apart -- a second copy of `0.70` here is exactly how the two would silently disagree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily.focus import _headline_focus  # noqa: E402
from aidaily.pipeline import MIN_AI_RELEVANCE  # noqa: E402


def focus_of(event: dict, insight: dict | None) -> tuple[float, str]:
    """`(best focus, the title a reader would see)` for one archived event."""
    raw = event.get("title") or ""
    shown = (insight or {}).get("title") or raw
    return max(_headline_focus(raw), _headline_focus(shown)), (shown or raw)


def purge(path: Path) -> tuple[int, int, list[tuple[float, str]]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    digest = doc["digest"]
    insights = doc.get("insights") or {}

    kept: list[dict] = []
    dropped: list[tuple[float, str]] = []
    for event in digest["top_events"]:
        focus, title = focus_of(event, insights.get(event["event_id"]))
        event.setdefault("rank_components", {})["focus"] = round(focus, 4)
        if focus >= MIN_AI_RELEVANCE:
            kept.append(event)
        else:
            dropped.append((focus, title))

    digest["top_events"] = kept
    counts = digest.get("counts") or {}
    if counts:
        counts["events"] = len(kept)
        counts["with_insights"] = sum(1 for e in kept if e["event_id"] in insights)

    # The section layout maps section -> event ids; prune the dropped ones so the page's section
    # list cannot reference a story that is no longer published.
    layout = digest.get("sections")
    if isinstance(layout, dict):
        live = {e["event_id"] for e in kept}
        for section, ids in list(layout.items()):
            if isinstance(ids, list):
                layout[section] = [i for i in ids if i in live]

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(kept), len(dropped), dropped


def main() -> int:
    total_dropped = 0
    for date in ("2026-10-14", "2026-10-15", "2026-10-16"):
        path = ROOT / "data" / "digests" / f"{date}.json"
        if not path.exists():
            continue
        kept, dropped, examples = purge(path)
        total_dropped += dropped
        print(f"  {date}: 保留 {kept}，剔除 {dropped}")
        for focus, title in examples[:5]:
            print(f"      ✗ focus={focus:.2f}  {title[:56]}")
    print(f"\n  合计剔除 {total_dropped} 条（门槛 {MIN_AI_RELEVANCE}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
