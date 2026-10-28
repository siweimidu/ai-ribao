"""Re-judge already-published issues with the model, and remove what is not AI news.

## Why a repair tool exists at all

The relevance gate is a regex (`focus.py`). On 2026-10-28 that regex was broken -- `rag`
matched `average`, `cline` matched `declined` -- so stories with no AI subject were
published, and 39 of 82 rows carried a perfect relevance score. Fixing the regex stops the
next issue from repeating it; it does not clean the issues already on disk, and rewriting
published data by hand is how an archive stops being trustworthy.

So this asks the model the question the reader is actually asking: *is this story about AI*
at all? It prints what it would remove and changes nothing unless `--apply` is given.

## Why several dates in one run

The workflow holds a concurrency lock, and GitHub keeps only one *pending* run per group:
dispatching six dates at once cancelled five of them. Taking the dates as arguments means
one job, one router, one rebuild at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Ids per call. Small enough that the model attends to every title, large enough that an
#: issue costs four calls rather than ninety.
BATCH = 25

SYSTEM = (
    "你是 AI 日报的审稿人。你会读到一批新闻标题。\n"
    "你的唯一任务：找出**与人工智能无关**的那些。\n"
    "\n"
    "**最高优先级的硬规则：标题点名了 AI 公司、AI 模型或 AI 产品，一律算相关。**\n"
    "包括 OpenAI、Anthropic、DeepSeek、Google/Gemini、Meta、xAI、Mistral、Qwen/通义、\n"
    "Qoder、Claude、Llama、OlmoEarth、Muse、Codex、Cursor、Copilot、Kimi、GLM/智谱、\n"
    "MiniMax、豆包、阶跃星辰、腾讯元宝。哪怕它同时在讲财报、股价、版本更新或裁员，\n"
    "也**必须保留**。\n"
    "\n"
    "只有**完全没有 AI 主体**时才判为无关：\n"
    "- 政治、选举、外交、贸易谈判（不含 AI 议题）；\n"
    "- 纯金融行情、股价；\n"
    "- 体育、娱乐、地方政务、天气；\n"
    "- 与 AI 无关的普通软硬件更新（Linux 发行版、Raspberry Pi、iMac、Markdown 渲染等）；\n"
    "- 只是正文偶然出现 AI 字样，但主体是别的事。\n"
    "\n"
    "\n"
    "拿不准就**保留**（不要列入结果）—— 漏删一条无关新闻，比错删一条真新闻好。\n"
    "只输出 JSON：{\"off_topic\": [\"id1\", \"id2\"]}，不要解释。"
)


async def _judge(router, rows: list[tuple[str, str]]) -> set[str]:
    listing = "\n".join(f"- id={rid} | {title[:160]}" for rid, title in rows)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"共 {len(rows)} 条：\n\n{listing}"},
    ]
    response = await router.complete(messages, temperature=0.0, max_tokens=2000)
    text = (getattr(response, "text", "") or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return set()
    try:
        doc = json.loads(text[start : end + 1])
    except ValueError:
        return set()
    ids = doc.get("off_topic")
    if not isinstance(ids, list):
        return set()
    sent = {rid for rid, _ in rows}
    return {str(i) for i in ids if str(i) in sent}


async def repair_one(router, date: str, apply: bool) -> int:
    path = ROOT / "data" / "digests" / f"{date}.json"
    if not path.exists():
        print(f"  {date}: 没有 {path.name}，跳过")
        return 2
    doc = json.loads(path.read_text(encoding="utf-8"))
    events = doc["digest"]["top_events"]
    insights = doc.get("insights") or {}

    def title_of(e):
        return (insights.get(e["event_id"]) or {}).get("title") or e.get("title") or ""

    rows = [(e["event_id"], title_of(e)) for e in events]
    print(f"  {date}: 待审 {len(rows)} 条")

    off: set[str] = set()
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        try:
            got = await _judge(router, chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"    第 {i // BATCH + 1} 批失败 {type(exc).__name__}")
            continue
        off |= got
        print(f"    第 {i // BATCH + 1} 批：{len(got)} 条判为无关")

    if not off:
        print(f"  {date}: 模型认为全部与 AI 相关，不改动")
        return 0

    print(f"  {date}: 判为无关 {len(off)} 条：")
    for e in events:
        if e["event_id"] in off:
            print("    · " + title_of(e)[:74])

    if not apply:
        return 0

    kept = [e for e in events if e["event_id"] not in off]
    doc["digest"]["top_events"] = kept
    for name, ids in list((doc.get("sections") or {}).items()):
        doc["sections"][name] = [i for i in ids if i not in off]
    for table in ("insights", "factcheck"):
        block = doc.get(table)
        if isinstance(block, dict):
            for rid in off:
                block.pop(rid, None)
    counts = doc["digest"].get("counts")
    if isinstance(counts, dict) and isinstance(counts.get("events"), int):
        counts["events"] = len(kept)

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  {date}: 已写回 {len(events)} → {len(kept)} 条")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dates", nargs="+", help="YYYY-MM-DD，可给多个")
    ap.add_argument("--apply", action="store_true", help="写回 JSON（默认只报告）")
    args = ap.parse_args()

    # Reuse the real provider stack rather than a second copy of the env handling.
    sys.path.insert(0, str(ROOT / "src"))
    from aidaily.__main__ import _build_router
    import argparse as _ap

    router, warnings, http = _build_router(_ap.Namespace(no_llm=False, relay_keys=None))
    for w in warnings:
        print("  " + w)
    if router is None:
        print("没有可用的模型，退出")
        return 3

    try:
        for date in args.dates:
            await repair_one(router, date, args.apply)
            print("")
    finally:
        if http is not None:
            await http.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))