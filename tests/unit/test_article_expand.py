"""A daily issue is twenty stories, not one line.

Measured 2026-10-20: `ainewslog` contributed 480 feed items whose median body was 92 characters.
The feed entry is the *issue*; the news is inside the issue, one request away. This module pins
the split against a page captured from the real site, so a change in that markup is noticed here
instead of silently costing twenty stories a day.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.article import split_article
from aidaily.expand import looks_like_issue
from aidaily.models import RawItem

#: The structure of one real issue, reduced to what the splitter keys on. `来源-<credit>` ends
#: each story; the lines between two credit lines form that story.
ISSUE_HTML = """
<html><body>
<h1>AI 日报 — 2026-10-19 | AI Daily</h1>
<p>多家巨头本月或发新前沿模型，新基准与开放移动智能体环境推进智能体评测训练。</p>
<p>涵盖 20 条 AI 新闻</p>
<h2>🔥 今日焦点</h2>
<h3>1. Anthropic、Google、OpenAI 或于本月推出新的前沿模型</h3>
<p>有报道称，三家可能在月底前推出新的前沿模型。</p>
<p>来源-reddit</p>
<h3>2. OpenMobile-2 发布开放移动智能体及可扩展训练环境</h3>
<p>OpenMobile-2 提供接近前沿水平的移动智能体。</p>
<p>来源-huggingface</p>
<h2>📰 重点报道</h2>
<h3>基准测试与智能体评估</h3>
<h3>LiveMACE 基准在动态演进市场中评估 LLM 智能体</h3>
<p>— 一个过程感知基准使用实时金融市场作为测试平台。</p>
<p>来源-huggingface</p>
<h3>多模态、具身 AI 与 3D</h3>
<h3>VLM 通过单图像观测学习思考与探索 3D 环境</h3>
<p>— 该论文训练视觉语言模型从单图像观测中推理。</p>
<p>来源-huggingface</p>
<h3>Scene-Designer 学习面向智能体式 3D 场景生成的设计智能</h3>
<p>— 利用设计与批判经验生成连贯的 3D 室内场景。</p>
<p>来源-github</p>
</body></html>
"""


def test_every_story_is_extracted() -> None:
    stories = split_article(ISSUE_HTML)
    assert len(stories) == 5, [s.title for s in stories]


def test_a_section_heading_is_not_a_story() -> None:
    """`基准测试与智能体评估` labels a group; taking it as a title desynchronised the rest.

    The first version of this splitter returned 5 stories from a page holding 21, because it
    read the section heading as a title and then shifted every later story up by one line.
    """
    titles = [s.title for s in split_article(ISSUE_HTML)]
    assert "基准测试与智能体评估" not in titles
    assert "多模态、具身 AI 与 3D" not in titles


def test_the_credit_line_is_recorded() -> None:
    stories = split_article(ISSUE_HTML)
    assert stories[0].source == "reddit"
    assert stories[2].source == "huggingface"


def test_the_numbered_prefix_is_removed() -> None:
    stories = split_article(ISSUE_HTML)
    assert not stories[0].title.startswith("1.")


def test_the_dateline_is_not_a_story() -> None:
    titles = [s.title for s in split_article(ISSUE_HTML)]
    assert not any(t.startswith("AI 日报 —") for t in titles)


def test_a_page_that_is_not_a_roundup_yields_nothing() -> None:
    """Returning [] lets the caller keep the original item, which is never worse."""
    assert split_article("<html><body><p>一条普通新闻</p></body></html>") == []


@pytest.mark.parametrize(
    "title,body,expected",
    [
        ("AI 日报 — 2026-10-19", "一句话摘要", True),
        ("AI Daily — 2026-10-19", "", True),
        ("Gemini 4 发布", "一句话", False),
        # A long body already carries the news; fetching again would duplicate it.
        ("AI 日报 — 2026-10-19", "字" * 2000, False),
    ],
)
def test_looks_like_issue(title: str, body: str, expected: bool) -> None:
    item = RawItem(
        source_id="rss:x",
        title=title,
        url="https://example.com/a",
        summary=body,
        content_text=body,
        published_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    assert looks_like_issue(item) is expected
