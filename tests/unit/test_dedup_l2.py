"""L2 article-level dedup.

Three behaviours are load-bearing and each has an explicit test, because getting
them wrong is how a digest either drowns in duplicates or silently deletes a story:

  1. the same article mirrored elsewhere     -> MERGE
  2. the same article re-published on one site -> MERGE
  3. two different articles with similar titles -> DO NOT MERGE (flag for review)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.dedup import DedupConfig, cluster
from aidaily.normalize import hamming

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)

ARTICLE = (
    "OpenAI today announced a new reasoning model. The company said the model improves "
    "mathematical accuracy by 30 percent over the previous generation, and is available "
    "through the API starting today for all paid tiers."
)


def test_mirror_of_same_article_merges(make_item) -> None:
    """Same text on two different sites is one story, not two."""
    a = make_item(title="OpenAI ships new reasoning model", url="https://openai.com/blog/r1",
                  content=ARTICLE, source_id="rss:openai", item_id="i0001")
    b = make_item(title="OpenAI ships new reasoning model", url="https://mirror.example/r1-copy",
                  content=ARTICLE, source_id="rss:mirror", item_id="i0002")

    result = cluster([a, b])

    assert len(result.groups) == 1, "mirrored copies must collapse to one group"
    g = result.groups[0]
    assert g.member_item_ids == ["i0001", "i0002"]
    assert set(g.all_urls) == {"https://openai.com/blog/r1", "https://mirror.example/r1-copy"}
    assert set(g.source_ids) == {"rss:openai", "rss:mirror"}


def test_same_site_retitled_republish_merges(make_item) -> None:
    """A feed that re-issues an item under a new URL and a re-cased title is one record.

    The bodies differ slightly (an AMP re-render adds a footer), so the content hash
    does not match -- the site+title rule is the one that has to catch this.
    """
    a = make_item(title="OpenAI ships new reasoning model", url="https://site.example/a",
                  content=ARTICLE, source_id="rss:a", item_id="i0001")
    b = make_item(title="OpenAI Ships New Reasoning Model", url="https://site.example/a-amp",
                  content=ARTICLE + "\n阅读原文请访问我们的网站。", source_id="rss:a", item_id="i0002",
                  published_at=NOW + timedelta(hours=2))

    result = cluster([a, b])

    assert len(result.groups) == 1
    assert "domain+title_norm" in result.groups[0].matched_by


def test_different_articles_with_similar_titles_do_not_merge(make_item) -> None:
    """Nearly identical headlines on different sites are the risky case.

    Merging here would delete a real story, so the pair must be reported as ambiguous
    and stay separate.
    """
    a = make_item(
        title="OpenAI 正式发布全新一代推理模型 o5 预览版并开放 API 访问",
        url="https://outlet-a.example/story",
        content="这一代模型在数学推理上提升明显，官方给出了新的定价表。",
        source_id="rss:a", item_id="i0001",
    )
    b = make_item(
        title="OpenAI 正式发布全新一代推理模型 o5 预览版并开放 API 调用",
        url="https://outlet-b.example/story",
        content="英伟达同日公布了下一代机架的供电设计，与本次发布无关。",
        source_id="rss:b", item_id="i0002",
        published_at=NOW + timedelta(hours=3),
    )

    result = cluster([a, b])

    assert len(result.groups) == 2, "similar titles on different domains must not be merged"
    assert len(result.ambiguous) == 1
    pair = result.ambiguous[0]
    assert {pair.left_item_id, pair.right_item_id} == {"i0001", "i0002"}
    assert pair.similarity >= DedupConfig().title_similarity_ambiguous


def test_recurring_column_is_not_merged_across_days(make_item) -> None:
    """A daily column reuses its title. Same site + same title is NOT enough."""
    a = make_item(title="AI 早报", url="https://daily.example/2026-10-13",
                  content="今日要闻：第一条……", source_id="rss:d", item_id="i0001",
                  published_at=NOW - timedelta(days=30))
    b = make_item(title="AI 早报", url="https://daily.example/2026-10-14",
                  content="今日要闻：完全不同的一批内容……", source_id="rss:d", item_id="i0002",
                  published_at=NOW)

    result = cluster([a, b])

    assert len(result.groups) == 2, "a recurring column must not collapse into one record"


def test_exact_duplicate_merges_even_without_dates(make_item) -> None:
    """Missing publication dates must not block a provably identical record.

    GitHub Trending carries no per-item date by design; two fetches of the same repo
    are still the same record.
    """
    a = make_item(title="some/repo", url="https://github.com/some/repo", content="a repo",
                  source_id="api:gh", published_at=None, item_id="i0001")
    b = make_item(title="some/repo", url="https://github.com/some/repo", content="a repo",
                  source_id="api:gh2", published_at=None, item_id="i0002")

    result = cluster([a, b])

    assert len(result.groups) == 1


def test_merged_group_preserves_every_url_and_source(make_item) -> None:
    """Dedup compresses records; it must never destroy evidence."""
    items = [
        make_item(title="T", url=f"https://m{i}.example/x", content=ARTICLE,
                  source_id=f"rss:s{i}", item_id=f"i{i:04d}")
        for i in range(3)
    ]

    result = cluster(items)

    assert len(result.groups) == 1
    g = result.groups[0]
    assert len(g.all_urls) == 3
    assert len(g.source_ids) == 3
    assert g.member_item_ids == ["i0000", "i0001", "i0002"]


def test_merged_content_keeps_unique_paragraphs_from_each_source(make_item) -> None:
    """Cross-source merge keeps both texts, like Horizon's orchestrator does.

    Real shape: two feeds carry the same canonical article but different excerpts, so
    neither excerpt may be dropped.
    """
    canonical = "https://canonical.example/x"
    primary = make_item(
        title="T", url="https://a.example/x", canonical_url=canonical,
        source_id="rss:a", item_id="i0001",
        content="第一段：共同内容。\n第二段：只有 A 有的细节。",
    )
    secondary = make_item(
        title="T", url="https://b.example/x", canonical_url=canonical,
        source_id="rss:b", item_id="i0002",
        content="第一段：共同内容。\n第三段：只有 B 有的细节。",
    )

    result = cluster([primary, secondary])
    assert len(result.groups) == 1, "same canonical URL must merge"
    merged = result.groups[0].merged_content

    assert "只有 A 有的细节" in merged
    assert "只有 B 有的细节" in merged
    assert "来自 rss:b 的补充" in merged
    assert merged.count("第一段：共同内容。") == 1, "shared paragraph must not be duplicated"


def test_near_duplicates_differing_in_high_bits_still_merge(make_item) -> None:
    """Regression: candidate generation must not depend on *where* the bits differ.

    The first implementation bucketed on the top 16 bits and probed `top ^ delta` for
    delta in 0..3, which only tolerates differences in the low two bits of that block.
    Two hashes one bit apart at bit 63 landed in different buckets and were never
    compared -- the first real run reported a 0% merge rate because of it.
    """
    base = 0x0123_4567_89AB_CDEF
    a = make_item(title="OpenAI ships a model", url="https://a.example/x",
                  content="body a", source_id="rss:a", item_id="i0001")
    b = make_item(title="OpenAI ships a model", url="https://b.example/x",
                  content="body b", source_id="rss:b", item_id="i0002")

    # Two different hashes, one bit apart, differing in the HIGHEST bit.
    a = a.model_copy(update={"simhash": base, "content_sha256": "h1"})
    b = b.model_copy(update={"simhash": base ^ (1 << 63), "content_sha256": "h2"})

    result = cluster([a, b])

    assert len(result.groups) == 1, "a 1-bit difference at bit 63 must still be compared"


def test_high_bit_difference_among_three_bits_still_merges(make_item) -> None:
    """Distance 3 spread across the widest possible span must still be found."""
    base = 0x0F0F_0F0F_0F0F_0F0F
    other = base ^ (1 << 63) ^ (1 << 32) ^ (1 << 1)
    assert hamming(base, other) == 3

    a = make_item(title="Same headline here", url="https://a.example/y",
                  content="x", source_id="rss:a", item_id="i0001").model_copy(
        update={"simhash": base, "content_sha256": "h1"})
    b = make_item(title="Same headline here", url="https://b.example/y",
                  content="y", source_id="rss:b", item_id="i0002").model_copy(
        update={"simhash": other, "content_sha256": "h2"})

    assert len(cluster([a, b]).groups) == 1


def test_unrelated_articles_stay_separate(make_item) -> None:
    a = make_item(title="OpenAI ships reasoning model", url="https://a.example/1",
                  content=ARTICLE, source_id="rss:a", item_id="i0001")
    b = make_item(title="Nvidia unveils datacenter rack", url="https://b.example/2",
                  content="Nvidia unveiled a rack-scale design for gigawatt AI factories at OCP.",
                  source_id="rss:b", item_id="i0002")

    result = cluster([a, b])

    assert len(result.groups) == 2
    assert result.ambiguous == []


def test_canonical_url_is_used_as_identity(make_item) -> None:
    """Two different URLs pointing at one canonical article are one record."""
    a = make_item(title="A", url="https://site.example/post?utm_source=rss",
                  canonical_url="https://site.example/post", content="one",
                  source_id="rss:a", item_id="i0001")
    b = make_item(title="B", url="https://other.example/post",
                  canonical_url="https://site.example/post", content="two",
                  source_id="rss:b", item_id="i0002")

    result = cluster([a, b])

    assert len(result.groups) == 1
    assert "canonical_url" in result.groups[0].matched_by


def test_stats_are_reported_for_auditing(make_item) -> None:
    items = [
        make_item(title="T", url="https://m.example/x", content=ARTICLE, source_id="s1", item_id="i1"),
        make_item(title="T", url="https://n.example/x", content=ARTICLE, source_id="s2", item_id="i2"),
        make_item(title="Other", url="https://o.example/y", content="unrelated body text here",
                  source_id="s3", item_id="i3"),
    ]

    stats = cluster(items).stats

    assert stats["items_in"] == 3
    assert stats["groups"] == 2
    assert stats["merged_away"] == 1


def test_empty_input(make_item) -> None:
    result = cluster([])
    assert result.groups == []
    assert result.item_to_group == {}
