"""Offline fetcher tests: parsing logic only, no network.

Every fixture here reproduces a shape that actually caused a problem in the audit, so
these tests are regression guards for real bugs rather than invented cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aidaily.fetchers import resolve_adapter
from aidaily.fetchers.github_trending import GitHubTrendingFetcher
from aidaily.fetchers.jsonapi import (
    JsonApiFetcher,
    _map_record,
    _records,
    _runtime_params,
    _with_runtime_params,
)
from aidaily.fetchers.reddit import RedditFetcher, detect_login_wall, json_url_to_html
from aidaily.fetchers.rss import RssFetcher
from aidaily.http import HttpClient
from aidaily.models import SourceSpec

# --- the Google News shape: valid UTF-8 bytes, CJK content, 100 items -------------
GNEWS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0"><channel><title>"AI OR LLM" - Google 新闻</title>
<item><title>智谱发布法律模型 GLM-Legal</title>
<link>https://example.com/glm-legal</link>
<pubDate>Tue, 13 Oct 2026 09:48:17 GMT</pubDate>
<description>开放测试申请</description></item>
<item><title>英伟达开放 Vera Rubin 机架设计</title>
<link>https://example.com/vera-rubin</link>
<pubDate>Tue, 13 Oct 2026 08:00:00 GMT</pubDate>
<description>面向吉瓦级 AI 工厂</description></item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <title>Simon Willison</title>
 <entry><title>Things I learned</title>
  <link href="https://simonwillison.net/2026/Oct/13/things/"/>
  <updated>2026-10-13T04:05:06Z</updated>
  <summary>Some thoughts.</summary></entry>
</feed>"""

# ainewslog publishes oldest-first -- the ordering trap found during the audit
OLDEST_FIRST_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>AI Daily</title>
<item><title>Edition 2026-02-13</title><link>https://example.com/e1</link>
<pubDate>Fri, 13 Feb 2026 00:00:00 GMT</pubDate><description>old</description></item>
<item><title>Edition 2026-10-13</title><link>https://example.com/e2</link>
<pubDate>Tue, 13 Oct 2026 00:00:00 GMT</pubDate><description>new</description></item>
</channel></rss>"""

JSONFEED = """{"version":"https://jsonfeed.org/version/1.1","title":"DailyDawn · 每日黎明（中文）",
"items":[{"id":"2026-10-13","url":"https://dailydawn.dev/zh/2026-10-13","title":"2026-10-13",
"date_published":"2026-10-13T00:00:00+00:00","content_html":"<p>今日内容</p>","summary":"摘要"}]}"""

REDDIT_LISTING = """<html><body>
<div class="thing" data-fullname="t3_abc123" data-url="https://example.com/story"
     data-timestamp="1760000000000" data-score="42" data-comments-count="7"
     data-author="someone" data-subreddit="rust" data-permalink="/r/rust/comments/abc123/t/"
     data-nsfw="false">
  <a class="title may-blank" href="https://example.com/story">A rust story</a>
</div></body></html>"""

REDDIT_LOGIN_WALL = """<html><head><title>Welcome to Reddit</title></head><body>
<div class="login">Please log in</div>
<form action="/login/?reason=lor2&amp;dest=https%3A%2F%2Fold.reddit.com%2Fr%2Frust%2Ftop%2F"></form>
</body></html>"""

GITHUB_TRENDING_HTML = """<html><body>
<article class="Box-row">
  <h2><a href="/OpenBMB/MiniCPM-V">OpenBMB / MiniCPM-V</a></h2>
  <p>A GPT-4V level MLLM on your phone.</p>
  <span class="d-inline-block float-sm-right">1,234 stars today</span>
  <span itemprop="programmingLanguage">Python</span>
</article>
<article class="Box-row">
  <h2><a href="/vllm-project/vllm">vllm-project / vllm</a></h2>
  <p>Easy, fast inference.</p>
  <span class="d-inline-block float-sm-right">987 stars today</span>
  <span itemprop="programmingLanguage">Python</span>
</article></body></html>"""


@pytest.fixture
def spec_factory():
    def _make(**kw) -> SourceSpec:
        base = dict(
            source_id="rss:test", name="test", url="https://example.com/feed.xml",
            normalized_url="https://example.com/feed.xml", domain="example.com",
            category="media", source_type="rss", adapter="RssFetcher",
            found_in=["repo:file#key"], repositories=["repo"],
        )
        base.update(kw)
        return SourceSpec(**base)

    return _make


# =============================== RSS / Atom / JSON Feed ==========================
def test_rss_parses_bytes_and_preserves_cjk(spec_factory) -> None:
    """The Google News regression: parse bytes, and CJK titles must survive intact."""
    fetcher = RssFetcher(HttpClient())
    items = fetcher._parse_feed(spec_factory(), GNEWS_XML.encode("utf-8"))

    assert len(items) == 2
    assert items[0].title == "智谱发布法律模型 GLM-Legal"
    assert items[0].published_at == datetime(2026, 10, 13, 9, 48, 17, tzinfo=timezone.utc)


def test_rss_does_not_trust_entry_order(spec_factory) -> None:
    """ainewslog publishes oldest-first; nothing may assume entries[0] is newest."""
    fetcher = RssFetcher(HttpClient())
    items = fetcher._parse_feed(spec_factory(), OLDEST_FIRST_RSS.encode("utf-8"))

    dates = [i.published_at for i in items]
    assert all(d is not None for d in dates)
    assert max(dates) == datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert items[0].published_at < items[1].published_at, "feed really is oldest-first"


def test_atom_parses(spec_factory) -> None:
    fetcher = RssFetcher(HttpClient())
    items = fetcher._parse_feed(spec_factory(source_type="atom"), ATOM_XML.encode("utf-8"))

    assert len(items) == 1
    assert items[0].url == "https://simonwillison.net/2026/Oct/13/things/"
    assert items[0].published_at == datetime(2026, 10, 13, 4, 5, 6, tzinfo=timezone.utc)


def test_entry_without_date_stays_undated(spec_factory) -> None:
    """A missing date must stay missing -- never backfilled with the fetch time."""
    xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        "<item><title>No date here</title><link>https://example.com/x</link>"
        "<description>d</description></item></channel></rss>"
    )
    fetcher = RssFetcher(HttpClient())
    items = fetcher._parse_feed(spec_factory(), xml.encode("utf-8"))

    assert len(items) == 1
    assert items[0].published_at is None


def test_jsonfeed_parses(spec_factory) -> None:
    fetcher = RssFetcher(HttpClient())
    items = fetcher._parse_jsonfeed(
        spec_factory(source_type="jsonfeed", domain="dailydawn.dev"), JSONFEED.encode("utf-8")
    )

    assert len(items) == 1
    assert items[0].title == "2026-10-13"
    assert items[0].url == "https://dailydawn.dev/zh/2026-10-13"
    assert items[0].published_at == datetime(2026, 10, 13, tzinfo=timezone.utc)
    assert "今日内容" in (items[0].content_text or "")


def test_malformed_jsonfeed_returns_empty_not_crash(spec_factory) -> None:
    assert RssFetcher(HttpClient())._parse_jsonfeed(spec_factory(), b"not json") == []


# =============================== Reddit ==========================================
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://reddit.com/r/programming/top.json?t=day&limit=15",
         "https://old.reddit.com/r/programming/top/?t=day&limit=15"),
        ("https://www.reddit.com/r/LocalLLaMA/hot.json",
         "https://old.reddit.com/r/LocalLLaMA/hot/"),
        ("https://reddit.com/r/rust/rising.json", "https://old.reddit.com/r/rust/rising/"),
    ],
)
def test_reddit_json_url_is_mapped_to_html(url: str, expected: str) -> None:
    assert json_url_to_html(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://old.reddit.com/r/rust/",       # already HTML
        "https://reddit.com/user/spez/submitted.json",
        "https://example.com/r/rust/top.json",  # not reddit
    ],
)
def test_non_listing_reddit_urls_are_not_rewritten(url: str) -> None:
    """Returning None lets the caller use the URL as-is rather than fetching a guess."""
    assert json_url_to_html(url) is None


def test_login_wall_is_detected_despite_http_200() -> None:
    """The false positive that made the first probe call Reddit 'healthy'."""
    reason = detect_login_wall(REDDIT_LOGIN_WALL)
    assert reason is not None
    assert "登录" in reason


def test_real_listing_is_not_mistaken_for_a_wall() -> None:
    assert detect_login_wall(REDDIT_LISTING) is None


def test_reddit_listing_parses(spec_factory) -> None:
    items = RedditFetcher(HttpClient())._parse_listing(spec_factory(), REDDIT_LISTING)

    assert len(items) == 1
    assert items[0].title == "A rust story"
    assert items[0].metrics["score"] == 42
    assert items[0].metrics["comments"] == 7
    assert items[0].published_at == datetime.fromtimestamp(1760000000, tz=timezone.utc)


# =============================== GitHub Trending =================================
def test_github_trending_parses_and_has_no_date(spec_factory) -> None:
    """Trending is a star-delta window; claiming a publication date would be a lie."""
    spec = spec_factory(
        source_id="scrape:github-com-trending", domain="github.com",
        url="https://github.com/trending?since=daily", source_type="scrape",
        adapter="GitHubTrendingFetcher",
    )
    items = GitHubTrendingFetcher(HttpClient())._parse(spec, GITHUB_TRENDING_HTML)

    assert len(items) == 2
    assert items[0].title == "OpenBMB/MiniCPM-V"
    assert items[0].url == "https://github.com/OpenBMB/MiniCPM-V"
    assert items[0].metrics["stars_today"] == 1234
    assert items[0].metrics["language"] == "Python"
    assert all(i.published_at is None for i in items), "window source must stay undated"


# =============================== Generic JSON API ================================
def test_records_unwraps_common_envelopes() -> None:
    assert len(_records({"hits": [{"a": 1}]})) == 1
    assert len(_records([{"a": 1}, {"b": 2}])) == 2
    assert _records({"unexpected": 1}) == []
    assert _records("nope") == []
    # A list of plain IDs (HN Firebase) has no records to map -- correctly empty.
    assert _records([1, 2, 3]) == []


def test_hn_algolia_hit_maps(spec_factory) -> None:
    spec = spec_factory(source_id="api:hn-algolia-com-search", domain="hn.algolia.com")
    item = _map_record(spec, {
        "title": "Show HN: a thing", "url": "https://example.com/thing", "points": 120,
        "num_comments": 33, "author": "pg", "created_at": "2026-10-13T03:21:00Z",
        "objectID": "12345",
    })

    assert item is not None
    assert item.metrics["points"] == 120
    assert item.metrics["num_comments"] == 33
    assert item.native_id == "12345"
    assert item.published_at == datetime(2026, 10, 13, 3, 21, tzinfo=timezone.utc)


def test_huggingface_model_id_becomes_a_url(spec_factory) -> None:
    """HF returns a bare id such as `meta-llama/Llama-3`, not a URL.

    Regression: falling back to a bare None produced `.../models/None`.
    """
    spec = spec_factory(
        source_id="api:huggingface-co-models", domain="huggingface.co",
        url="https://huggingface.co/api/models?sort=likes7d",
    )
    item = _map_record(spec, {"modelId": "meta-llama/Llama-3", "likes": 500,
                              "lastModified": "2026-10-01T00:00:00.000Z"})

    assert item is not None
    assert item.url == "https://huggingface.co/models/meta-llama/Llama-3"
    assert item.title == "meta-llama/Llama-3"
    assert item.metrics["likes"] == 500


def test_huggingface_dataset_url_uses_the_datasets_path(spec_factory) -> None:
    spec = spec_factory(
        source_id="api:huggingface-co-datasets", domain="huggingface.co",
        url="https://huggingface.co/api/datasets?sort=likes7d",
    )
    item = _map_record(spec, {"id": "some/dataset", "likes": 12})
    assert item is not None
    assert item.url == "https://huggingface.co/datasets/some/dataset"


def test_v2ex_unix_timestamp_and_member(spec_factory) -> None:
    """Regression: V2EX names its unix-seconds field `created`, which was missing from
    the date-key list and silently dropped every date from that source."""
    spec = spec_factory(source_id="api:v2ex-com-topics-hot", domain="v2ex.com")
    item = _map_record(spec, {
        "title": "一个话题", "url": "https://www.v2ex.com/t/1", "replies": 9,
        "created": 1760000000, "member": {"username": "someone"},
        "node": {"title": "程序员"},
    })

    assert item is not None
    assert item.author == "someone"
    assert item.metrics["replies"] == 9
    assert item.published_at == datetime.fromtimestamp(1760000000, tz=timezone.utc)


def test_record_without_title_or_url_is_dropped(spec_factory) -> None:
    assert _map_record(spec_factory(), {"unrelated": True}) is None


# =============================== runtime query params ============================
def test_hn_algolia_gets_a_runtime_time_filter(spec_factory) -> None:
    """Regression: without a filter, Algolia returns all-time top stories.

    The first real run reported this source's newest item as seven months old because the
    bare endpoint is popularity-sorted, not time-sorted.
    """
    now = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)
    spec = spec_factory(
        source_id="api:hn-algolia-com-search", domain="hn.algolia.com",
        url="https://hn.algolia.com/api/v1/search",
    )
    url = _with_runtime_params(spec, now)

    assert url.startswith("https://hn.algolia.com/api/v1/search?")
    assert "tags=story" in url
    assert "hitsPerPage=60" in url
    cutoff = int((now - timedelta(hours=48)).timestamp())
    assert f"created_at_i%3E{cutoff}" in url or f"created_at_i>{cutoff}" in url


def test_runtime_params_are_empty_for_other_domains(spec_factory) -> None:
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    spec = spec_factory(domain="huggingface.co", url="https://huggingface.co/api/models")
    assert _runtime_params(spec, now) == {}
    assert _with_runtime_params(spec, now) == "https://huggingface.co/api/models"


def test_runtime_params_append_to_an_existing_query(spec_factory) -> None:
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    spec = spec_factory(
        domain="hn.algolia.com", url="https://hn.algolia.com/api/v1/search?query=llm"
    )
    url = _with_runtime_params(spec, now)
    assert url.count("?") == 1 and "&tags=story" in url


# =============================== adapter resolution ==============================
def test_explicit_unimplemented_adapter_is_not_silently_swapped(spec_factory) -> None:
    """The bug: an explicit request fell back to a generic parser and yielded a silent 0.

    `adapter: PyTrendsFetcher` on the Google Trends source was ignored, the generic JSON
    parser ran against an HTML page, and the run reported a healthy HTTP 200 with zero
    items -- a source that looked collected but contributed nothing.
    """
    spec = spec_factory(source_type="api", adapter="PyTrendsFetcher")
    assert resolve_adapter(spec) is None


def test_registry_placeholder_adapter_falls_back_by_type(spec_factory) -> None:
    assert resolve_adapter(spec_factory(source_type="api", adapter="ApiFetcher")) == "JsonApiFetcher"
    assert resolve_adapter(spec_factory(source_type="rss", adapter="ApiFetcher")) == "RssFetcher"
    assert resolve_adapter(spec_factory(source_type="scrape", adapter="HtmlFetcher")) is None


def test_implemented_adapter_is_used_as_named(spec_factory) -> None:
    assert resolve_adapter(spec_factory(adapter="GitHubTrendingFetcher")) == "GitHubTrendingFetcher"
    assert resolve_adapter(spec_factory(adapter="RedditFetcher")) == "RedditFetcher"
