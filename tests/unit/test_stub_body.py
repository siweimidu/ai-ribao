"""A body too short to identify anything must not become the identity.

`content_sha256` is an exact dedup key with no time window, so two items with the same body are
merged outright. Measured 2026-10-23: every InfoQ RSS entry carries the same template summary,
which strips to the six characters `点击查看原文>`. All twelve of that day entries hashed
identically, were merged into one unit, and the issue published a single event whose headline was
about API gateways while its facts listed Qwen kernels, a DeepSeek funding round and a Huawei
assistant review. The link the reader clicked was one of the twelve, so it went to an article the
entry never described.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.ingest import _MIN_IDENTIFYING_BODY, _is_boilerplate, normalize_raw
from aidaily.models import RawItem, SourceSpec

SPEC = SourceSpec(
    source_id="rss:infoq-cn",
    name="InfoQ",
    url="https://www.infoq.cn/feed",
    normalized_url="https://www.infoq.cn/feed",
    domain="infoq.cn",
    category="技术",
    source_type="rss",
    adapter="RssFetcher",
)

#: Exactly what the feed carries: a wrapper div around a "read the original" link.
STUB = (
    '<div align="right"><a href="https://www.infoq.cn/article/abc123?utm_source=rss">'
    "点击查看原文&gt;</a></div>"
)


def _item(title: str, summary: str = STUB) -> RawItem:
    return RawItem(
        source_id="rss:infoq-cn",
        title=title,
        url="https://www.infoq.cn/article/x",
        summary=summary,
        content_text=None,
        published_at=None,
    )


def test_a_stub_body_falls_back_to_the_title() -> None:
    """The whole bug: twelve different stories sharing one six-character body."""
    a = normalize_raw(_item("Qwen 线性注意力优化"), SPEC, now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    b = normalize_raw(_item("DeepSeek 完成千亿融资"), SPEC, now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert a.content_sha256 != b.content_sha256
    assert a.simhash != b.simhash


def test_a_real_body_still_decides_the_identity() -> None:
    """Two different headlines over the same article text are still one record."""
    body = "<p>" + "这是一篇足够长的正文，用来确认长正文仍然决定指纹。" * 3 + "</p>"
    a = normalize_raw(_item("标题一", body), SPEC)
    b = normalize_raw(_item("标题二", body), SPEC)
    assert a.content_sha256 == b.content_sha256


def test_the_same_headline_over_a_stub_still_merges() -> None:
    """The fallback must not disable exact dedup -- same story, same key."""
    a = normalize_raw(_item("同一篇报道"), SPEC)
    b = normalize_raw(_item("同一篇报道"), SPEC)
    assert a.content_sha256 == b.content_sha256


def test_the_threshold_sits_above_every_stub_seen() -> None:
    for stub in ("点击查看原文>", "阅读全文", "Read more", "点击查看原文"):
        assert len(stub) < _MIN_IDENTIFYING_BODY, stub


def test_the_threshold_sits_below_a_real_lede() -> None:
    """Measured over 4868 real bodies: 1st percentile 16 chars, median 115.

    A 24-character floor catches the 3.2% that are stubs and leaves the rest alone.
    """
    lede = "InfoQ 中文站发布了一篇关于 Qwen 线性注意力优化的文章，介绍了具体的实现细节与测试结果"
    assert len(lede) >= _MIN_IDENTIFYING_BODY


def test_the_threshold_does_not_swallow_ordinary_summaries() -> None:
    """3.2% of the corpus is shorter than 24 chars; the floor must not exceed that tail."""
    assert _MIN_IDENTIFYING_BODY <= 40


#: Exactly what CNBC ships under four different headlines naming four different companies.
CNBC_STUB = "These are the stocks posting the largest moves premarket."


def test_boilerplate_is_recognised_even_when_it_is_long_enough() -> None:
    """57 characters passes the length test and still identifies nothing."""
    assert len(CNBC_STUB) > _MIN_IDENTIFYING_BODY
    assert _is_boilerplate(CNBC_STUB, "Stocks making the biggest moves premarket: CoreWeave")


def test_four_headlines_over_one_boilerplate_get_four_fingerprints() -> None:
    """The bug as the reader saw it: one event, four companies, none of them in the title."""
    names = ("CoreWeave", "Bank of America", "Delta Air Lines", "Haemonetics")
    hashes = set()
    for name in names:
        item = _item(f"Stocks making the biggest moves premarket: {name}", CNBC_STUB)
        hashes.add(normalize_raw(item, SPEC).content_sha256)
    assert len(hashes) == len(names)


def test_a_real_lede_is_not_treated_as_boilerplate() -> None:
    body = "OpenAI released a new video model today that generates sixty second clips."
    assert not _is_boilerplate(body, "OpenAI ships Sora 2")


def test_a_body_that_restates_the_title_is_boilerplate() -> None:
    """Hashing the title twice adds nothing to identity."""
    title = "Qwen 线性注意力优化实践"
    assert _is_boilerplate(title, title)


def test_an_empty_body_is_boilerplate() -> None:
    assert _is_boilerplate("", "任意标题")
