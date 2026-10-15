"""Is this story *about* AI, or does it merely mention it?

Every assertion here comes from a measured failure. The digest was compared against
`daily.juya.uk` for 2026-10-14 and shared only six of its stories; of the digest's top twenty,
five were AI stories. The rest included an Apple smart speaker, Xbox game ports, Ray-Ban
glasses, a DLSS patch, and V3EX chatter about mortgage debt and splitting a Wi-Fi network into
two bands -- all scoring 0.36, level with real AI news.

So the cases below are not invented. Each one either appeared in that run or is the boundary
case the fix has to hold.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aidaily.focus import focus_multiplier
from aidaily.models import Event, SourceSpec

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)


def make_event(title: str, source_ids: tuple[str, ...] = ("rss:theverge",)) -> Event:
    return Event(
        event_id="e1", title=title, member_item_ids=["i1"], primary_item_id="i1",
        source_ids=list(source_ids), all_urls=["https://example.com/a"],
        independent_source_count=2, first_seen_at=NOW, last_updated_at=NOW,
        published_range=(NOW, NOW), evidence_level="multi_source",
    )


def make_source(source_id: str, category: str) -> SourceSpec:
    return SourceSpec(
        source_id=source_id, name=source_id, url="https://example.com/feed",
        normalized_url="https://example.com/feed", domain="example.com",
        category=category, source_type="rss", adapter="RssFetcher",
        found_in=["repo:file#key"], repositories=["repo"],
    )


SOURCES = {
    s.source_id: s
    for s in (
        make_source("rss:theverge", "media"),
        make_source("rss:deepmind-google-blog", "lab-blog"),
        make_source("rss:v2ex", "community"),
        make_source("rss:hn", "community"),
    )
}


def focus_of(title: str, sources: tuple[str, ...] = ("rss:theverge",)) -> float:
    _, comp = focus_multiplier(make_event(title, sources), SOURCES)
    return comp["focus"]


# =============================== must be AI ======================================
@pytest.mark.parametrize("title", [
    "Gemini 4 Argon 向全球 Google AI Pro 和 Ultra 订阅者开放",
    "阶跃星辰开放 Step 5 Preview 权重",
    "库克：苹果智能接入阿里千问大模型，10月底在中国发布测试版本",
    "LFM2.5-24B-A2B: Built for fast on-device agents",
    "EMNLP 2026 | 大模型推理如何再快一步？SpecTr-GBV 统一多草稿与块验证",
    "Eight states sue OpenAI, saying ChatGPT isn't safe for children",
    "DeepSeek Suffers Nearly Five-Hour AI Service Outage",
    "人工神经网络如何自主构建学习机制",
    "Meta打出AI翻身牌：新模型并肩行业巨头",
    "英伟达开源 Run:ai 平台，AI 算力编排与 GPU 调度下沉到社区",
])
def test_ai_stories_are_recognised(title: str) -> None:
    """The last three were false negatives in an earlier revision, each for a different
    reason: a plural (`networks`), a missing term (`新模型`), and treating bare `AI` as
    neutral when it accompanies a named change."""
    assert focus_of(title) >= 0.6, f"被判为非 AI：{title}"


# =============================== must not be AI ==================================
@pytest.mark.parametrize("title", [
    "Apple 发布 7 英寸智能音箱 HomeView，售价 299 美元并搭载 Siri AI",
    "Xbox is officially embracing the chaos of AI-powered game ports",
    "作者体验 Ray-Ban Meta Audio 眼镜后表示不怀念摄像头",
    "DLSS 5 在《霍格沃茨之遗》中首秀时效果被调弱",
    "Mia Goth 团队称 Instagram 放任其 AI 伪造图片传播令人费解",
    "Epic shifts to 'AI-accelerated development' for upcoming Disney titles",
    "西安杭州两套房资不抵债，楼主纠结是否割肉止损",
    "网友将家中 Wi-Fi 2.4G 与 5G 拆分为两个网络",
    "作者展示基于十二进制的 XY 音乐记谱法",
])
def test_non_ai_stories_are_demoted(title: str) -> None:
    """Every one of these appeared in the measured top twenty of a real run."""
    assert focus_of(title) < 0.45, f"被判为 AI 相关：{title}"


def test_a_bare_ai_cannot_carry_a_story() -> None:
    """The rule that fixed "Show HN: a Mac budgeting app whose AI models run on-device".

    It scored 0.89 on the word `AI` alone, promoting a personal-finance app into the AI band.
    Named models and techniques are what distinguish the two cases, so evidence consisting
    only of `AI` is capped.
    """
    assert focus_of("Show HN: Pulse Local, a Mac budgeting app whose AI models run on-device") < 0.6
    # And the same word next to a named model is not capped.
    assert focus_of("Show HN: a tool that runs GPT-4 locally") >= 0.6


# =============================== the source signal ===============================
def test_an_ai_only_source_amplifies_but_never_substitutes() -> None:
    """Measured: `MIT 林肯实验室主办新兴生物技术国家安全委员会路演` scored focus 1.00 under
    `max(headline, source)` because its category is `lab-blog`.

    A category says what a publication is *for*, not what an article is *about* -- `lab-blog`
    contains MIT Lincoln Laboratory, which covers biotech. So a lab source must raise a
    borderline headline, not certify a non-AI one.
    """
    from_lab = focus_of("MIT 林肯实验室主办新兴生物技术国家安全委员会路演",
                        ("rss:deepmind-google-blog",))
    assert from_lab < 0.45, "实验实验室来源不得为一条非 AI 内容作担保"

    same_story_general = focus_of("MIT 林肯实验室主办新兴生物技术国家安全委员会路演", ("rss:hn",))
    assert from_lab >= same_story_general, "AI 来源应当有正向放大作用"


def test_a_general_source_does_not_certify() -> None:
    """Xbox and DLSS scored 0.75 because `media` counted as a mixed AI source."""
    for title in ("Xbox is officially embracing the chaos of AI-powered game ports",
                  "DLSS 5 gets toned down for its Hogwarts Legacy debut"):
        assert focus_of(title, ("rss:theverge",)) < 0.45


# =============================== the multiplier ==================================
def test_the_multiplier_never_reaches_zero() -> None:
    """Demote, never delete: a quiet day must still print, and a borderline item must still be
    able to lead if it is genuinely the day's biggest thing."""
    multiplier, _ = focus_multiplier(make_event("西安杭州两套房资不抵债"), SOURCES)
    assert multiplier > 0.15, "不得归零 —— 降权而非删除是本项目的规则"
    assert multiplier < 0.6, "但必须明显降权"


def test_the_ranking_consequence_is_what_matters() -> None:
    """Asserts the outcome, not an arbitrary threshold.

    The earlier version of this file required `multiplier < 0.4` for a non-AI item, a number
    picked by hand. What the digest actually needs is that a non-AI story with **equal or
    greater** heat ends up below an AI story -- that is the ordering the reader sees, and it
    is robust to tuning the floor.
    """
    def final(title: str, heat: float, sources=("rss:theverge",)) -> float:
        mult, _ = focus_multiplier(make_event(title, sources), SOURCES)
        return heat * mult

    # Same heat, so only relevance separates them.
    ai = final("OpenAI releases GPT-6", 0.40)
    chatter = final("西安杭州两套房资不抵债，楼主纠结是否割肉止损", 0.40)
    consumer = final("Apple 发布 7 英寸智能音箱 HomeView，售价 299 美元", 0.40)

    assert ai > chatter * 2, "非 AI 的社区闲聊必须被拉开两倍以上"
    assert ai > consumer * 2, "非 AI 的消费电子必须被拉开两倍以上"

    # And a non-AI story must not out-rank an AI story even with a large heat advantage,
    # because heat is exactly the signal that let these items through in the first place.
    hot_chatter = final("网友将家中 Wi-Fi 2.4G 与 5G 拆分为两个网络", 0.80)
    assert ai > hot_chatter, "热度再高也不能让一条与 AI 无关的内容压过 AI 新闻"


def test_an_ai_story_is_left_alone() -> None:
    """The source must not *reduce* an unambiguous headline.

    An earlier revision multiplied by `(0.55 + 0.45 * source)`, so `OpenAI releases GPT-6` on
    The Verge scored 0.89 -- being published by a general outlet treated as evidence against
    a story being AI news, which it is not.
    """
    multiplier, comp = focus_multiplier(make_event("OpenAI releases GPT-6"), SOURCES)
    assert multiplier == pytest.approx(1.0)
    assert comp["focus"] == pytest.approx(1.0)


def test_it_works_without_source_information() -> None:
    """A caller with no registry still gets sane numbers -- weaker, but never in the dangerous
    direction: it can under-promote an AI story, not promote a non-AI one."""
    ai, _ = focus_multiplier(make_event("Gemini 4 Argon 开放"), None)
    off, _ = focus_multiplier(make_event("网友将家中 Wi-Fi 拆分"), None)
    assert ai > off
    assert 0 < off < 1


def test_components_are_reported_for_the_audit_trail() -> None:
    """A placement has to be explainable, or tuning is guesswork."""
    _, comp = focus_multiplier(make_event("OpenAI releases GPT-6"), SOURCES)
    for key in ("focus", "focus_headline", "focus_source", "focus_multiplier"):
        assert key in comp
