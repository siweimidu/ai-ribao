"""Does key rotation actually rotate?

Three things, in order of how much they matter:

1. **Fall-through.** Put deliberately broken credentials first and confirm the router
   reaches a working one and still returns an analysis. This is the user's actual
   requirement -- "我一个密钥的免费额度耗完不能自动切下一个" -- and a provider count proves
   nothing about it.
2. **Provider count.** 111 resolved rows must become 111 providers, including the thirteen
   that share one host. The old code deduped on `baseUrl` and kept one, so this is the
   regression guard.
3. **A real call** with the fallback chain disabled, to confirm the model actually answers
   with Chinese rather than only that the transport worked.
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

from aidaily.analyze import analyze_event  # noqa: E402
from aidaily.llm import Router  # noqa: E402
from aidaily.llm.router import providers_from_env  # noqa: E402
from aidaily.models import Event, NormalizedItem  # noqa: E402

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def make_case() -> tuple[Event, list[NormalizedItem]]:
    item = NormalizedItem(
        item_id="i1", source_id="rss:theverge",
        title="OpenAI ships GPT-6 with a new reasoning interface",
        title_norm="openai ships gpt-6", url="https://example.com/a",
        published_at=NOW, fetched_at=NOW, first_seen_at=NOW, updated_at=NOW,
        summary="OpenAI released GPT-6 with a redesigned chat interface and a new "
                "reasoning mode that the company says reduces latency by half.",
        content_text="OpenAI released GPT-6 with a redesigned chat interface and a new "
                     "reasoning mode that the company says reduces latency by half.",
        content_sha256="h", simhash=1, metrics={"points": 300},
    )
    event = Event(
        event_id="e1", title=item.title, member_item_ids=["i1"], primary_item_id="i1",
        source_ids=["rss:theverge"], all_urls=[item.url], independent_source_count=4,
        first_seen_at=NOW, last_updated_at=NOW, published_range=(NOW, NOW),
        evidence_level="multi_source",
    )
    return event, [item]


async def main() -> int:
    keys_path = Path(os.environ.get("KEYS", ""))
    if not keys_path.exists():
        print(f"  找不到密钥文件: {keys_path}")
        return 2
    rows = json.loads(keys_path.read_text(encoding="utf-8"))
    rows = [r for r in rows if r.get("model")]
    print(f"  已解析密钥: {len(rows)} 条")

    # ---- 1. provider count, including same-host rotation -------------------------
    specs = providers_from_env(env={"RELAY_KEYS_JSON": json.dumps(rows)})
    hosts: dict[str, int] = {}
    for s in specs:
        hosts[s.base_url] = hosts.get(s.base_url, 0) + 1
    multi = {h: n for h, n in hosts.items() if n > 1}
    print(f"  provider 数: {len(specs)}   覆盖 {len(hosts)} 个端点")
    print(f"  同端点多密钥（轮换的前提）: {len(multi)} 个端点")
    for h, n in sorted(multi.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {n:3} 把  {h}")
    assert len(specs) == len(rows), "有密钥被丢弃"

    # ---- 2. fall-through from broken credentials ---------------------------------
    # Two impossible credentials ahead of the real ones. If the router gives up instead of
    # rotating, the analysis below will be rule-based and the test fails.
    broken = [
        {"baseUrl": "https://127.0.0.1:9/v1", "key": "sk-broken-1", "model": "x",
         "label": "dead-host"},
        {"baseUrl": "https://api.openai.com/v1", "key": "sk-invalid-key-000",
         "model": "gpt-4o-mini", "label": "invalid-key"},
    ]
    event, items = make_case()
    async with httpx.AsyncClient(timeout=120) as http:
        router = Router(providers_from_env(env={"RELAY_KEYS_JSON": json.dumps(broken + rows)}), http)
        print()
        print(f"  绕过 {len(broken)} 个坏凭据后调用模型 ...")

        # Cap the relay budget: this must succeed within a few rotations, not by trying all.
        router.relay_max_calls = 6
        try:
            insight = await analyze_event(router, event, items)
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 全部失败: {type(exc).__name__}: {str(exc)[:90]}")
            print(f"     标记失效 {len(router.stats.dead)} 个凭据")
            return 1

    print(f"  rule_based = {insight.rule_based}")
    print(f"  title      : {insight.title[:66]}")
    print(f"  facts      : {(insight.facts or ['(空)'])[0][:66]}")
    print()
    stats = router.stats
    print(f"  用过 {len(stats.used)} 个凭据 · 标记失效 {len(stats.dead)} 个 · 失败 {len(stats.failures)} 个")
    for pid, reason in list(stats.dead.items())[:4]:
        print(f"      dead: {pid}  {reason[:74]}")
    rotation_events = [e for e in stats.events if "rate_limited_retry" in str(e)]
    if rotation_events:
        print(f"  限流重试事件 {len(rotation_events)} 次")

    import re
    if insight.rule_based:
        print("  ❌ 降级了 —— 说明没能切到可用密钥")
        return 1
    if not re.search(r"[\u4e00-\u9fff]", insight.title):
        print("  ⚠️ 拿到结果但标题非中文")
        return 1
    print("  ✅ 坏凭据被跳过，轮换到可用密钥并返回中文分析")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
