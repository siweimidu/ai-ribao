"""Cross-day deduplication by model, over the whole 7-day window.

## What the deterministic path misses

`history.find_repeat` compares fingerprints and title similarity inside a window. Measured
2026-10-25 against the previous six issues:

    1.00  Perplexity 在 Computer 技能市场上线开源技能 /impeccable
    1.00  OpenAI CEO：最强内部模型暂难开源
    1.00  Convovo 研究：Grok 4.7 强制选择时 92% 推荐共和党
    0.71  Kling 4.0 在 fal 上线并向所有客户开放 API
            [10-24] 可灵 Kling 4.0 上线 fal 平台并开放 API
    0.69  Cohere 发布 Rerank 5 企业检索重排模型，分 Pro 与 Fast 两档
            [10-22] Cohere 发布 Rerank 5 重排序模型
    0.61  Cognition 推出 Devin Oncall，协助诊断和解决生产事故
            [10-24] Cognition 推出焕新版 Devin Desktop

Fourteen of 120 entries repeated something from the previous six issues. Three were
byte-identical -- the fingerprint path should have caught those and did not, because the
history file only records what was published and a re-run rewrites it.

The rest differ by vocabulary: 可灵/Kling, 上线/推出, one names the platform and the other the
model. A similarity threshold tuned to catch those would also merge two genuinely different
releases from one vendor.

So the judgement goes to the model, which is what the instruction asks for:
「去重七天内所有资讯，去重交给llm的API来做」.

## What this pass does NOT do

It never drops an event the model did not name. An unmentioned event survives, so a partial
answer costs nothing and a wrong answer costs one wrongly-hidden story rather than a lost one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .models import Event
from .unfiltered import protects

SYSTEM = """你是 AI 日报的编辑。任务是找出「今天这条与过去某天那条讲的是同一件事」。

## 判据

同一件事指的是：同一个主体、同一个动作、指向同一个结果。

  同一款模型的发布，即使一处写中文名一处写英文名
    可灵 Kling 4.0 上线 fal 平台并开放 API   ←→   Kling 4.0 在 fal 上线并向所有客户开放 API
  同一笔融资、同一起事故、同一份报告
  同一条消息的简版与详版

不是同一件事：

  同一家公司的两个不同产品
    可灵 Kling 4.0 全量上线      ←→   Cognition 推出 Devin Oncall
  同一款模型的发布 与 它的评测/教程
  两家公司各自发布同类产品
    蚂蚁 inclusionAI 开源 Ming-3.0-tts  ←→  Hugging Face 发布 Carbon-X
  同一产品的两个不同动作
    Cohere 发布 Rerank 5        ←→   Cohere Rerank 5 降价

## 拿不准的时候

**判为不重复。**

误判重复会让一条真新闻消失，读者永远不知道它发生过；
漏判只是重复一次，读者能自己看出来。

## 输出

只输出 JSON，不要 markdown，不要解释：

  {{"duplicates": [{{"today": "今天的 id", "earlier": "早先那条的 id", "why": "为什么是同一件事"}}]}}

没有重复就输出 {{"duplicates": []}}。
ids 必须原样照抄输入里给的。
"""

USER = """# 今天的条目

{today}

# 过去 7 天已发布的条目

{earlier}

# 任务

找出今天的条目里，与过去某天讲同一件事的，输出 JSON：
{{"duplicates": [{{"today": "id", "earlier": "id", "why": "理由"}}]}}
"""

#: How many earlier headlines to put in one prompt.
#:
#: Seven days at ~120 entries is ~700 lines. Sending all of them on every call would make the
#: prompt enormous and the comparison unreliable; the window is chunked and each chunk
#: compared against the whole of today.
EARLIER_CHUNK = 120

#: Output budget for a JSON list of pairs. Reasoning models spend tokens before answering.
DEDUP_MAX_TOKENS = 2000

#: Hard ceiling on the pass, so a slow provider costs the dedup rather than the issue.
DEDUP_TIMEOUT_SECONDS = 240

#: Concurrent chunk comparisons.
DEDUP_CONCURRENCY = 3

#: How many independent sources it takes for a story to be exempt from this drop.
#:
#: The check below is a model reading today headlines against the last seven days of
#: published ones. It is a judgement on wording, and wording is exactly what a big story
#: has twenty different versions of.
#:
#: Measured 2026-10-28: the 06:48 build of the issue dropped Genie 4, a story carried by
#: 20 independent sources -- the DeepMind blog, four aihot feeds, juya, the Verge,
#: TechCrunch, Hacker News. Nothing named Genie had been published in the previous seven
#: days, so there was nothing for it to duplicate. The 14:51 rebuild kept it and it
#: published at #03. A story corroborated that widely is not a duplicate of anything, and
#: an LLM guess must not be able to delete it.
MIN_SOURCES_TO_PROTECT = 3


@dataclass
class CrossDayResult:
    events: list[Event]
    dropped: int = 0
    calls: int = 0
    chunks: int = 0
    failed: bool = False
    examples: list[dict] = field(default_factory=list)
    #: Events the model called duplicates but which survived on source count.
    protected: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.failed:
            return "未运行（模型不可用）"
        if not self.dropped:
            return "无重复"
        kept = f"，保护 {len(self.protected)} 条多源报道" if self.protected else ""
        return f"剔除 {self.dropped} 条（与 7 天内重复）{kept}"


def _listing(events, prefix):
    return "\n".join(f"- id={prefix}{i} | {e.title[:120]}" for i, e in enumerate(events))


async def drop_cross_day_duplicates(
    events,
    earlier,
    router,
    *,
    chunk=EARLIER_CHUNK,
    timeout_s=DEDUP_TIMEOUT_SECONDS,
    concurrency=DEDUP_CONCURRENCY,
):
    """Remove today's events that repeat something published in the last seven days.

    `earlier` is a list of (date, title) pairs from the published archive. Only titles are
    sent -- the model needs to recognise the story, not read it.

    Never raises. On failure every event survives: a repeated story is a smaller defect than
    a story that silently never appears.
    """
    import asyncio

    result = CrossDayResult(events=list(events))
    if router is None or not events or not earlier:
        result.failed = router is None
        return result

    today_block = _listing(events, "T")
    earlier_chunks = [earlier[i:i + chunk] for i in range(0, len(earlier), chunk)]
    result.chunks = len(earlier_chunks)

    removed = set()
    lock = asyncio.Lock()

    async def one(piece):
        lines = "\n".join(f"- id=E{j} | {d} | {t[:120]}" for j, (d, t) in enumerate(piece))
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(today=today_block, earlier=lines)},
        ]
        try:
            got = await router.complete_json(
                messages, temperature=0.0, max_tokens=DEDUP_MAX_TOKENS
            )
        except Exception:
            async with lock:
                result.failed = True
            return

        if not isinstance(got, dict):
            async with lock:
                result.failed = True
            return

        async with lock:
            result.calls += 1
            for row in got.get("duplicates") or []:
                if not isinstance(row, dict):
                    continue
                today_id = str(row.get("today") or "")
                if not today_id.startswith("T"):
                    continue
                try:
                    index = int(today_id[1:])
                except ValueError:
                    continue
                if not (0 <= index < len(events)) or index in removed:
                    continue
                # **Never delete an item from a source the user put on the no-filter list.**
                #
                # 「这些消息只能去重并标注多源验证，不能删除，不能删除任何一条」. Merging is
                # still allowed and still happens upstream; this stage only decides deletion,
                # and for those sources the answer is always no.
                #
                # Measured 2026-10-28: Genie 4 arrived from juya, was deleted here, and the
                # issue published without the biggest story of the day.
                protected_by_source = protects(events[index].source_ids)
                sources = len(set(events[index].source_ids or ()))
                if protected_by_source or sources >= MIN_SOURCES_TO_PROTECT:
                    if len(result.protected) < 6:
                        result.protected.append({
                            "kept": events[index].title[:70],
                            "sources": sources,
                            "named_source": protected_by_source,
                            "why": str(row.get("why") or "")[:60],
                        })
                    continue
                removed.add(index)
                if len(result.examples) < 6:
                    result.examples.append({
                        "dropped": events[index].title[:70],
                        "why": str(row.get("why") or "")[:70],
                    })

    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(piece):
        async with sem:
            await one(piece)

    try:
        tasks = [asyncio.create_task(guarded(p)) for p in earlier_chunks]
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, timeout_s))
        for task in pending:
            task.cancel()
        if pending:
            result.failed = True
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception:
        result.failed = True

    result.dropped = len(removed)
    result.events = [e for i, e in enumerate(events) if i not in removed]
    return result