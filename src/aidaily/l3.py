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
from itertools import combinations

from .dedup import ArticleUnit
from .entities import KNOWN_ENTITIES, extract_entities
from .llm import LLMError, LLMUnavailable, Router
from .models import Event, NormalizedItem
from .normalize import title_similarity
from .samestory import same_message

#: Re-exported so existing callers keep working; the implementation moved to entities.py
#: when ranking also needed it (ranking a list should not import the clustering module).
__all__ = ["KNOWN_ENTITIES", "extract_entities"]

# --- entity extraction ------------------------------------------------------------
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
    #: Clusters the judge never returned a verdict for -- usually the provider was rate
    #: limited mid-run. Counted separately so a report cannot imply the model reviewed them.
    unjudged: int = 0
    #: Clusters merged by the deterministic fallback because no judge reviewed them.
    accepted_without_judge: int = 0


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

    buckets: dict[int, list[NormalizedItem]] = defaultdict(list)
    for item in items:
        buckets[_time_bucket(item.published_at, time_bucket_hours)].append(item)

    # Seed-based grouping, not union-find.
    #
    # Union-find computes a **transitive closure**: A joins B on two shared entities, B joins
    # C on two others, and A and C end up in one cluster having nothing in common. Measured
    # on a real day this produced a single candidate cluster of **116 items** whose
    # shared-entity intersection was empty. The thirteen reports of the Gemini 4 Argon
    # launch were inside that blob, so they never formed their own event -- and since the
    # blob was then rejected as incoherent, none of them merged at all. They scattered to
    # positions 1, 41, 55, 56, 57, 59 and 60 of 60 instead of leading the issue.
    #
    # Here a cluster is built around a seed and every member must share entities **with the
    # seed**. That is a real constraint rather than a chain: an item that shares nothing with
    # the seed cannot enter by way of a third party. Cost is that a genuine story carried by
    # two different vocabularies may split into two clusters -- which the merge step tolerates
    # (two entries about one story) whereas a 116-item blob does not.
    out: list[CandidateCluster] = []
    for bucket in buckets.values():
        # Longest entity sets first: a headline naming several specifics is a better anchor
        # than one that happens to share a common word.
        ordered = sorted(bucket, key=lambda i: (-len(entity_map[i.item_id]), i.item_id))
        claimed: set[str] = set()

        for seed in ordered:
            if seed.item_id in claimed:
                continue
            seed_entities = entity_map[seed.item_id]
            if len(seed_entities) < entity_overlap_min:
                continue

            members = [seed.item_id]
            for other in bucket:
                if other.item_id == seed.item_id or other.item_id in claimed:
                    continue
                # Entity overlap is the main signal, but it cannot see two spellings of one
                # name: `DeepSeek参与塑造Huawei人工智能芯片设计` and `…华为…` share one entity
                # (`deepseek`) and nothing else, so they never landed in one cluster and the
                # same Huawei chip story was published twice, from two publishers.
                #
                # `same_message` compares actor + event type + wording, which is what joins
                # the Latin and the Chinese spelling. It is a narrow, rule-based check, so it
                # cannot chain unrelated items the way a lowered entity threshold would.
                if (
                    len(seed_entities & entity_map[other.item_id]) >= entity_overlap_min
                    or same_message(seed.title, other.title)
                ):
                    members.append(other.item_id)

            if len(members) < 2:
                continue
            claimed.update(members)
            # What the cluster is *about*: the smallest entity set a member shares with the
            # seed. Every member is guaranteed to share at least `entity_overlap_min` with
            # it, so this is non-empty by construction.
            #
            # Not the intersection of every member: seven headlines about one launch will
            # each mention a different extra detail, so their global intersection is empty
            # even though they are unmistakably one story. Measured -- the seven-report
            # Gemini 4 Argon cluster reported `shared=0` under the intersection rule and was
            # rejected as incoherent.
            core: set[str] | None = None
            for member in members:
                overlap = seed_entities & entity_map[member]
                if core is None or len(overlap) < len(core):
                    core = set(overlap)
            members.sort()
            out.append(CandidateCluster(
                key="c" + hashlib.sha1("|".join(members).encode()).hexdigest()[:10],
                item_ids=members,
                shared_entities=core or set(),
            ))

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


#: Feeds that republish another publisher's material. A story seen here and on the original
#: is one publisher twice, not corroboration.
_AGGREGATOR_HOSTS = (
    "news.google.com",
    "raw.githubusercontent.com",
    "hn.algolia.com",
    "hnrss.org",
    "hacker-news.firebaseio.com",
    "reddit.com",
    "t.me",
    "wechat2rss.xlab.app",
    "wechat2rss.bestblogs.dev",
    "rss.beehiiv.com",
)

#: Hosts seen in this registry, longest-first so `aihot-demo-techcrunch-ai` is not read as the
#: `aihot` prefix followed by a section name. Splitting on hyphens alone cannot tell
#: `aihot-news` from `aihot-demo-techcrunch-ai`.
_PUBLISHER_PREFIXES = (
    "aihot", "ainewslog", "arstechnica", "aws-amazon", "bair-berkeley", "baoyu-io",
    "blog-google", "blogs-nvidia", "daily-ai225", "daily-juya", "dailydawn-dev",
    "decemberpei-cyou", "deepmind-google", "github-blog", "github-com", "huggingface-co",
    "importai-substack", "justlovemaki-github-io", "leovan-me", "mcpapi-aibase-cn",
    "mistral-ai", "news-mit", "openai-com", "podrss-1874-run", "research-google",
    "simonwillison-net", "techcrunch-com", "the-decoder", "theverge-com",
    "trends-google", "v2ex-com", "wangyi-ai", "www-latent-space", "www-microsoft",
    "www-minimax-io", "www-technologyreview", "hex2077-dev", "unclejoeyao666-github-io",
    "ai-hubtoday-app", "git-trending-justlikemaki-vip", "s-baoyu-io",
)


def _publisher_of(source_id: str, groups: dict[str, str]) -> str:
    """The publishing organisation behind a feed, as a comparable key.

    "Corroborated by multiple sources" only means something if the sources are different
    *publishers*. Measured on 2026-10-20: `aihot.news` supplied 27 of 44 published events
    through 12 registered feeds, and a story carried by three of them counted as three
    witnesses.

    `dedup_group` wins when the registry declares it. Otherwise the host is recovered from the
    feed id -- that is what identifies a publisher, not the section name after it.
    """
    declared = groups.get(source_id)
    if declared:
        return "p:" + declared

    slug = source_id.split(":", 1)[-1].lower()

    # `rss:aihot-demo-techcrunch-ai` carries TechCrunch's feed, so TechCrunch is the
    # publisher. Reading the leading `aihot` would credit the aggregator with the story.
    demo = re.match(r"aihot-demo-(.+?)-ai$", slug)
    if demo:
        return "p:" + demo.group(1)

    # Aggregators first: a story on Google News is still the original publisher's story.
    for host in _AGGREGATOR_HOSTS:
        dashed = host.replace(".", "-")
        if slug == dashed or slug.startswith(dashed + "-"):
            return "agg:" + host

    # Then a known host prefix, longest match first.
    for prefix in sorted(_PUBLISHER_PREFIXES, key=len, reverse=True):
        if slug == prefix or slug.startswith(prefix + "-"):
            return "p:" + prefix

    # Unknown host: the first two labels are the closest available guess.
    parts = slug.split("-")
    return "p:" + "-".join(parts[:2]) if len(parts) >= 2 else "p:" + parts[0]


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

    def merge_unambiguous(cluster: CandidateCluster) -> bool:
        """Deterministic merge for a cluster no judge reviewed.

        Merging nothing leaves one story split across as many "events" as there are
        reports, and the diversity pass then penalises every one of them for repeating a
        topic -- so the day's biggest story ends up buried.

        Measured: thirteen reports of the Gemini 4 Argon launch, unmerged, landed at
        positions 1, 41, 55, 56, 57, 59 and 60 of 60, while a chat-app point release sat in
        the top twelve. The conservative choice is not "merge nothing", it is "merge what is
        unambiguous".

        Deliberately narrower than the LLM's brief. Two conditions, both required:

        * a shared core of at least three entities **and** some headline similarity, or
        * the minimum overlap **and** a clearly similar headline (0.5).

        The headline condition is not decoration. Entities nest -- `gpt` and `gpt-6` are one
        thing counted twice, exactly as sliding CJK bigrams were -- so "three shared
        entities" on its own merged "OpenAI ships GPT-6 model" with "OpenAI GPT-6 benchmarks
        leak": the same two facts written twice. Requiring the headlines to also resemble
        each other is what keeps a count of entities from standing in for a judgement about
        the story.
        """
        titles = [by_id[i].title for i in cluster.item_ids if i in by_id]
        if not titles:
            return False
        shared = len(cluster.shared_entities)
        best_similarity = 0.0
        for left, right in combinations(titles, 2):
            best_similarity = max(
                best_similarity, title_similarity(left.lower(), right.lower())
            )
        return (shared >= 3 and best_similarity >= 0.35) or (
            shared >= entity_overlap_min and best_similarity >= 0.5
        )

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
                # The judge never returned for this one: either the provider was rate
                # limited mid-run, or the budget ran out. That is the production case --
                # a live run hit `gemini: HTTP 429 daily` and `groq: HTTP 429` and left
                # most clusters unjudged. Skipping them here is what let the day's biggest
                # story scatter, so they fall through to the deterministic merge instead.
                result.unjudged += 1
                if merge_unambiguous(cluster):
                    accepted.append(cluster)
                    result.accepted_without_judge += 1
                else:
                    result.rejected += 1
                continue
            same, confidence, _reason = got
            result.judged += 1
            if same and confidence >= confidence_threshold:
                accepted.append(cluster)
            elif merge_unambiguous(cluster):
                # **The judge said no; the evidence says they are one story.**
                #
                # `merge_unambiguous` was only consulted when the judge returned *nothing*, so a
                # cluster the judge rejected was discarded whole. Measured: four Muse Spark Open
                # headlines sharing `{meta, muse, spark}` -- one launch, announced once -- stayed as
                # four entries because the judge judged them separate events.
                #
                # The rule applied is the conservative one already in this file (three shared
                # entities *and* similar headlines, or the minimum overlap plus 0.5). It cannot
                # merge unrelated stories; it stops a single launch being split four ways.
                accepted.append(cluster)
                result.accepted_without_judge += 1
            else:
                result.rejected += 1
        if failed:
            result.llm_failed = True

    else:
        # No judge configured at all (`--no-llm`, or no provider key). Same reasoning: merge
        # what is unambiguous, leave the rest split.
        for cluster in candidates:
            if merge_unambiguous(cluster):
                accepted.append(cluster)
                result.accepted_without_judge += 1
            else:
                result.rejected += 1

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

        # The representative is the **most central** title, not the longest one.
        #
        # Longest-body used to win, which for a merged cluster picked whichever member
        # happened to have the most text -- not whichever described the story. Measured: the
        # seven-report Gemini 4 Argon cluster took its title from a passing mention of
        # Google's vibe-coding tool, so the event that led the issue was headlined with a
        # different story than the one its six other members were about.
        #
        # Centrality here is "how many other members does this title share entities with".
        # That is exactly the property the cluster was built on, so the anchor that bound it
        # together is the one that names it. Ties break on body length (a more informative
        # title is better than a terser one) and then on unit id for determinism.
        def centrality(unit) -> tuple[int, int, str]:
            entities = extract_entities(unit.representative.title)
            shared_with = sum(
                1
                for other in members
                if other.unit_id != unit.unit_id
                and entities & extract_entities(other.representative.title)
            )
            body = len(unit.representative.content_text or unit.representative.summary or "")
            return (shared_with, body, unit.unit_id)

        primary = max(members, key=centrality).representative

        # Expand back to every underlying item, URL and source across the whole event.
        item_ids = sorted({i for u in members for i in u.item_ids})
        urls = sorted({url for u in members for url in u.urls})
        source_ids = sorted({s for u in members for s in u.source_ids})
        # Independent sources: collapse feeds that carry the same content. hn-algolia and
        # hnrss-frontpage surface identical HN stories, so an event reported by both is
        # still a single source. Treating it as corroboration would overstate confidence.
        groups = source_groups or {}
        #
        # Then collapse by **publisher domain**, because the group key alone overstated
        # corroboration badly. Measured on 2026-10-20: `aihot.news` alone accounted for 27 of
        # 44 published events, and it is registered as 12 feeds (news, news-full, news-picks,
        # cat-models, cat-industry, ...). Those are one publisher's栏目, not twelve independent
        # witnesses -- but only some carried a `dedup_group`, so a story covered by three
        # aihot feeds counted as three sources.
        #
        # "Corroborated by multiple sources" means multiple *publishers*. That is the only
        # reading under which the number says anything to a reader.
        independent = len({
            _publisher_of(s, groups) for s in source_ids
        })
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
