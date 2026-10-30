
"""Two reports of one event, decided pair by pair.

## Why this exists

`merge_llm.merge_duplicates` asks the model to group a bucket of events. That works when the
wording is close. It fails on the shape that actually reaches the page:

    #01  Mistral 发布 1 万亿参数 Mistral Large 4 权重
    #02  Mistral 发布万亿参数模型权重以应对网络安全

    #06  Anthropic 研究：专家 86% 采纳 AI 随机偏好
    #07  Anthropic研究：专家误认AI随机观点为自身见解

Measured 2026-10-30: both pairs published as separate entries. One named the product, the other
described it; the bucket the model saw never asked "are these two the same launch".

## What this does instead

It does not ask the model to search. A cheap lexical pass finds pairs that share a **rare entity**
-- a name that appears in at most a handful of today's events -- and then a yes/no question is
put to the model for each pair. Two questions, two answers, no grouping to get wrong.

The lexical pass is recall; the model is precision. Neither is trusted alone: entity overlap across
two days produced 207 candidate pairs of which almost none were duplicates, so nothing merges
without the model saying so.
"""

from __future__ import annotations

import asyncio
import re

from .models import Event

#: Latin-script names: `Mistral`, `Anthropic`, `Gemini`, `Nemotron`.
_ENTITY = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{2,}")

#: Words that appear in half the headlines and identify nothing.
_STOP = frozenset(
    """
    ai api app apps ai 的 与 和 the and for with from that this new launches launch release
    releases released announces announced update updates model models open study research
    """.split()
)

#: How many events may share a name before it stops being distinguishing.
RARE_LIMIT = 4

#: A hard ceiling on questions per issue. Two hundred events produce far fewer shareable names.
MAX_PAIRS = 50

PAIR_MAX_TOKENS = 300
PAIR_TIMEOUT_SECONDS = 90
PAIR_CONCURRENCY = 4

SYSTEM = """你是 AI 资讯编辑的合并裁判。

给你两条同一天的资讯标题与摘要，判断它们是否在报道**同一件事**。

判为同一件事（same=true）：
- 同一家公司发布/更新同一个产品或模型，只是措辞不同
- 同一篇论文、同一项实验、同一个基准结果
- 一条点名产品、另一条描述这个产品（例如「Mistral Large 4」与「万亿参数模型」指同一次发布）
- 同一场发布会、同一份财报、同一起诉讼

判为不同的事（same=false）：
- 同一家公司的两个不同产品、两次不同发布
- 同一产品的不同事实（发布 vs 涨价 vs 被起诉），但**同一天同一发布的多角度报道算同一件**
- 只是共享一个公司名或一个泛词

拿不准时判 false，并把理由写清楚。

只输出 JSON：{"same": true/false, "why": "不超过 40 字"}"""

USER = """标题 A：{a}
摘要 A：{a_fact}

标题 B：{b}
摘要 B：{b_fact}"""


def _entities(title: str) -> set[str]:
    out: set[str] = set()
    for word in _ENTITY.findall(title or ""):
        token = word.lower().strip(".-")
        if len(token) < 3 or token in _STOP:
            continue
        out.add(token)
    return out


def _fact(event: Event, limit: int = 120) -> str:
    facts = (event.unique_facts or {}).get("facts")
    if isinstance(facts, list) and facts:
        return str(facts[0])[:limit]
    return ""


def candidate_pairs(events: list[Event], *, limit: int = MAX_PAIRS) -> list[tuple[int, int]]:
    """Index pairs that share a name rare enough to mean something.

    A name carried by five events is not evidence of anything; this keeps only names carried by
    at most `RARE_LIMIT` events, which is what makes the pairing cheap enough to spend a model
    call on each one.
    """
    holders: dict[str, list[int]] = {}
    for index, event in enumerate(events):
        for token in _entities(event.title):
            holders.setdefault(token, []).append(index)

    seen: set[tuple[int, int]] = set()
    for token, indexes in holders.items():
        if len(indexes) < 2 or len(indexes) > RARE_LIMIT:
            continue
        for i in range(len(indexes)):
            for j in range(i + 1, len(indexes)):
                seen.add((indexes[i], indexes[j]))
    return sorted(seen)[:limit]


def merge_into(keeper: Event, other: Event) -> None:
    """Fold `other` into `keeper` without losing anything it carried."""
    for mid in other.member_item_ids:
        if mid not in keeper.member_item_ids:
            keeper.member_item_ids.append(mid)
    for sid in other.source_ids:
        if sid not in keeper.source_ids:
            keeper.source_ids.append(sid)
    for url in other.all_urls:
        if url not in keeper.all_urls:
            keeper.all_urls.append(url)

    facts = keeper.unique_facts if isinstance(keeper.unique_facts, dict) else {}
    absorbed = list(facts.get("merged_titles") or [])
    for title in [other.title, *((other.unique_facts or {}).get("merged_titles") or [])]:
        if title and title not in absorbed:
            absorbed.append(title)
    facts["merged_titles"] = absorbed
    keeper.unique_facts = facts


async def review_pairs(
    events: list[Event],
    router,
    *,
    limit: int = MAX_PAIRS,
    concurrency: int = PAIR_CONCURRENCY,
    timeout_s: float = PAIR_TIMEOUT_SECONDS,
) -> tuple[list[Event], dict]:
    """Return the list with same-event pairs folded together.

    Never raises. On any failure the input survives: a missed merge costs a duplicate line, a
    wrong merge costs a story.
    """
    report = {"pairs": 0, "asked": 0, "merged": 0, "failed": False}
    if router is None or len(events) < 2:
        report["failed"] = router is None
        return list(events), report

    pairs = candidate_pairs(events, limit=limit)
    report["pairs"] = len(pairs)
    if not pairs:
        return list(events), report

    parent = list(range(len(events)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()

    async def one(i: int, j: int) -> None:
        a, b = events[i], events[j]
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": USER.format(
                    a=a.title[:120],
                    a_fact=_fact(a),
                    b=b.title[:120],
                    b_fact=_fact(b),
                ),
            },
        ]
        async with sem:
            try:
                got = await router.complete_json(
                    messages, temperature=0.0, max_tokens=PAIR_MAX_TOKENS
                )
            except Exception:
                async with lock:
                    report["failed"] = True
                return
        async with lock:
            report["asked"] += 1
            if isinstance(got, dict) and got.get("same") is True:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra

    async def guarded(i: int, j: int) -> None:
        async with sem:
            pass
        await one(i, j)

    try:
        tasks = [asyncio.create_task(guarded(i, j)) for i, j in pairs]
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, timeout_s))
        for task in pending:
            task.cancel()
        if pending:
            report["failed"] = True
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception:
        report["failed"] = True

    groups: dict[int, list[int]] = {}
    for index in range(len(events)):
        groups.setdefault(find(index), []).append(index)

    out: list[Event] = []
    for root in sorted(groups):
        members = groups[root]
        keeper = events[members[0]]
        for index in members[1:]:
            merge_into(keeper, events[index])
            report["merged"] += 1
        out.append(keeper)
    return out, report
