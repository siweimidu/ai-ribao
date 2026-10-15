"""Does the rubric change the ranking, and in the right direction?

Unit tests pin the parsing and the arithmetic. They cannot answer the question that matters:
when a model reads `config/profile.md` and scores a real day's headlines, does the top of the
digest actually improve?

This prints the before/after order for the real events, so the answer is visible rather than
argued about. It uses the relay file if one is provided and otherwise reports that the check
was skipped -- a missing credential must not look like a passing test OR a failing one.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily.analyze import EventInsight  # noqa: E402
from aidaily.collect import read_items_jsonl  # noqa: E402
from aidaily.config import load_config  # noqa: E402
from aidaily.dedup import units_from_result  # noqa: E402
from aidaily.l3 import build_events  # noqa: E402
from aidaily.llm import Router  # noqa: E402
from aidaily.llm.router import providers_from_env  # noqa: E402
from aidaily.pipeline import run_dedup_stage, select_for_digest  # noqa: E402
from aidaily.registry import apply_overrides, load_overrides, load_registry  # noqa: E402
from aidaily.rubric import band, score_events  # noqa: E402


async def main() -> int:
    keys_path = os.environ.get("KEYS", "")
    rows: list[dict] = []
    if keys_path and Path(keys_path).exists():
        rows = [r for r in json.loads(Path(keys_path).read_text(encoding="utf-8"))
                if r.get("model")]

    cfg = load_config(env={})
    sources, _ = apply_overrides(load_registry(), load_overrides())
    items = read_items_jsonl(str(ROOT / "data" / "raw" / "items.jsonl"))
    stage = run_dedup_stage(items, cfg)
    units = units_from_result(stage.result, stage.window.kept)
    events, _ = await build_events(units, None)
    print(f"  事件 {len(events)}")

    before, _ = select_for_digest(events, stage, sources, cfg)
    print(f"  公式选出 {len(before)} 条")

    if not rows:
        print("  跳过 rubric：未提供可用密钥（KEYS 未设置）")
        return 0

    pool_n = cfg.output.deep.max_items * 2
    pool, _ = select_for_digest(events, stage, sources, cfg, pool_only=pool_n)
    print(f"  候选池 {len(pool)} 条")

    async with httpx.AsyncClient(timeout=180) as http:
        router = Router(providers_from_env(env={"RELAY_KEYS_JSON": json.dumps(rows)}), http)
        result = await score_events(
            pool, router, batch_size=cfg.llm.batch_size.rubric,
            concurrency=cfg.llm.batch_size.rubric_concurrency,
        )

    print(f"  {result.coverage}")
    print(f"  标准来源: {result.profile_source}")
    if result.failed_batches:
        print(f"  失败批次: {result.failed_batches}")
    if result.unknown_ids:
        print(f"  模型编造的 id: {result.unknown_ids}（已丢弃）")
    if not result.scores:
        print("  ❌ 没有拿到任何分数")
        return 1

    after, _ = select_for_digest(events, stage, sources, cfg, rubric_scores=result.scores)

    print()
    print("  分数分布:")
    from collections import Counter
    dist = Counter(band(v) for v in result.scores.values())
    for k, v in dist.most_common():
        print(f"    {k:6} {v:3} 条")

    print()
    print("  公式榜首 → rubric 榜首:")
    print(f"    前: {before[0].title[:58] if before else '—'}")
    print(f"    后: {after[0].title[:58] if after else '—'}")

    before_ids = [e.event_id for e in before]
    after_ids = [e.event_id for e in after]
    moved_in = [i for i in after_ids if i not in before_ids]
    moved_out = [i for i in before_ids if i not in after_ids]
    print()
    print(f"  rubric 让 {len(moved_in)} 条进入 / {len(moved_out)} 条离开前 {len(after)} 名")
    for e in after[:5]:
        raw = result.scores.get(e.event_id)
        tag = f"{raw:.0f}分 {band(raw)}" if raw is not None else "未打分"
        print(f"    [{tag:10}] {e.title[:52]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
