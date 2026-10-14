"""Re-rank an archived digest with the current ranking code, keeping its analysis.

Why this exists: the ranking is deterministic and needs no model, but the archive was
produced by an older ranker. Waiting for the next scheduled run to see a ranking change is
slow, and re-running the whole pipeline would spend model quota to reproduce text that is
already on disk and still correct.

What it does:

1. Rebuilds the events from the same raw items with the current L2/L3 code, so clustering
   fixes take effect (a story split across several events is merged).
2. **Carries the existing insights over**, matched by which items each event contains. Event
   ids change when clustering changes, so a naive id lookup would silently drop every
   translation and put English headlines back on the page.
3. Re-scores and re-selects with the current heat model.
4. Rewrites the digest JSON.

What it deliberately does not do: invent analysis. An event with no matching old insight is
reported as such rather than given placeholder text.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily import pipeline  # noqa: E402
from aidaily.analyze import EventInsight  # noqa: E402
from aidaily.collect import read_items_jsonl  # noqa: E402
from aidaily.config import load_config  # noqa: E402
from aidaily.dedup import units_from_result  # noqa: E402
from aidaily.l3 import build_events  # noqa: E402
from aidaily.models import Digest, Event  # noqa: E402
from aidaily.registry import apply_overrides, load_overrides, load_registry  # noqa: E402


def carry_over_insights(
    old_events: list[Event],
    old_insights: dict[str, dict],
    new_events: list[Event],
) -> tuple[dict[str, dict], list[str]]:
    """Match each new event to the old insight that covered the most of the same items.

    Exact-id matching is useless here: merging two events produces a new id, and the whole
    point of re-running L3 is that it merges. Item overlap is the stable key -- the items are
    the same rows either way.
    """
    by_item: dict[str, str] = {}
    for event in old_events:
        for item_id in event.member_item_ids:
            by_item[item_id] = event.event_id

    carried: dict[str, dict] = {}
    missing: list[str] = []

    for event in new_events:
        # Vote by item, so a merged event inherits from whichever old event owned most of
        # the items it now contains.
        votes: dict[str, int] = {}
        for item_id in event.member_item_ids:
            old_id = by_item.get(item_id)
            if old_id:
                votes[old_id] = votes.get(old_id, 0) + 1
        if not votes:
            missing.append(event.event_id)
            continue
        best = max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0]
        insight = old_insights.get(best)
        if insight is None:
            missing.append(event.event_id)
            continue
        carried[event.event_id] = insight

    return carried, missing


async def main() -> int:
    digest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "digests" / "2026-10-14.json"
    payload = json.loads(digest_path.read_text(encoding="utf-8"))
    old_digest = Digest.model_validate(payload["digest"])
    old_insights: dict[str, dict] = payload.get("insights") or {}

    cfg = load_config(env={})
    sources, _ = apply_overrides(load_registry(), load_overrides())
    items = read_items_jsonl(str(ROOT / "data" / "raw" / "items.jsonl"))
    items_by_id = {i.item_id: i for i in items}

    stage = pipeline.run_dedup_stage(items, cfg)
    units = units_from_result(stage.result, stage.window.kept)
    events, cluster = await build_events(units, None)
    print(f"  事件 {len(old_digest.top_events)} → {len(events)}"
          f"  (无判定合并 {cluster.accepted_without_judge})")

    carried, missing = carry_over_insights(old_digest.top_events, old_insights, events)
    print(f"  沿用旧分析 {len(carried)}/{len(events)}"
          + (f"  无对应 {len(missing)}" if missing else ""))

    insights: dict[str, EventInsight] = {}
    for event_id, raw in carried.items():
        try:
            # `EventInsight` is a dataclass, not a pydantic model, so there is no
            # `model_validate` -- and calling one raises AttributeError, which an earlier
            # version swallowed per-event. The result was a re-ranked digest with every
            # translation silently dropped and English headlines back on the page, which is
            # exactly the failure this whole round of work was fixing.
            insights[event_id] = EventInsight(**raw)
        except (TypeError, ValueError) as exc:
            print(f"    跳过无法解析的分析 {event_id}: {type(exc).__name__}: {exc}")

    if not insights:
        print("  没有可沿用的分析，中止（重新排序会丢掉全部中文标题）")
        return 2
    print(f"  解析成功 {len(insights)} 条分析")

    # **Select only from events that carry an analysis.**
    #
    # The archive stores the published sixty, but re-clustering produces the full day (204
    # events). Selecting from all of them would pull in events that were never analysed by a
    # model, and an unanalysed event renders its source's own headline -- which for an
    # English feed is an English sentence on a Chinese page. Measured: doing that took the
    # untranslated count from 32 to 29 *and* replaced analysed entries with raw ones.
    #
    # Restricting the candidate set keeps every entry translated. The digest is then smaller
    # than sixty; that is the honest size for an archive re-rank, and the next scheduled run
    # analyses the whole day again.
    analysed = [e for e in events if e.event_id in insights]
    print(f"  有分析的事件 {len(analysed)}/{len(events)}，作为候选集")

    selected, report = pipeline.select_for_digest(analysed, stage, sources, cfg)
    print(f"  选出 {len(selected)} 条；榜首 heat="
          f"{(selected[0].rank_components or {}).get('heat')}  {selected[0].title[:48]}")

    new_digest = old_digest.model_copy(update={
        "top_events": selected,
        "counts": {**old_digest.counts, "events": len(selected)},
    })
    payload["digest"] = json.loads(new_digest.model_dump_json())
    # Keep only the analyses the digest actually references, so the file does not grow a
    # tail of entries nothing links to.
    keep = {e.event_id for e in selected}
    payload["insights"] = {
        eid: {
            "event_id": ins.event_id, "title": ins.title, "facts": ins.facts,
            "inferences": ins.inferences, "opinions": ins.opinions,
            "uncertainties": ins.uncertainties, "key_points": ins.key_points,
            "rule_based": ins.rule_based,
        }
        for eid, ins in insights.items() if eid in keep
    }
    digest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已写入 {digest_path.relative_to(ROOT)}（分析 {len(payload['insights'])} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
