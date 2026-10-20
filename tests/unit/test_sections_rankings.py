"""Rankings and forward-looking announcements are not model releases.

On 2026-10-19 the digest led with `豆包登顶通用大模型人气周榜第5位` under 要闻, and two
`MiniMax-M3.1-Flash 即将发布` items sat in 模型发布 among the releases that actually shipped.

Two rules were missing:

* **rankings** — `榜单` was captured by the research matcher and 要闻 accepted anything the model
  called important, so a position change read as a headline. A ranking is 格局 news.
* **forward-looking announcements** — the release-verb matcher sees 发布 in `即将发布` and files
  it as a release that happened. It has not happened.
"""

from __future__ import annotations

import pytest

from aidaily.sections import classify


@pytest.mark.parametrize(
    "title",
    [
        "豆包登顶通用大模型人气周榜第5位 ChatGPT回落",
        "Arena 2026 年第 42 周 AI 大模型周榜：kimi-k3-max 首进代码榜前十",
        "某模型登顶 OpenRouter 用量榜第一",
        "豆包以 18% 份额位列第一",
    ],
)
def test_a_ranking_belongs_to_industry_news(title: str) -> None:
    """A position change is about the landscape, not about one model shipping."""
    assert classify(title) == "行业动态"


@pytest.mark.parametrize(
    "title",
    [
        "MiniMax-M3.1-Flash 即将发布",
        "MiniMax 正准备发布 MiniMax-M3.1-Flash",
        "某厂预告新一代模型将于下月上线",
    ],
)
def test_an_announced_release_is_not_a_release(title: str) -> None:
    """`即将发布` contains 发布 but nothing has shipped."""
    assert classify(title) == "行业动态"


@pytest.mark.parametrize(
    "title",
    [
        "DeepSeek 发布 V4.1-Flash-1017",
        "可灵AI新一代模型Kling 4.0正式上线",
        "MiniMax-M3.1-Flash 正式发布",
    ],
)
def test_a_real_release_is_still_a_model_release(title: str) -> None:
    """The guard must not swallow the releases themselves."""
    assert classify(title) == "模型发布"


def test_a_new_benchmark_is_still_research() -> None:
    """`榜单` in the sense of a new evaluation method stays in 技术与洞察."""
    assert classify("AA 新增缓存命中率与任务成本对比榜单") == "技术与洞察"
