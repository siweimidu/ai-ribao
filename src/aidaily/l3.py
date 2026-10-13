"""L3: semantic event clustering -- "these different articles are one story".

Distinct from L2. L2 answers "is this the same article?" and must be conservative
because merging two different articles destroys information permanently. L3 answers
"are these different articles *about the same event*?" and is allowed to be a judgement
call, because the resolution is not deletion: every member keeps its own URL and its own
source, and the event reports all of them.

The design leans on three things that keep it affordable and auditable:

* **A rule pass before the LLM.** Entity overlap plus a time bucket turns a day's ~250
  items into a few dozen candidate groups, so the model only sees pairs worth judging.
  Without this, clustering a day would cost more than summarising it.
* **The model never emits a URL.** It returns item ids; the caller reconstructs links
  from its own data. A fabricated link is therefore structurally impossible.
* **Ambiguity is recorded, not resolved silently.** A cluster below the confidence
  threshold stays separate and is flagged, because a wrong merge is worse than a missed
  one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .dedup import ArticleUnit
from .llm import LLMError, LLMUnavailable, Router
from .models import Event, NormalizedItem

# --- entity extraction ------------------------------------------------------------
#: Organisations and products that matter for AI news. Kept small and explicit: a huge
#: list would add noise, and a model-based extractor would cost money for a job that a
#: dictionary does well enough to feed the LLM judge.
KNOWN_ENTITIES = (
    "openai", "anthropic", "google", "deepmind", "meta", "microsoft", "nvidia", "amd",
    "intel", "apple", "amazon", "aws", "tesla", "xai", "mistral", "cohere", "stability",
    "huggingface", "hugging face", "github", "cloudflare", "vercel", "databricks",
    "deepseek", "qwen", "alibaba", "baidu", "tencent", "bytedance", "moonshot", "zhipu",
    "minimax", "stepfun", "sensetime", "iflytek", "sakana", "figure", "waymo",
    "gpt", "claude", "gemini", "llama", "grok", "qwen", "kimi", "glm", "minicpm",
    "openbmb", "stablediffusion", "midjourney", "sora", "whisper", "phi", "o1", "o3",
    "智谱", "月之暗面", "商汤", "科大讯飞", "百度", "腾讯", "字节", "阿里", "蚂蚁",
    "华为", "小米", "深度求索", "百川", "零一万物", "面壁", "阶跃", "英伟达", "微软",
    "谷歌", "苹果", "OpenAI", "三星", "联想",
)

_LATIN_CAP = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:[-.][A-Za-z0-9]+)*)\b")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,8}")

#: Words that look like entities but carry no clustering signal. Two items sharing
#: "Best" are not about the same event, and letting such tokens through creates false
#: candidate clusters that cost a model call each to reject.
_STOP_CAPS = {
    # title-case English words common in headlines
    "the", "this", "that", "how", "why", "what", "when", "where", "who", "which",
    "new", "and", "for", "with", "from", "you", "your", "our", "its", "his", "her",
    "show", "ask", "best", "top", "first", "more", "most", "less", "all", "any",
    "introducing", "announcing", "announcement", "update", "updates", "release",
    "released", "launch", "launched", "week", "day", "year", "month", "today",
    "now", "here", "there", "then", "than", "into", "over", "under", "after",
    "before", "about", "just", "only", "also", "can", "will", "would", "could",
    "should", "may", "might", "must", "not", "but", "are", "was", "were", "has",
    "have", "had", "does", "did", "doing", "get", "got", "make", "made", "use",
    "used", "using", "one", "two", "three", "build", "building", "built", "thing",
    "things", "way", "ways", "time", "times", "part", "parts", "need", "needs",
    "want", "wants", "like", "said", "says", "report", "reports", "study", "data",
    "open", "source", "free", "full", "real", "next", "last", "back", "down",
    "openai's", "ai", "llm", "llms", "gpt", "model", "models",
}


def extract_entities(text: str, extra_lexicon: set[str] | None = None) -> set[str]:
    """Cheap entity bag: known names + capitalised latin tokens + CJK n-grams."""
    if not text:
        return set()
    low = text.lower()
    found: set[str] = set()

    for entity in KNOWN_ENTITIES:
        if entity.lower() in low:
            found.add(entity.lower())

    for match in _LATIN_CAP.finditer(text):
        token = match.group(1)
        # Stopwords are stored lowercase; compare case-insensitively or the filter
        # silently does nothing.
        if len(token) > 2 and token.lower() not in _STOP_CAPS:
            found.add(token.lower())

    for run in _CJK_RUN.findall(text):
        # Sliding 2-grams keep Chinese usable without a segmenter.
        for idx in range(len(run) - 1):
            found.add(run[idx:idx + 2])

    if extra_lexicon:
        for entity in extra_lexicon:
            if entity and entity.lower() in low:
                found.add(entity.lower())
    return found


# --- coarse clustering ------------------------------------------------------------
@dataclass
class CandidateCluster:
    key: str
    item_ids: list[str]
    shared_entities: set[str] = field(default_factory=set)


@dataclass
class ClusterResult:
    clusters: list[CandidateCluster]
    judged: int = 0
    rejected: int = 0
    llm_failed: bool = False


def _time_bucket(published: datetime | None, hours: int) -> int:
    if published is None:
        return -1
    epoch_hours = int(published.astimezone(timezone.utc).timestamp() // 3600)
    return epoch_hours // max(1, hours)


def coarse_clusters(
    items: list[NormalizedItem],
    *,
    entity_overlap_min: int = 2,
    time_bucket_hours: int = 6,
    lexicon: set[str] | None = None,
) -> list[CandidateCluster]:
    """Group items that share enough entities inside one time bucket.

    Singleton groups are dropped: they cannot be a cross-source event, so judging them
    would spend tokens to learn nothing.
    """
    entity_map: dict[str, set[str]] = {}
    for item in items:
        entity_map[item.item_id] = extract_entities(
            f"{item.title} {item.summary[:200]}", lexicon
        )

    parent: dict[str, str] = {i.item_id: i.item_id for i in items}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    buckets: dict[int, list[NormalizedItem]] = defaultdict(list)
    for item in items:
        buckets[_time_bucket(item.published_at, time_bucket_hours)].append(item)

    for bucket in buckets.values():
        for idx, left in enumerate(bucket):
            le = entity_map[left.item_id]
            if len(le) < entity_overlap_min:
                continue
            for right in bucket[idx + 1:]:
                overlap = le & entity_map[right.item_id]
                if len(overlap) >= entity_overlap_min:
                    union(left.item_id, right.item_id)

    grouped: dict[str, list[str]] = defaultdict(list)
    for item in items:
        grouped[find(item.item_id)].append(item.item_id)

    out: list[CandidateCluster] = []
    for root, ids in grouped.items():
        if len(ids) < 2:
            continue
        shared: set[str] = set.intersection(*(entity_map[i] for i in ids)) if ids else set()
        ids.sort()
        out.append(CandidateCluster(key="c" + hashlib.sha1("|".join(ids).encode()).hexdigest()[:10],
                                    item_ids=ids, shared_entities=shared))
    out.sort(key=lambda c: (-len(c.item_ids), c.key))
    return out


# --- LLM judge --------------------------------------------------------------------
JUDGE_SYSTEM = (
    "你是新闻聚合的判重助手。给定一组标题，判断它们是否在报道**同一件事**。\n"
    "判定规则：\n"
    "- 同一件事 = 同一主体 + 同一事件 + 同一时间。措辞不同不影响判定。\n"
    "- 只要主体、事件或结论任一不同，就不是同一件事。\n"
    "- 特别注意：结论相反的报道（如一份判决被判违规、另一份被判违法）**不是**同一件事。\n"
    "- 同一天同一公司发布不同产品，不是同一件事。\n"
    "只输出 JSON，不要解释或 markdown。"
)

JUDGE_TEMPLATE = """判断下面这组标题是否在报道同一件事。

{items}

只输出如下 JSON：
{{"same_event": true/false, "confidence": 0.0-1.0, "reason": "一句话理由（中文）"}}"""


async def judge_cluster(router: Router, cluster: CandidateCluster, by_id: dict[str, NormalizedItem]) -> tuple[bool, float, str]:
    lines = []
    for item_id in cluster.item_ids[:8]:
        item = by_id.get(item_id)
        if item is None:
            continue
        when = item.published_at.strftime("%Y-%m-%d %H:%M") if item.published_at else "时间未知"
        lines.append(f"- [{item_id}] ({item.source_id}, {when}) {item.title[:120]}")
    prompt = JUDGE_TEMPLATE.format(items="\n".join(lines))

    try:
        got = await router.complete_json(
            [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=256, purpose="l3_judge",
        )
    except (LLMError, LLMUnavailable):
        raise

    if not isinstance(got, dict):
        return False, 0.0, "judge returned a non-object"
    same = bool(got.get("same_event"))
    try:
        confidence = float(got.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return same, max(0.0, min(1.0, confidence)), str(got.get("reason") or "")[:200]


async def build_events(
    units: list[ArticleUnit],
    router: Router | None,
    *,
    source_groups: dict[str, str] | None = None,
    entity_overlap_min: int = 2,
    time_bucket_hours: int = 6,
    confidence_threshold: float = 0.75,
    max_clusters: int = 60,
    judge_concurrency: int = 4,
) -> tuple[list[Event], ClusterResult]:
    """Turn L2 units into Events, merging only clusters the judge accepts.

    The input is a list of `ArticleUnit` -- one per distinct article -- so an event is
    built out of L2 groups rather than raw items. Passing raw items here would undo L2:
    a story carried by three feeds would become three separate "events".

    With no router (or when the LLM is unavailable) every cluster is rejected and units
    stay singletons -- the pipeline degrades to "L2 only" rather than guessing.
    """
    by_unit = {u.unit_id: u for u in units}

    # Clustering sees the representative item of each unit, labelled by unit id.
    proxies = [
        u.representative.model_copy(update={"item_id": u.unit_id}) for u in units
    ]
    by_id = {u.unit_id: u.representative for u in units}

    candidates = coarse_clusters(
        proxies, entity_overlap_min=entity_overlap_min, time_bucket_hours=time_bucket_hours
    )[:max_clusters]

    result = ClusterResult(clusters=candidates)
    accepted: list[CandidateCluster] = []

    if router is not None:
        # Judged concurrently. Sequentially, 60 candidate clusters at a few seconds each
        # blew past the job's time budget -- the first live run had to be killed at ten
        # minutes. A semaphore keeps the request rate civil without serialising the work.
        sem = asyncio.Semaphore(judge_concurrency)
        outcomes: dict[str, tuple[bool, float, str]] = {}
        failed = False

        async def judge_one(cluster: CandidateCluster) -> None:
            nonlocal failed
            async with sem:
                if failed:
                    return
                try:
                    outcomes[cluster.key] = await judge_cluster(router, cluster, by_id)
                except (LLMError, LLMUnavailable):
                    failed = True

        await asyncio.gather(*(judge_one(c) for c in candidates))

        for cluster in candidates:
            got = outcomes.get(cluster.key)
            if got is None:
                continue
            same, confidence, _reason = got
            result.judged += 1
            if same and confidence >= confidence_threshold:
                accepted.append(cluster)
            else:
                result.rejected += 1
        if failed:
            result.llm_failed = True

    membership: dict[str, str] = {}
    for cluster in accepted:
        for unit_id in cluster.item_ids:
            membership[unit_id] = cluster.key

    groups: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        groups[membership.get(unit.unit_id, f"single:{unit.unit_id}")].append(unit.unit_id)

    events: list[Event] = []
    for key, unit_ids in groups.items():
        unit_ids.sort()
        members = [by_unit[u] for u in unit_ids if u in by_unit]
        if not members:
            continue
        primary = max(members, key=lambda u: (len(u.representative.content_text or u.representative.summary or ""), u.unit_id)).representative

        # Expand back to every underlying item, URL and source across the whole event.
        item_ids = sorted({i for u in members for i in u.item_ids})
        urls = sorted({url for u in members for url in u.urls})
        source_ids = sorted({s for u in members for s in u.source_ids})
        # Independent sources: collapse feeds that carry the same content. hn-algolia and
        # hnrss-frontpage surface identical HN stories, so an event reported by both is
        # still a single source. Treating it as corroboration would overstate confidence.
        groups = source_groups or {}
        independent = len({groups.get(s, s) for s in source_ids})
        published = [u.representative.published_at for u in members if u.representative.published_at]
        first_seen = min((u.representative.first_seen_at for u in members), default=primary.first_seen_at)
        updated = max((u.representative.updated_at for u in members), default=primary.updated_at)

        events.append(
            Event(
                event_id="e" + hashlib.sha1(key.encode()).hexdigest()[:14],
                title=primary.title,
                member_item_ids=item_ids,
                primary_item_id=primary.item_id,
                source_ids=source_ids,
                all_urls=urls,
                independent_source_count=independent,
                first_seen_at=first_seen,
                last_updated_at=updated,
                published_range=(min(published), max(published)) if published else None,
                confidence=0.9 if len(members) > 1 else 1.0,
                evidence_level="multi_source" if independent > 1 else "single_source",
                needs_review=False,
            )
        )

    events.sort(key=lambda e: (-e.independent_source_count, -len(e.source_ids), e.event_id))
    return events, result


def events_stats(events: list[Event]) -> dict[str, int]:
    multi = [e for e in events if len(e.member_item_ids) > 1]
    return {
        "events": len(events),
        "multi_source_events": len(multi),
        "items_in_multi_source_events": sum(len(e.member_item_ids) for e in multi),
        "singletons": len(events) - len(multi),
    }
