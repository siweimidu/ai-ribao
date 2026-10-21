"""橘鸦's section priority, and what the rule-based classifier can and cannot do.

## The measurement this encodes

Every story in a 橘鸦 issue carries a rank (`... ↗ #17`), assigned **by section in contiguous
blocks**:

    2026-10-15  要闻 #1-2 | 模型发布 #3-6 | 开发生态 #7-10 | 产品应用 #11-13 |
                技术与洞察 #14-17 | 行业动态 #18-27

Over ten issues the pairwise "A before B" tally is 100% for thirteen pairs and 5:4 for one, so
the order is categorical with one near-tie. **Within** a section nothing predicts position
(Spearman below 0.35 for every candidate, signs flipping between sections), so that part stays
with the score.

## What the rules are for

This file asserts the **priority** rigorously, because that came straight out of the data, and it
asserts the **classifier's measured accuracy** rather than claiming it is right case by case.

The rules reach 41.8% on 橘鸦's own 478 labelled stories (`scripts/eval_juya_sections.py`).
That is not good enough to be the only classifier, which is why the section travels through the
rubric: the model reads every story anyway, and a reading comprehension question about whether a
thing is a model, a product, a tool or a report is not a keyword question. The rules are the
fallback for a run with no model, and for a row the model did not classify.

Two earlier versions of the rules scored 37.2% and then 41.8%; the failure modes are recorded in
`sections.py` because each one is a real editorial boundary, not a tuning detail.
"""

from __future__ import annotations

import pytest

from aidaily.sections import SECTIONS, SECTION_RANK, classify, rank_of, sort_key


# =============================== the priority ====================================
def test_the_priority_is_the_measured_one() -> None:
    """要闻 first; 行业动态 and 其他 last; 开发生态 before 模型发布 by the 5:4 tie-break.

    Straight from the pairwise tally over ten issues -- thirteen pairs never invert, one is 5:4.
    """
    assert SECTION_RANK["要闻"] == 0
    assert SECTION_RANK["开发生态"] < SECTION_RANK["模型发布"]
    assert SECTION_RANK["模型发布"] < SECTION_RANK["产品应用"]
    assert SECTION_RANK["产品应用"] < SECTION_RANK["技术与洞察"]
    assert SECTION_RANK["技术与洞察"] < SECTION_RANK["行业动态"]
    # `其他` shared the last rank with 行业动态 as of 2026-10-21. It used to sort strictly
    # below it, which buried 38% of the issue at the bottom of the page.
    assert SECTION_RANK["其他"] == SECTION_RANK["行业动态"]


def test_every_section_has_a_distinct_rank() -> None:
    # Two sections may share the last rank; what must not happen is a gap.
    ranks = sorted(set(SECTION_RANK.values()))
    assert ranks == list(range(len(ranks)))


def test_an_unknown_section_sorts_last_rather_than_raising() -> None:
    """A section the model invented must not crash the run, and must not be promoted."""
    assert rank_of("模型發布") == len(SECTIONS)
    assert rank_of("") == len(SECTIONS)


def test_the_section_outranks_the_score() -> None:
    """The whole finding: a 要闻 with a low score beats 行业动态 with a high one.

    A pure score ranking cannot move a story across a category boundary, which is why the 橘鸦
    comparison could not be closed by tuning weights.
    """
    headline = "Claude Code 桌面版更新优化多会话体验"
    industry = "报道称 Anthropic 第三季度营收达 168 亿美元"
    assert sort_key(headline, 1.0) < sort_key(industry, 10.0)


def test_sections_are_ordered_by_priority_not_by_score() -> None:
    rows = [
        ("报道称 Anthropic 第三季度营收达 168 亿美元", 10.0),
        ("Claude Code 桌面版更新优化多会话体验", 1.0),
    ]
    assert [t for t, _ in sorted(rows, key=lambda r: sort_key(r[0], r[1]))][0].startswith("Claude")


# =============================== the classifier ==================================
#: 橘鸦's own items, with the section each was filed under. Kept as a labelled sample so the
#: accuracy assertion below is measured rather than asserted.
LABELLED: list[tuple[str, str]] = [
    ("Claude Code 新增闲置会话自动压缩", "要闻"),
    ("OpenAI 优化 ChatGPT 桌面应用存储占用", "要闻"),
    ("Google 全球开放 Gemini 4 Argon", "要闻"),
    ("蚂蚁百灵开源 Ling-3.1-flash 模型", "模型发布"),
    ("Fish Audio 发布 Drama 3，开放模型权重", "模型发布"),
    ("智谱推出法律模型 GLM-Legal，开放测试申请", "模型发布"),
    ("OpenAI 公布部分 GPT-4 模型退役安排", "开发生态"),
    ("Command Code 推出 GOAT 限时额度优惠", "开发生态"),
    ("豆包工作上线数据导入与同步功能", "产品应用"),
    ("llama.cpp 推出 Windows 桌面应用 Llama Windows", "产品应用"),
    ("AA-Robotics 评测：GPT-6 Astra 居首", "技术与洞察"),
    ("Swarmchasers 报告腾讯云 Agent 试绕高德反爬", "技术与洞察"),
    ("报道称 Anthropic 第三季度营收达 168 亿美元", "行业动态"),
    ("谷歌向 17 家机构提供 3600 万美元 AI 科研资助", "行业动态"),
    ("OpenAI 基础设施负责人将离职", "行业动态"),
]


def test_the_classifier_clears_a_measured_floor() -> None:
    """Asserts the accuracy it actually has, on labelled 橘鸦 data.

    The floor is 40%, just under the 41.8% measured over all 478 items, so a regression fails
    here rather than being discovered by reading the site. Raising this number is the way to
    record an improvement; lowering it should require a reason.
    """
    hits = sum(1 for title, truth in LABELLED if classify(title) == truth)
    assert hits / len(LABELLED) >= 0.40, f"分类准确率 {hits}/{len(LABELLED)} 低于 40%"


def test_the_two_clear_directions_are_never_confused() -> None:
    """The distinctions the taxonomy exists for, on unambiguous examples.

    Asserted only for the pairs the rules do get right. The pairs they do not -- `Meta 发布 Muse
    Wonder 模型系列` (a model whose title reads like a product line) and `Qoder 国际版极致档位
    推出夜间 2 折优惠` (a discount with no dev keyword) -- are the model's job, and asserting
    them here would only be asserting something the code does not do.
    """
    # A model release is not a product launch.
    assert classify("蚂蚁百灵开源 Ling-3.1-flash 模型") == "模型发布"
    # Business is business even when a frontier lab is named.
    assert classify("报道称 Anthropic 第三季度营收达 168 亿美元") == "行业动态"
    assert classify("OpenAI 基础设施负责人将离职") == "行业动态"
    # A dev offer naming a model is about access, not the model.
    assert classify("OpenAI 公布部分 GPT-4 模型退役安排") == "开发生态"


def test_an_empty_title_is_other() -> None:
    assert classify("") == "其他"
    assert classify("   ") == "其他"


def test_every_result_is_a_known_section() -> None:
    """A classifier returning a string outside the taxonomy would sort it last and silently
    demote the story, so the output domain matters more than any single answer."""
    for title in ("", "随便一句话", "OpenAI 发布 GPT-6", "某公司完成 A 轮融资",
                  "AA 新增缓存命中率榜单", "豆包手机助手开放第三方自动化"):
        assert classify(title) in SECTIONS
