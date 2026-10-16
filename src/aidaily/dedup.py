"""L2 article-level dedup: "these N records are the same article".

Distinct from L1 (duplicate *sources*, a registry-time concern) and L3 (several
*different* articles about one event, an LLM concern).

The governing bias is asymmetry of error:
  * failing to merge leaves a duplicate in the digest -- annoying, recoverable;
  * merging two genuinely different articles destroys information -- unrecoverable.
So every rule below merges only on a strong signal, and the one plausible-but-weak
signal (similar titles on different domains) is recorded as `AmbiguousPair` instead
of being merged.
"""

from __future__ import annotations

import re

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import AmbiguousPair, DupGroup, NormalizedItem
from .normalize import hamming, normalize_content, title_similarity, url_domain


#: Title similarity that merges without consulting simhash.
#:
#: Above every real near-duplicate measured on a published issue (the closest was 0.976) and below
#: the point where two different stories about one subject coincide. The publication window still
#: applies. See the `title_prefix` candidate channel for why the simhash gate alone is not enough.
TITLE_MERGE_WITHOUT_SIMHASH = 0.93

#: Words that announce a story without changing it. Removing them from both headlines and finding
#: the results equal is a stronger signal than a similarity ratio: `可灵 Kling 4.0 正式发布` and
#: `可灵 Kling 4.0 发布` score 0.917 -- below the threshold above -- but are the same headline with
#: one adverb added.
#:
#: Measured against the pairs that must *not* merge: `Meta 发布多模态开放权重模型 Muse Spark Open`
#: and `Meta 发布开源权重模型 Muse Spark Open` (0.906) differ by a real technical qualifier, and
#: stripping leaves them unequal, so this rule does not touch them.
_TITLE_NOISE = re.compile(
    r"(正式|快速|全新|重磅|最新|刚刚|同步|独家|首发|官宣|"
    r"officially|now|just|finally|正式版)"
)


def titles_are_the_same_story(left: str, right: str) -> bool:
    """True when two folded headlines differ only by announcement filler.

    Deliberately narrow. A similarity ratio cannot separate "same headline plus an adverb" from
    "same subject, different fact", and the second kind must not be merged.
    """
    if not left or not right:
        return False
    strip = lambda t: _TITLE_NOISE.sub("", t)  # noqa: E731
    a, b = strip(left), strip(right)
    if a == b:
        return True
    # The shorter is contained in the longer with at most a few characters left over, which covers
    # a dropped outlet suffix (`... - 东方财富`) without letting a genuinely longer headline through.
    short, long = sorted((a, b), key=len)
    return len(short) >= 8 and short in long and len(long) - len(short) <= 6


@dataclass
class DedupConfig:
    simhash_distance: int = 3
    title_similarity_merge: float = 0.85      # required alongside a close simhash
    title_similarity_ambiguous: float = 0.92  # different domains -> flag, never merge
    publish_window_hours: int = 72
    ambiguous_window_hours: int = 24


@dataclass
class DedupResult:
    groups: list[DupGroup] = field(default_factory=list)
    ambiguous: list[AmbiguousPair] = field(default_factory=list)
    item_to_group: dict[str, str] = field(default_factory=dict)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "items_in": sum(len(g.member_item_ids) for g in self.groups),
            "groups": len(self.groups),
            "merged_away": sum(len(g.member_item_ids) - 1 for g in self.groups),
            "ambiguous_pairs": len(self.ambiguous),
        }


@dataclass
class ArticleUnit:
    """One distinct article after L2, carrying every URL and source it was found in.

    L3 must cluster *units*, not raw items: feeding it the raw items would split apart
    exactly the duplicates L2 just merged. The unit keeps the full member list so the
    event built on top of it can still report every link.
    """

    unit_id: str
    representative: NormalizedItem
    item_ids: list[str]
    urls: list[str]
    source_ids: list[str]


def units_from_result(result: DedupResult, items: list[NormalizedItem]) -> list[ArticleUnit]:
    """Collapse a DedupResult into one unit per group, preserving all members."""
    by_id = {i.item_id: i for i in items}
    units: list[ArticleUnit] = []
    for group in result.groups:
        primary = by_id.get(group.primary_item_id)
        if primary is None:
            members = [by_id[m] for m in group.member_item_ids if m in by_id]
            if not members:
                continue
            primary = members[0]
        units.append(
            ArticleUnit(
                unit_id=group.dup_group_id,
                representative=primary,
                item_ids=list(group.member_item_ids),
                urls=list(group.all_urls),
                source_ids=list(group.source_ids),
            )
        )
    return units


class _DSU:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {k: k for k in keys}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:      # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        # deterministic root choice keeps output stable across runs
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        return True


def _within(a: datetime | None, b: datetime | None, hours: int) -> bool:
    """Time gate. A missing date on either side does NOT block an exact-match merge."""
    if a is None or b is None:
        return True
    return abs((a - b).total_seconds()) <= hours * 3600


def _group_id(members: list[str]) -> str:
    return "d" + hashlib.sha1("|".join(sorted(members)).encode()).hexdigest()[:15]


def _block_layout(distance: int, bits: int = 64) -> list[tuple[int, int]]:
    """Split widths/shifts for multi-index hashing at a given Hamming distance.

    Returns `distance + 1` blocks, which is what the pigeonhole argument requires:
    with d differing bits and d+1 blocks, at least one block must be identical, so
    indexing every block cannot miss a pair within distance d.
    """
    nblocks = max(1, distance + 1)
    size = max(1, bits // nblocks)
    return [((1 << size) - 1, i * size) for i in range(nblocks)]


def _merge_content(items: list[NormalizedItem]) -> str:
    """Primary (longest) content first, then each other source's *new* paragraphs.

    Mirrors the approach already proven in Horizon's orchestrator: keep both texts
    rather than picking a winner, so a source's unique detail is not discarded.
    """
    ordered = sorted(items, key=lambda i: len(i.content_text or ""), reverse=True)
    primary = ordered[0]
    primary_body = primary.content_text or primary.summary or ""
    chunks: list[str] = [primary_body]
    # Track paragraphs, not whole bodies: a shared paragraph must be recognized even
    # though the two articles differ overall, otherwise it gets appended twice.
    seen = {normalize_content(p) for p in primary_body.split("\n") if p.strip()}

    for item in ordered[1:]:
        body = item.content_text or item.summary or ""
        if not body:
            continue
        novel: list[str] = []
        for para in body.split("\n"):
            para = para.strip()
            if not para:
                continue
            key = normalize_content(para)
            if key and key not in seen:
                seen.add(key)
                novel.append(para)
        if novel:
            chunks.append(f"--- 来自 {item.source_id} 的补充 ---\n" + "\n".join(novel))
    return "\n\n".join(c for c in chunks if c).strip()


def cluster(items: list[NormalizedItem], cfg: DedupConfig | None = None) -> DedupResult:
    """Cluster items into "same article" groups."""
    cfg = cfg or DedupConfig()
    if not items:
        return DedupResult()

    by_id = {i.item_id: i for i in items}
    dsu = _DSU(list(by_id))
    matched_by: dict[str, set[str]] = defaultdict(set)

    def link(a: str, b: str, rule: str) -> None:
        if dsu.union(a, b):
            matched_by[dsu.find(a)].add(rule)

    # --- exact keys: no time gate, these are provably the same record ------------
    for key_fn, rule in (
        (lambda i: i.canonical_url or "", "canonical_url"),
        (lambda i: i.url, "url"),
        (lambda i: i.content_sha256 or "", "content_sha256"),
    ):
        buckets: dict[str, list[str]] = defaultdict(list)
        for item in items:
            k = key_fn(item)
            if k:
                buckets[k].append(item.item_id)
        for ids in buckets.values():
            for other in ids[1:]:
                link(ids[0], other, rule)

    # --- same domain + identical normalized title -------------------------------
    # A time gate is essential here: daily and weekly columns reuse their title
    # ("AI 早报"), so site+title alone would collapse separate editions into one
    # record and delete whole days of content.
    title_buckets: dict[tuple[str, str], list[NormalizedItem]] = defaultdict(list)
    for item in items:
        if item.title_norm:
            title_buckets[(url_domain(item.url), item.title_norm)].append(item)
    for rows in title_buckets.values():
        for idx, left in enumerate(rows):
            for right in rows[idx + 1:]:
                if not _within(left.published_at, right.published_at, cfg.publish_window_hours):
                    continue
                link(left.item_id, right.item_id, "domain+title_norm")

    # --- near-duplicate wording + overlapping publication window ----------------
    # Candidate generation uses multi-index hashing. The obvious approach -- bucket on
    # the top 16 bits and probe `top ^ delta` for delta in 0..3 -- is WRONG: it only
    # tolerates differences in the low two bits of that block, so two hashes three bits
    # apart at bit 63 land in different buckets and are never compared. (That bug made
    # the first real run report a 0% merge rate.)
    #
    # Correct by the pigeonhole principle: split the hash into d+1 blocks; d differing
    # bits can affect at most d blocks, so at least one block must match exactly.
    blocks = _block_layout(cfg.simhash_distance)
    tables: list[dict[int, list[NormalizedItem]]] = [defaultdict(list) for _ in blocks]
    for item in items:
        if item.simhash:
            for idx, (_mask, shift) in enumerate(blocks):
                tables[idx][(item.simhash >> shift) & 0xFFFF].append(item)

    for item in items:
        if not item.simhash:
            continue
        considered: set[str] = set()
        for idx, (_mask, shift) in enumerate(blocks):
            for candidate in tables[idx].get((item.simhash >> shift) & 0xFFFF, ()):
                if candidate.item_id >= item.item_id or candidate.item_id in considered:
                    continue
                considered.add(candidate.item_id)
                if not _within(item.published_at, candidate.published_at, cfg.publish_window_hours):
                    continue
                sim = title_similarity(item.title_norm, candidate.title_norm)
                # **Title similarity can merge on its own, without the simhash gate.**
                #
                # The gate exists to avoid comparing every pair, not to judge sameness -- and it
                # measures the wrong thing: "…马斯克回应：…" vs "…马斯克快速回应：…" is 0.976 similar
                # by title and 6 bits apart by simhash, because two changed CJK bigrams spread
                # across several bits. Gated on simhash alone, a 97.6%-identical pair published
                # twice in one issue was never even compared.
                if sim >= TITLE_MERGE_WITHOUT_SIMHASH:
                    link(item.item_id, candidate.item_id, "title_very_similar")
                    continue
                if hamming(item.simhash, candidate.simhash) > cfg.simhash_distance:
                    continue
                if sim >= cfg.title_similarity_merge:
                    link(item.item_id, candidate.item_id, "simhash+title")

    # --- title-prefix candidates -------------------------------------------------
    # **An independent candidate channel, because multi-index hashing under-generates.**
    #
    # Measured on a pair published twice in one issue: titles 0.976 similar, simhash 6 bits apart
    # with the differences spread across all four blocks -- so the pigeonhole scheme (which needs
    # one exact block match at d=3) generated no pair at all and the two were never compared. A
    # gate meant to bound the work was silently deciding the answer.
    #
    # Near-duplicate headlines share their opening characters, so a prefix bucket finds them
    # without any hashing assumption. The comparison below is the same one the simhash path uses,
    # so the decision is still made by title similarity.
    prefix_buckets: dict[str, list[NormalizedItem]] = defaultdict(list)
    for item in items:
        if item.title_norm:
            prefix_buckets[item.title_norm[:8]].append(item)
    for rows in prefix_buckets.values():
        if len(rows) < 2:
            continue
        for idx, left in enumerate(rows):
            for right in rows[idx + 1:]:
                if dsu.find(left.item_id) == dsu.find(right.item_id):
                    continue
                if not _within(left.published_at, right.published_at, cfg.publish_window_hours):
                    continue
                # **The title is not enough on its own.**
                #
                # Measured: two headlines differing only in `API 访问` / `API 调用` on different
                # domains, whose bodies are about different things (one is a pricing table, the
                # other is a rack power design). A title-only rule merged them, which deletes a
                # real story -- the one outcome L2 must never produce, and the reason this case
                # exists in the test suite at all.
                #
                # The simhash path never had this bug: a small simhash distance *is* evidence the
                # bodies match. This channel removed that evidence while keeping the conclusion, so
                # the body check is restored here rather than assumed.
                body_close = (
                    bool(left.simhash) and bool(right.simhash)
                    and hamming(left.simhash, right.simhash) <= cfg.simhash_distance
                ) or (left.content_sha256 and left.content_sha256 == right.content_sha256)
                if not body_close:
                    continue
                if titles_are_the_same_story(left.title_norm, right.title_norm):
                    link(left.item_id, right.item_id, "title_same_story")
                    continue
                sim = title_similarity(left.title_norm, right.title_norm)
                if sim >= cfg.title_similarity_merge:
                    link(left.item_id, right.item_id, "title_prefix")

    # --- ambiguous: similar titles, different domains, close in time -------------
    # Never merged. Recorded so a human can review the near-misses.
    ambiguous: list[AmbiguousPair] = []
    by_title_bucket: dict[str, list[NormalizedItem]] = defaultdict(list)
    for item in items:
        if item.title_norm:
            by_title_bucket[item.title_norm[:12]].append(item)
    for bucket in by_title_bucket.values():
        for idx, left in enumerate(bucket):
            for right in bucket[idx + 1:]:
                if dsu.find(left.item_id) == dsu.find(right.item_id):
                    continue
                if url_domain(left.url) == url_domain(right.url):
                    continue
                sim = title_similarity(left.title_norm, right.title_norm)
                if sim < cfg.title_similarity_ambiguous:
                    continue
                if not _within(left.published_at, right.published_at, cfg.ambiguous_window_hours):
                    continue
                ambiguous.append(
                    AmbiguousPair(
                        left_item_id=left.item_id,
                        right_item_id=right.item_id,
                        similarity=round(sim, 4),
                        reason="标题高度相似但域名不同且发布接近：可能是同一事件的不同报道，不自动合并",
                    )
                )

    # --- materialize groups ------------------------------------------------------
    components: dict[str, list[str]] = defaultdict(list)
    for item_id in by_id:
        components[dsu.find(item_id)].append(item_id)

    result = DedupResult(ambiguous=ambiguous)
    for root, member_ids in components.items():
        member_ids.sort()
        members = [by_id[m] for m in member_ids]
        primary = max(members, key=lambda m: (len(m.content_text or m.summary or ""), m.item_id))
        gid = _group_id(member_ids)
        published = [m.published_at for m in members if m.published_at]
        group = DupGroup(
            dup_group_id=gid,
            primary_item_id=primary.item_id,
            member_item_ids=member_ids,
            # every URL and every source is preserved -- dedup must not destroy evidence
            all_urls=sorted({m.url for m in members if m.url} | {m.canonical_url for m in members if m.canonical_url}),
            source_ids=sorted({m.source_id for m in members}),
            title=primary.title,
            published_at=min(published) if published else None,
            first_seen_at=min(m.first_seen_at for m in members),
            updated_at=max(m.updated_at for m in members),
            merged_content=_merge_content(members),
            domain=url_domain(primary.url),
            matched_by=sorted(matched_by.get(root, {"singleton"})),
            confidence=1.0 if len(members) == 1 else 0.95,
        )
        result.groups.append(group)
        for m in member_ids:
            result.item_to_group[m] = gid

    result.groups.sort(key=lambda g: (-len(g.member_item_ids), g.dup_group_id))
    return result
