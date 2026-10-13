"""Analysis: turn events into facts, inferences, opinions and uncertainties.

Two structural choices carry the anti-hallucination guarantee:

* **The model returns text only -- never a link.** Links are attached afterwards from our
  own records, so a fabricated URL cannot reach the digest even if the model tries.
* **The three epistemic buckets are separate fields.** A single "summary" string makes it
  impossible to tell a reported fact from the model's own guess, which is precisely the
  failure mode a news digest must avoid. Keeping them apart also lets the renderer label
  them differently for the reader.

When there is no router, or the budget is gone, `fallback_insight` produces a
rule-based entry from the source's own summary. The digest then says so in `warnings`
instead of pretending the analysis ran.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable

from .llm import LLMError, LLMUnavailable, Router
from .models import Event, NormalizedItem

SYSTEM_PROMPT = (
    "你是 AI 日报的编辑。你只能使用给定的材料，**不得补充任何材料之外的信息**。\n"
    "严格区分四类内容：\n"
    "- facts：材料中直接陈述的事实，每条一句话，不加形容词。\n"
    "- inferences：你基于事实的推断。必须能被材料支持，措辞上体现推断性质。\n"
    "- opinions：评价性判断，不得伪装成事实。\n"
    "- uncertainties：材料没有讲清楚、无法确认的点。宁多勿少。\n"
    "硬性禁止：\n"
    "1. 不得写出任何链接（链接由程序回填）。\n"
    "2. 不得写出材料中没有的日期、数字、模型名或公司名。\n"
    "3. 材料里没有的信息，宁可不写，也不要推测填充。\n"
    "只输出 JSON，不要 markdown 代码块或解释。"
)

USER_TEMPLATE = """以下是关于同一事件的材料。请据此产出 JSON。

【事件】{event_title}
【来源数】{source_count}
【材料】
{materials}

只输出如下 JSON：
{{
  "title": "一句话概括（不超过 30 字，不加链接）",
  "facts": ["事实1", "事实2"],
  "inferences": ["推断1"],
  "opinions": [],
  "uncertainties": ["不确定点1"],
  "key_points": ["要点1", "要点2"]
}}"""


@dataclass
class EventInsight:
    event_id: str
    title: str
    facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    opinions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    #: True when produced without the model (no router, or budget exhausted)
    rule_based: bool = False


def fallback_insight(event: Event, members: list[NormalizedItem]) -> EventInsight:
    """What the digest says when the model is unavailable: the source's own words.

    Deliberately dull. The point is that a degraded digest is still *accurate* -- it
    quotes the feed instead of inventing a summary.
    """
    primary = next((m for m in members if m.item_id == event.primary_item_id), None)
    if primary is None and members:
        primary = members[0]
    if primary is None:
        return EventInsight(event_id=event.event_id, title=event.title, rule_based=True)

    body = (primary.summary or primary.content_text or "").strip()
    facts = [body[:300]] if body else [primary.title]
    return EventInsight(
        event_id=event.event_id,
        title=primary.title[:120],
        facts=facts,
        uncertainties=["本次未调用大模型，内容为来源原文摘录"] if True else [],
        rule_based=True,
    )


def _materials(members: list[NormalizedItem], per_item: int = 700) -> str:
    blocks: list[str] = []
    for idx, item in enumerate(members[:6], start=1):
        when = item.published_at.strftime("%Y-%m-%d %H:%M UTC") if item.published_at else "时间未知"
        body = (item.summary or item.content_text or "").strip()[:per_item]
        blocks.append(f"[材料{idx}] 来源={item.source_id} 时间={when}\n标题：{item.title}\n内容：{body}")
    return "\n\n".join(blocks)


async def analyze_event(
    router: Router, event: Event, members: list[NormalizedItem]
) -> EventInsight:
    prompt = USER_TEMPLATE.format(
        event_title=event.title[:200],
        source_count=len(event.source_ids),
        materials=_materials(members),
    )
    got = await router.complete_json(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=900,
        purpose="summarize_event",
    )
    if not isinstance(got, dict):
        raise LLMError("analysis did not return an object")

    def strings(key: str, cap: int) -> list[str]:
        rows = got.get(key) or []
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        for row in rows[:cap]:
            text = str(row).strip()
            # A link in the body means the model ignored the contract; drop the line
            # rather than publish a link we cannot vouch for.
            if text and "http://" not in text and "https://" not in text:
                out.append(text[:400])
        return out

    return EventInsight(
        event_id=event.event_id,
        title=str(got.get("title") or event.title)[:200],
        facts=strings("facts", 8),
        inferences=strings("inferences", 5),
        opinions=strings("opinions", 4),
        uncertainties=strings("uncertainties", 5),
        key_points=strings("key_points", 6),
    )


async def analyze_events(
    events: Iterable[Event],
    by_id: dict[str, NormalizedItem],
    router: Router | None,
    *,
    limit: int = 40,
    concurrency: int = 3,
) -> tuple[dict[str, EventInsight], list[str]]:
    """Analyse the top `limit` events. Returns (insights, warnings).

    Only the top events get model attention: analysing all ~250 would burn the budget to
    polish entries nobody scrolls to, and the brief only needs the head of the list.
    """
    warnings: list[str] = []
    targets = [e for e in events][:limit]
    insights: dict[str, EventInsight] = {}

    def members_of(event: Event) -> list[NormalizedItem]:
        return [by_id[i] for i in event.member_item_ids if i in by_id]

    if router is None:
        warnings.append("未配置大模型，本期所有条目为来源原文摘录（规则降级）")
        for event in targets:
            insights[event.event_id] = fallback_insight(event, members_of(event))
        return insights, warnings

    sem = asyncio.Semaphore(concurrency)
    degraded = 0

    async def run(event: Event) -> None:
        nonlocal degraded
        async with sem:
            try:
                insights[event.event_id] = await analyze_event(router, event, members_of(event))
            except (LLMError, LLMUnavailable) as exc:
                degraded += 1
                if degraded == 1:
                    warnings.append(f"部分条目降级为原文摘录（首次失败：{type(exc).__name__}）")
                insights[event.event_id] = fallback_insight(event, members_of(event))

    await asyncio.gather(*(run(e) for e in targets))

    if degraded:
        warnings.append(f"{degraded}/{len(targets)} 个事件降级为规则摘录")
    if len(list(events)) > limit:
        warnings.append(f"仅分析前 {limit} 个事件，其余未做模型处理")
    return insights, warnings
