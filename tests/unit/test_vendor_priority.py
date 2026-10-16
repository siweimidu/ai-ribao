"""Chinese model vendors rank first. Explicit user policy, with a measured boundary.

> 国产几家模型 DeepSeek，GLM，kimi，MiniMax，Qwen，豆包，阶跃星辰，元宝的优先级要放在第一位，
> 尤其是 DeepSeek，GLM，kimi，这三家调高优先级，DeepSeek 最高优先级，Kimi 其次，然后是 GLM

The ordering is carried by the size of the multipliers, not by tiers: a flat tier would rank
DeepSeek, Kimi and GLM together and lose the "especially these three" part of the instruction.

The boundary that matters is **subject versus dependency**. `UCSD 用 DeepSeek V4.1-Flash 做机械臂`
is a robotics story that happens to use DeepSeek; boosting it would put it above DeepSeek's own
announcements, which is the opposite of what was asked for.
"""

from __future__ import annotations

import pytest

from aidaily.vendor_priority import VENDOR_TIERS, components, vendor_priority


# =============================== the requested order =============================
def test_the_three_named_vendors_outrank_the_rest() -> None:
    """DeepSeek > Kimi > GLM > everything else named."""
    assert VENDOR_TIERS["deepseek"] > VENDOR_TIERS["kimi"] > VENDOR_TIERS["glm"]
    for other in ("minimax", "qwen", "doubao", "stepfun", "yuanbao"):
        assert VENDOR_TIERS["glm"] > VENDOR_TIERS[other], other


def test_deepseek_is_the_highest() -> None:
    assert VENDOR_TIERS["deepseek"] == max(VENDOR_TIERS.values())


@pytest.mark.parametrize("title, vendor", [
    ("DeepSeek 网页及 API 出现中断", "deepseek"),
    ("深度求索发布新模型", "deepseek"),
    ("Kimi 发布 K2 新版本", "kimi"),
    ("月之暗面完成新一轮融资", "kimi"),
    ("智谱推出 GLM-5 并开源权重", "glm"),
    ("MiniMax 入驻天猫，开售三档订阅方案", "minimax"),
    ("阿里千问推出个人 Agent", "qwen"),
    ("豆包手机助手将开放第三方自动化", "doubao"),
    ("阶跃星辰开放 Step 5 Preview 权重", "stepfun"),
])
def test_each_listed_vendor_is_recognised_as_the_subject(title: str, vendor: str) -> None:
    factor, got = vendor_priority(title)
    assert got == vendor
    assert factor == VENDOR_TIERS[vendor]


def test_the_priority_order_is_what_a_headline_gets() -> None:
    """End to end through the public function, so the ordering is asserted where it is used."""
    ordered = [
        vendor_priority(t)[0]
        for t in ("DeepSeek 发布新模型", "Kimi 发布新模型", "智谱发布 GLM-5", "MiniMax 发布新模型")
    ]
    assert ordered == sorted(ordered, reverse=True)


# =============================== the boundary ====================================
@pytest.mark.parametrize("title", [
    "UCSD 用 DeepSeek V4.1-Flash 让开源权重模型零样本操作真实机械臂",
    "基于 Qwen 的微调实践：从零到一",
    "OpenAI 发布 GPT-6，性能超越 DeepSeek",
    "对比 Kimi 与 Claude 的长上下文表现",
    "使用 GLM-5 构建企业知识库",
])
def test_a_dependency_is_not_a_subject(title: str) -> None:
    """The measured false-positive shape. Boosting these would rank other people's news about
    a tool above the tool's own announcements."""
    factor, vendor = vendor_priority(title)
    assert factor == 1.0, f"被误判为主体：{title} -> {vendor}"
    assert vendor == ""


def test_a_subject_mention_wins_over_a_dependency_mention() -> None:
    """One mention as the subject is enough, even when another mention is a comparison."""
    factor, vendor = vendor_priority("DeepSeek 发布 V4，性能超越 GPT-6")
    assert vendor == "deepseek"
    assert factor == VENDOR_TIERS["deepseek"]


def test_an_unlisted_vendor_is_untouched() -> None:
    for title in ("Anthropic 发布 Claude 新版本", "Google 开放 Gemini 4 Argon", "Meta 发布 Muse"):
        assert vendor_priority(title) == (1.0, "")


def test_latin_names_do_not_fire_inside_other_words() -> None:
    """`glm` must not match inside a longer token."""
    assert vendor_priority("The glamorous world of AI")[0] == 1.0


def test_a_headline_naming_two_vendors_takes_the_higher() -> None:
    """Taking the highest preserves the priority the user set; an average would equalise
    them, which is the one outcome the instruction rules out."""
    factor, vendor = vendor_priority("DeepSeek 与 Kimi 联合发布新模型")
    assert vendor == "deepseek"
    assert factor == VENDOR_TIERS["deepseek"]


def test_components_carry_the_audit_trail() -> None:
    comp = components("DeepSeek 网页及 API 出现中断")
    assert comp["vendor_priority"] == VENDOR_TIERS["deepseek"]
    assert comp["vendor_subject"] == "deepseek"
    assert components("Anthropic 发布新版本")["vendor_subject"] == ""


def test_it_handles_an_empty_title() -> None:
    assert vendor_priority("") == (1.0, "")
