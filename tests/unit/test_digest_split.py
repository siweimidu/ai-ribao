"""A digest issue is a container of stories, not a story.

All three feeds the user named publish one entry per ISSUE:

  daily.juya.uk/rss.xml        `AI 早报 2026-10-22` -- 32 stories in one body
  hex2077.dev/rss-zh-CN.xml    a weekly issue of prose plus per-story headings
  aihot.news/feed/daily.xml    one issue per day

Kept whole, each is filtered as a roundup and every story inside is lost. Split, each story
becomes its own candidate carrying the ORIGINAL publisher link -- so the page shows `openai.com`
rather than `juya.uk`, which is what was asked for.

`aihot.news/feed/full.xml` publishes one entry per story and must NOT be split.
"""

from __future__ import annotations

import pytest

from aidaily.digest_split import is_digest_feed, is_digest_title, split_digest

JUYA_BODY = """
<h2 id="s1">概览</h2>
<h3 id="s2">要闻</h3>
<ul>
<li>Claude Duet 开放研究预览，主动提醒并在后台办事
<a href="https://claude.com/resources/articles/claude-duet">↗</a> <code>#1</code></li>
<li>Tibo 称 Codex 登录用户缓存永久保留
<a href="https://developers.openai.com/api/docs/guides/prompt-caching">↗</a> <code>#2</code></li>
</ul>
<h3 id="s3">开发生态</h3>
<ul>
<li>LiteLLM 遭供应链攻击，恶意版本下架
<a href="https://docs.litellm.ai/blog/security-incident">↗</a> <code>#3</code></li>
</ul>
"""


def test_a_digest_body_splits_into_its_stories() -> None:
    stories = split_digest(JUYA_BODY)
    assert len(stories) == 3
    assert stories[0].title == "Claude Duet 开放研究预览，主动提醒并在后台办事"
    assert stories[0].section == "要闻"


def test_each_story_carries_the_original_publisher_link() -> None:
    """The whole point: the digest link must never be the source shown."""
    stories = split_digest(JUYA_BODY)
    urls = [s.url for s in stories]
    assert "https://claude.com/resources/articles/claude-duet" in urls
    assert not any("juya" in u for u in urls)


def test_an_unrecognised_body_yields_nothing() -> None:
    """So the caller can fall back to keeping the item whole instead of dropping it."""
    assert split_digest("<p>just prose, no story list</p>") == []
    assert split_digest("") == []


def test_navigation_sections_are_not_stories() -> None:
    body = '<h3>相关链接</h3><ul><li>Some link <a href="https://example.com/a">↗</a></li></ul>'
    assert split_digest(body) == []


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://daily.juya.uk/rss.xml", True),
        ("https://hex2077.dev/rss-zh-CN.xml", True),
        ("https://aihot.news/feed/daily.xml", True),
        ("https://aihot.news/feed/weekly.xml", True),
        ("https://aihot.news/feed/full.xml", False),
        ("https://openai.com/news/rss.xml", False),
    ],
)
def test_only_issue_feeds_are_split(url: str, expected: bool) -> None:
    """`full.xml` is one entry per story; splitting it would parse bodies at random."""
    assert is_digest_feed(url) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("AI 早报 2026-10-22", True),
        ("2026-10-22", True),
        ("AIHOT 日报 · 2026-10-22", True),
        ("何夕2077 AI 深度信号周报 2026 W42", True),
        ("Claude Duet 开放研究预览", False),
        ("vllm-project/vllm", False),
    ],
)
def test_issue_titles_are_recognised(title: str, expected: bool) -> None:
    assert is_digest_title(title) is expected
