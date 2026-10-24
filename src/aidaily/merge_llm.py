"""One extra LLM pass that merges the same story reported in different words.

## The failure, measured

The 2026-10-24 issue carried three entries that were one story:

  01  Moonshot AI 推出 3 万亿参数 Kim K3.1 Pro
  02  Kimi 3.1 Pro 推出 Fable-5.1 开放权重与高速 API
  06  全球最大 3 万亿参数开源AI模型上线

Every deterministic signal missed it:

  title similarity   0.31 / 0.30 / 0.18   (the merge threshold is 0.85)
  same_message       False on all three pairs
  designation        only the second title names a model

The third headline never says "Kimi" at all -- it calls it "全球最大开源模型". No rule over
the text can know that is the same launch; it requires knowing what happened that day.

## Why this pass and not the existing judge

`l3.judge_cluster` decides whether the items *inside* one candidate cluster describe one event.
It cannot merge across clusters, and these three arrived in three separate clusters because
the signals that form clusters are the same signals that failed here.

## Why duplicates should merge rather than be dropped

The user was explicit: a story reported by several outlets is *one* entry with multi-source
corroboration, not three entries. Merging unions the source ids, which raises
`independent_source_count` -- the field that says "this many outlets independently carry this".
Three separate entries claiming the same thing is the worst of both: repetition for the reader
and no corroboration signal for the ranking.

## Fallback

When the model is unavailable or answers badly, every event survives unchanged. This pass can
only merge; it never drops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LLMError, LLMUnavailable, Router
from .models import Event

SYSTEM = (
    "你是 AI 日报的编辑，负责把同一件事的多篇报道合并。\n"
    "\n"
    "输入是一批新闻标题，每条有 id。请找出**报道同一件事**的条目，把它们分到一组。\n"
    "\n"
    "判定标准：\n"
    "- 同一款模型/产品的发布，即使标题措辞完全不同（一个写产品名，一个写「全球最大开源模型」）\n"
    "- 同一笔融资、同一起安全事故、同一份报告\n"
    "\n"
    "不是同一件事的例子：\n"
    "- 同一家公司的两个不同产品发布\n"
    "- 同一款模型的发布 vs 它的评测/教程/跑分\n"
    "- 同一主题的两条不同新闻（两家公司各自发模型）\n"
    "\n"
    "输出要求：\n"
    "- 只输出 JSON，形如 "
    '{"groups": [{"ids": ["a", "b"], "why": "都是 Kimi K3.1 Pro 发布"}]}\n'
    "- 只列出至少有 2 条的组；不构成重复的条目**不要**出现在输出里\n"
    "- 每个 id 必须原样照抄输入里给的，不要改写、不要新增\n"
    "- 不要输出任何解释性文字",
)

USER = """# 待识别的标题（{count} 条）

{items}

# 任务

找出报道同一件事的条目，输出 JSON：
{{"groups": [{{"ids": ["a", "b"], "why": "合并理由"}}]}}
"""

#: Output budget. Reasoning models spend tokens before answering; 2000 leaves room for both.
GROUP_MAX_TOKENS = 2000

#: Titles per call. A batch that is too large makes the comparison quadratic in the model head
#: and the output long; 40 keeps one call under a few seconds.
BATCH = 40


@dataclass
class MergeResult:
    events: list[Event]
    merged_groups: int = 0
    merged_events: int = 0
    calls: int = 0
    failed: bool = False
    examples: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.failed:
            return "未运行（模型不可用）"
        if not self.merged_groups:
            return "无重复"
        return f"{self.merged_groups} 组，合并 {self.merged_events} 条"

def _listing(events):
    return "\n".join(f"- id={e.event_id} | {e.title[:160]}" for e in events)


def _merge_into(target, absorbed):
    """Fold absorbed into target, keeping every source and URL.

    The title keeps the target own wording: re-titling a merged event would decouple the
    headline from the score computed for it. The absorbed titles are recorded so the page
    can show what the other outlets called it.
    """
    for other in absorbed:
        for member in other.member_item_ids:
            if member not in target.member_item_ids:
                target.member_item_ids.append(member)
        for source in other.source_ids:
            if source not in target.source_ids:
                target.source_ids.append(source)
        for url in other.all_urls:
            if url not in target.all_urls:
                target.all_urls.append(url)

    merged_titles = list((target.unique_facts or {}).get("merged_titles") or [])
    for other in absorbed:
        if other.title and other.title != target.title and other.title not in merged_titles:
            merged_titles.append(other.title)
    if merged_titles:
        target.unique_facts = dict(target.unique_facts or {})
        target.unique_facts["merged_titles"] = merged_titles

    target.independent_source_count = len(set(target.source_ids))
    return target


async def merge_duplicates(events, router, *, batch=BATCH):
    """Group events that report one story. Never raises; a failure returns the input.

    Only merges. An event the model did not mention survives untouched, so a partial answer
    costs nothing and a wrong answer costs a merge rather than a lost story.
    """
    result = MergeResult(events=list(events))
    if router is None or len(events) < 2:
        result.failed = router is None
        return result

    by_id = {e.event_id: e for e in events}
    absorbed = set()

    size = max(2, batch)
    for start in range(0, len(events), size):
        chunk = events[start:start + size]
        if len(chunk) < 2:
            continue
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(count=len(chunk), items=_listing(chunk))},
        ]
        try:
            got = await router.complete_json(
                messages, temperature=0.0, max_tokens=GROUP_MAX_TOKENS
            )
            result.calls += 1
        except Exception:
            result.failed = True
            continue

        if not isinstance(got, dict):
            result.failed = True
            continue

        for group in got.get("groups") or []:
            if not isinstance(group, dict):
                continue
            ids = [str(i) for i in (group.get("ids") or []) if str(i) in by_id]
            ids = [i for i in ids if i not in absorbed]
            if len(ids) < 2:
                continue
            keep = by_id[ids[0]]
            rest = [by_id[i] for i in ids[1:]]
            _merge_into(keep, rest)
            absorbed.update(ids[1:])
            result.merged_groups += 1
            result.merged_events += len(ids) - 1
            if len(result.examples) < 5:
                result.examples.append({
                    "kept": keep.title[:80],
                    "merged": [e.title[:60] for e in rest],
                    "why": str(group.get("why") or "")[:80],
                })

    result.events = [e for e in events if e.event_id not in absorbed]
    return result
