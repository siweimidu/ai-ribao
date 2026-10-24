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
import re
from pathlib import Path
from dataclasses import dataclass, field

from .llm import LLMError, LLMUnavailable, Router
from .models import Event

#: The dedup rules live in `config/dedup_prompt.md` rather than in this file.
#:
#: They are the specification for a judgement the model makes every run, and they grow every
#: time a merge goes wrong -- the three-headline Kimi case, the roundup trap, and so on.
#: Keeping them in a Markdown file means they can be reviewed and edited as a document instead
#: of as escaped Python string concatenation.
PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "dedup_prompt.md"

#: Used when the file is missing or empty. A packaging mistake must not silently disable
#: dedup -- the fallback states the two rules that matter most.
_FALLBACK = (
    "你是 AI 日报的编辑。找出报道同一件事的标题，把它们分到一组。",
    "同一款模型的发布可以措辞完全不同；同公司的不同产品、发布与评测不能合并。",
    "拿不准就不合并。只输出 JSON：",
    '{"groups": [{"ids": ["a", "b"], "why": "理由"}]}',
)


def load_prompt(path: Path | None = None) -> str:
    """The dedup rules, from disk when available."""
    target = path or PROMPT_PATH
    try:
        text = target.read_text(encoding="utf-8").strip()
    except OSError:
        return "\n".join(_FALLBACK)
    return text or "\n".join(_FALLBACK)


SYSTEM = load_prompt()


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
#: Hard ceiling on the whole pass. A slow provider must cost the merge, not the issue.
#:
#: Measured 2026-10-24: the run that first shipped this pass spent over an hour in `publish`,
#: far past the usual ten to fifteen minutes. The batches were sequential, each asking one
#: model to compare forty headlines against each other -- the most expensive prompt in the
#: pipeline -- and a provider that is merely slow (not failing) has no timeout of its own.
#:
#: Two fixes: batches run concurrently, and the whole pass has a deadline.
MERGE_TIMEOUT_SECONDS = 180

#: How many batches may be in flight. The rubric stage uses a similar number; the relay pool
#: rotates keys per call, so a handful in parallel spreads across accounts.
MERGE_CONCURRENCY = 3


@dataclass
class MergeResult:
    events: list[Event]
    merged_groups: int = 0
    merged_events: int = 0
    calls: int = 0
    failed: bool = False
    #: Groups the model proposed but the plausibility check rejected. Recorded because a high
    #: count means the model is grouping by theme rather than by subject.
    rejected_groups: int = 0
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

    # **The evidence level has to follow the count.**
    #
    # `factcheck` rejects an event that claims `single_source` while carrying more than one
    # independent source, and a merge is exactly how that happens: the source ids grow and
    # the label stays behind. Measured 2026-10-24: one such event blocked the whole issue
    # three times in a row -- `publish failed with exit code 2 after 3 attempts`.
    #
    # Recomputed from the union rather than incremented, so a merge of merges stays correct.
    if target.independent_source_count >= 2:
        target.evidence_level = "multi_source"
    else:
        target.evidence_level = "single_source"
    return target


#: A parameter count, written the ways outlets actually write it.
#:
#: `万亿` / `T` are trillions, `B` is billions. The unit must sit immediately after the digits,
#: so "300 亿美元融资" -- funding, not parameters -- does not match.
_SCALE = re.compile(r"(\d+(?:\.\d+)?)\s*(万亿|[tT]|[bB])(?![a-zA-Z])")


def _scale_key(title):
    """The parameter scale a headline names, rounded to a band, or empty.

    Two outlets write one model as `3万亿` and `2.8T`; a third writes `2800B`. They are the same
    thing stated at different precision, so the key is the count rounded to whole trillions:

        3万亿 -> 3.0T
        2.8T  -> 2.8T  -> rounds to 3
        2800B -> 2.8T  -> rounds to 3

    Rounding is what makes those collide while keeping a 3T and a 4T model apart, which is the
    distinction that matters.
    """
    match = _SCALE.search(title or "")
    if not match:
        return ""
    number, unit = match.group(1), match.group(2).lower()
    try:
        value = float(number)
    except ValueError:
        return ""
    trillions = value if unit in ("万亿", "t") else value / 1000.0
    if trillions < 0.5:
        return ""
    return "scale:%dT" % round(trillions)


def _bucket(events, cap):
    """Group events so that two that share *any* identifying feature share a batch.

    ## Why a partition failed twice

    The first version sliced at a fixed 40. Measured: `3万亿级参数规模 全球最大开源AI模型上新`
    fell on the far side of the cut from three headlines that do name Kimi, survived on its
    own, and the issue carried one launch four times.

    The second version bucketed by a single key. Measured: `Kimi 3.1 Pro 推出 Fable-5.1 开放权重`
    names no parameter count, so it keyed on its entity while the other three keyed on
    `scale:3T` -- and the split came back.

    **A single key cannot express "these belong together".** Two headlines about one launch may
    share an entity, or a parameter count, or neither on their own while a third connects both.
    That is a connected-components problem, so this builds a union-find over every feature a
    title carries.

    ## What a feature is

    * each recognised entity (`kimi`, `moonshot`, `fable-5.1`)
    * the parameter scale when present (`scale:3T`)

    Two events are unioned when they share any one of them. The buckets are the components,
    packed up to `cap`. An event with no features goes to the loose pile.

    This over-groups on purpose: a batch holding two unrelated stories costs nothing, because
    the model decides what to merge. A batch that hides one story from its sibling is the
    failure that shipped four times.
    """
    from .entities import extract_entities

    def features(event):
        try:
            names = {n.lower() for n in extract_entities(event.title)}
        except Exception:
            names = set()
        scale = _scale_key(event.title)
        if scale:
            names = names | {scale}
        return names

    by_feature = {}
    loose = []
    for index, event in enumerate(events):
        feats = features(event)
        if not feats:
            loose.append(event)
            continue
        for feature in feats:
            by_feature.setdefault(feature, []).append(index)

    parent = list(range(len(events)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for indices in by_feature.values():
        for other in indices[1:]:
            union(indices[0], other)

    loose_ids = {id(e) for e in loose}
    components = {}
    for index, event in enumerate(events):
        if id(event) in loose_ids:
            continue
        components.setdefault(find(index), []).append(event)

    buckets = []
    current = []
    for root in sorted(components):
        members = components[root]
        if len(members) > cap:
            if current:
                buckets.append(current)
                current = []
            for start in range(0, len(members), cap):
                piece = members[start:start + cap]
                if len(piece) >= 2:
                    buckets.append(piece)
                else:
                    loose.extend(piece)
            continue
        if len(current) + len(members) > cap:
            buckets.append(current)
            current = []
        current.extend(members)
    if current:
        buckets.append(current)

    for event in loose:
        if not buckets or len(buckets[-1]) >= cap:
            buckets.append([])
        buckets[-1].append(event)

    return [b for b in buckets if len(b) >= 2]


#: Features that make two headlines plausibly the same story.
#:
#: A merge is not free: it unions the source lists, which is how the page claims "N outlets
#: independently carry this". A wrong merge therefore manufactures proof that a story is true.
#:
#: Measured 2026-10-24, the first run with union-find bucketing:
#:
#:     kept  Moonshot AI Releases Kimi K3.1 Pro ...
#:     merged  OpenAI now trains its frontier AI models with no internet access
#:
#:     kept  3万亿级参数规模 全球最大开源AI大模型上新
#:     merged  Anthropic says its unreleased model is both more capable ...
#:
#: Two vendors, two stories, one entry. The model had been handed forty headlines per batch and
#: started grouping by theme ("a lab announces a model") rather than by subject.
#:
#: So every group the model returns is checked before it is applied. Two headlines pass when
#: they share an entity, a parameter scale, or a model designation. Anything else is rejected
#: and the entries stay separate -- a missed merge only repeats a story, while a wrong one
#: invents corroboration.
def _plausible(a: Event, b: Event) -> bool:
    """Whether these two headlines could be one story."""
    from .designation import designation
    from .entities import extract_entities

    def feats(event):
        try:
            names = {n.lower() for n in extract_entities(event.title)}
        except Exception:
            names = set()
        scale = _scale_key(event.title)
        if scale:
            names.add(scale)
        try:
            tag = designation(event.title)
        except Exception:
            tag = None
        if tag:
            names.add("designation:" + str(tag))
        return names

    return bool(feats(a) & feats(b))

async def merge_duplicates(
    events: list[Event],
    router,
    *,
    batch: int = BATCH,
    timeout_s: float = MERGE_TIMEOUT_SECONDS,
    concurrency: int = MERGE_CONCURRENCY,
) -> MergeResult:
    """Group events that report one story. Never raises; a failure returns the input.

    Only merges. An event the model did not mention survives untouched, so a partial answer
    costs nothing and a wrong answer costs a merge rather than a lost story.
    """
    import asyncio

    result = MergeResult(events=list(events))
    if router is None or len(events) < 2:
        result.failed = router is None
        return result

    by_id = {e.event_id: e for e in events}
    absorbed: set[str] = set()
    lock = asyncio.Lock()

    size = max(2, batch)
    chunks = _bucket(events, size)

    async def one(chunk: list[Event]) -> None:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(count=len(chunk), items=_listing(chunk))},
        ]
        try:
            got = await router.complete_json(
                messages, temperature=0.0, max_tokens=GROUP_MAX_TOKENS
            )
        except Exception:  # noqa: BLE001 - the pass is optional by design
            async with lock:
                result.failed = True
            return

        if not isinstance(got, dict):
            async with lock:
                result.failed = True
            return

        async with lock:
            result.calls += 1
            for group in got.get("groups") or []:
                if not isinstance(group, dict):
                    continue
                ids = [str(i) for i in (group.get("ids") or []) if str(i) in by_id]
                ids = [i for i in ids if i not in absorbed]
                if len(ids) < 2:
                    continue
                keep = by_id[ids[0]]
                # **Check the group before applying it.**
                #
                # Measured 2026-10-24: the model returned
                #   [Moonshot AI Releases Kimi K3.1 Pro, OpenAI now trains its frontier ...]
                # and [3万亿级参数规模 ..., Anthropic says its unreleased model ...].
                # Two vendors, two stories, one entry each, with source lists unioned -- exactly
                # how the page would have claimed "2 outlets carry this".
                #
                # Only members sharing a feature with the kept headline are merged; the rest stay
                # separate. A missed merge repeats a story; a wrong one invents proof.
                rest = [by_id[i] for i in ids[1:] if _plausible(keep, by_id[i])]
                if not rest:
                    result.rejected_groups += 1
                    continue
                _merge_into(keep, rest)
                absorbed.update(e.event_id for e in rest)
                result.merged_groups += 1
                result.merged_events += len(ids) - 1
                if len(result.examples) < 5:
                    result.examples.append({
                        "kept": keep.title[:80],
                        "merged": [e.title[:60] for e in rest],
                        "why": str(group.get("why") or "")[:80],
                    })

    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(chunk: list[Event]) -> None:
        async with sem:
            await one(chunk)

    try:
        tasks = [asyncio.create_task(guarded(c)) for c in chunks]
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, timeout_s))
        # **Cancel what is still running.** `wait_for(gather(...))` cancels the gather, not the
        # tasks inside it, so a hanging provider still burned its full timeout before the
        # function returned -- measured 5.0s for a 1.0s deadline.
        for task in pending:
            task.cancel()
        if pending:
            result.failed = True
            await asyncio.gather(*pending, return_exceptions=True)
    except Exception:  # noqa: BLE001
        result.failed = True

    result.events = [e for e in events if e.event_id not in absorbed]
    return result