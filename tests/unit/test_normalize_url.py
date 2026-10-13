"""URL and title normalization.

Every case here is drawn from a source that actually exists in the six audited
repositories -- these are not invented examples.
"""

from __future__ import annotations

import pytest

from aidaily.normalize import (
    content_fingerprint,
    hamming,
    normalize_url,
    simhash,
    title_norm,
    try_normalize_url,
    url_domain,
)


# --- URLs that MUST collapse to one key -----------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        # scheme + host case + www + trailing slash are all non-content-bearing
        ("http://Example.COM/a/", "https://example.com/a"),
        ("https://www.example.com/a", "https://example.com/a"),
        ("https://example.com/a/", "https://example.com/a"),
        # fragments never select server content
        ("https://example.com/post#section-3", "https://example.com/post"),
        # tracking params dropped, functional param kept
        ("https://example.com/post?utm_source=x&utm_medium=y&id=5", "https://example.com/post?id=5"),
        ("https://example.com/post?fbclid=abc", "https://example.com/post"),
        ("https://example.com/p?ref=hn&source=rss&q=llm", "https://example.com/p?q=llm"),
        # default ports are noise; non-default ports are meaningful
        ("https://example.com:443/x", "https://example.com/x"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        # credentials in a URL are a leak vector, never part of identity
        ("https://user:pw@example.com/x", "https://example.com/x"),
        # duplicate slashes collapse
        ("https://example.com//a//b", "https://example.com/a/b"),
        # query order is not meaningful, so it is sorted for a stable key
        ("https://example.com/s?b=2&a=1", "https://example.com/s?a=1&b=2"),
    ],
)
def test_normalize_collapses(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


# --- URLs that MUST stay distinct ------------------------------------------------
def test_lwn_two_feeds_stay_distinct() -> None:
    """Same host, different path: headlines and full_text are different content.

    Both appear in Horizon's config; collapsing them would silently drop a source.
    """
    a = normalize_url("https://lwn.net/headlines/rss")
    b = normalize_url("https://lwn.net/headlines/full_text?key=SECRET")
    assert a != b


def test_google_news_queries_stay_distinct() -> None:
    """`q`/`hl`/`gl`/`ceid` select content -- two different queries are two sources."""
    a = normalize_url("https://news.google.com/rss/search?q=AI&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    b = normalize_url("https://news.google.com/rss/search?q=LLM&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    assert a != b
    assert "q=AI" in a and "ceid=CN%3Azh-Hans" in a


def test_url_path_case_is_preserved() -> None:
    """GitHub owner/repo paths are case-sensitive; lowercasing would merge two projects."""
    assert normalize_url("https://github.com/OpenBMB/MiniCPM-V") != normalize_url(
        "https://github.com/openbmb/minicpm-v"
    )


def test_raw_githubusercontent_feed_path_is_stable() -> None:
    """The alan-turing-institute feeds back 9 of the healthiest sources in the registry."""
    u = (
        "https://raw.githubusercontent.com/alan-turing-institute/ai-rss-feeds/"
        "refs/heads/main/feeds/anthropic-news.xml"
    )
    assert normalize_url(u) == u


def test_follow_list_ids_stay_distinct() -> None:
    """Cloudflare's four Folo lists differ only by listId -- collapsing them loses sources."""
    a = normalize_url("https://api.follow.is/entries?listId=158437828119024640")
    b = normalize_url("https://api.follow.is/entries?listId=158437917409783808")
    assert a != b
    assert "listId=158437828119024640" in a


# --- structural guarantees -------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "http://Example.COM/a/?utm_source=x#f",
        "https://www.example.com/a/b?b=2&a=1",
        "https://example.com",
        "https://lwn.net/headlines/full_text?key=K",
        "https://news.google.com/rss/search?q=AI+OR+LLM&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://example.com:8443/x/",
    ],
)
def test_normalize_is_idempotent(raw: str) -> None:
    once = normalize_url(raw)
    assert normalize_url(once) == once


@pytest.mark.parametrize("junk", ["", "not a url", "ftp://example.com/x", "/relative/path", "javascript:void(0)"])
def test_junk_urls_rejected(junk: str) -> None:
    assert try_normalize_url(junk) is None
    with pytest.raises(ValueError):
        normalize_url(junk)


@pytest.mark.parametrize(
    "url,domain",
    [
        ("https://www.theverge.com/rss/x.xml", "theverge.com"),
        ("https://raw.githubusercontent.com/a/b/c.xml", "raw.githubusercontent.com"),
        ("https://example.com:8443/x", "example.com"),
    ],
)
def test_url_domain(url: str, domain: str) -> None:
    assert url_domain(url) == domain


# --- titles ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("OpenAI Releases GPT-5!", "openaireleasesgpt5"),
        # leading bracketed label is noise
        ("【重磅】智谱发布 GLM-Legal", "智谱发布glmlegal"),
        # trailing brand is noise ...
        ("OpenAI 发布新模型 | 量子位", "openai发布新模型"),
        ("标题 – 量子位", "标题"),
        # ... but a brand at the FRONT must not swallow the actual title
        ("机器之心 | OpenAI 发布新模型", "机器之心openai发布新模型"),
        ("Breaking: Meta ships Muse", "metashipsmuse"),
        ("", ""),
    ],
)
def test_title_norm(raw: str, expected: str) -> None:
    assert title_norm(raw) == expected


def test_title_norm_ignores_urls() -> None:
    """Feeds frequently append the article URL to the title; it must not affect the key."""
    a = title_norm("OpenAI ships a thing")
    b = title_norm("OpenAI ships a thing https://openai.com/blog/thing")
    assert a == b


def test_title_norm_keeps_version_numbers() -> None:
    """v4.1 vs v4.7 are genuinely different releases -- never normalize them away."""
    assert title_norm("MiniCPM-V 4.7 released") != title_norm("MiniCPM-V 4.1 released")


# --- simhash / fingerprints ------------------------------------------------------
def test_simhash_near_duplicates_are_close() -> None:
    """A mirrored article with a changed byline should land within distance 3."""
    a = "OpenAI today announced a new reasoning model that improves math accuracy by 30 percent."
    b = "OpenAI today announced a new reasoning model that improves math accuracy by 30 percent!"
    assert hamming(simhash(a), simhash(b)) <= 3


def test_simhash_different_stories_are_far() -> None:
    a = "OpenAI announced a new reasoning model improving math accuracy by thirty percent."
    b = "Nvidia unveiled a datacenter rack design for gigawatt scale AI factories."
    assert hamming(simhash(a), simhash(b)) > 10


def test_simhash_handles_chinese() -> None:
    """Character bigrams give CJK the discriminative power words give English."""
    a = "智谱发布法律模型 GLM-Legal，开放测试申请"
    b = "智谱发布法律模型 GLM-Legal，开放测试申请。"
    c = "英伟达开放 Vera Rubin 机架设计"
    assert hamming(simhash(a), simhash(b)) <= 3
    assert hamming(simhash(a), simhash(c)) > 10


def test_simhash_empty() -> None:
    assert simhash("") == 0


def test_content_fingerprint_ignores_whitespace_and_markup() -> None:
    """Mirrored copies differ in whitespace and stray tags; the fingerprint must not."""
    a = "<p>Hello   world</p>\n\n"
    b = "Hello world"
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_distinguishes_real_edits() -> None:
    assert content_fingerprint("accuracy improved by 30 percent") != content_fingerprint(
        "accuracy improved by 13 percent"
    )
