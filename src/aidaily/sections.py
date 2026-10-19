"""the reference's section taxonomy and priority, reverse-engineered from its own numbering.

## What the data showed

Every story in a reference issue carries a rank (`... ↗ #17`) running 1..N across the issue, and the
ranks are handed out **by section, in contiguous blocks**:

    2026-10-15  要闻 #1-2 | 模型发布 #3-6 | 开发生态 #7-10 | 产品应用 #11-13 |
                技术与洞察 #14-17 | 行业动态 #18-27

So the ordering is categorical, not scored. Over ten issues the pairwise "A before B" tally is
100% for thirteen pairs and 5:4 for exactly one (`开发生态` vs `模型发布`), which gives a total
order. **Within** a section, no title feature predicts position -- Spearman against position was
below 0.35 for every candidate and the signs flipped between sections (`含数字` was +0.34 in
模型发布 and -0.24 in 开发生态), so that part is editorial judgement and is left to the score.

## Why this is worth reproducing

Getting the section right reproduces the coarse order deterministically -- a story 参考站 put in
要闻 and this pipeline ranked 47th cannot be fixed by tuning a weight, because the difference is
categorical. The section is therefore the ranking's primary key, ahead of heat.

## The categories, as 参考站 uses them

Read off its own examples rather than invented; each boundary below is one that actually occurs.

* **要闻** -- a major lab changing something the reader must know today. Not only models:
  `Claude Code 桌面版更新`, `OpenAI 优化 ChatGPT 桌面应用存储占用`, `Codex 第 8 天安排`.
* **开发生态** -- developer-facing access, tooling and pricing: `OpenCode Go 上线 Gemini 4
  Argon`, `Qoder 极致档位夜间 2 折`, `GPT-4 模型退役安排`, `OpenTelemetry 导出`,
  `限时额度优惠`. **Credits and pricing belong here, not in 行业动态.**
* **模型发布** -- a model is released: `蚂蚁百灵开源 Ling-3.1-flash`,
  `智谱推出法律模型 GLM-Legal`, `Fish Audio 发布 Drama 3，开放模型权重`.
* **产品应用** -- a product or app, consumer or enterprise: `豆包工作上线数据导入`,
  `企业微信接入 WorkBuddy`, `千问开售 N 系列 AI 眼镜`, `llama.cpp 推出 Windows 应用`.
* **技术与洞察** -- research, benchmarks and reports: `AA-Robotics 评测：GPT-6 Astra 居首`,
  `Swarmchasers 报告腾讯云 Agent 试绕高德反爬`, `Anthropic 弃用 Git，自建 Scion`.
* **行业动态** -- business, money and law: revenue, funding, lawsuits, market share,
  partnerships. `报道称 Anthropic 第三季度营收达 168 亿美元`.

The boundary that matters most in practice is 开发生态 vs 产品应用 vs 模型发布: a *model* being
released, a *developer tool or credit* being offered, and a *product* shipping are three
different things that all read like "X 发布 Y".
"""

from __future__ import annotations

import re

#: Section ids in the reference's order. The order **is** the ranking key, so it is a list rather than a
#: dict: the position in this tuple is the priority.
SECTIONS: tuple[str, ...] = (
    "要闻",
    "开发生态",
    "模型发布",
    "产品应用",
    "技术与洞察",
    "行业动态",
    "其他",
)

#: The rank each section gets. Lower sorts first. Derived from the pairwise tally, with the one
#: 5:4 pair (开发生态 over 模型发布) resolved by median rank, which agrees.
SECTION_RANK: dict[str, int] = {name: i for i, name in enumerate(SECTIONS)}

#: Section labels for the page, since a bare 要闻 in a heading is what 参考站 uses and reads well.
SECTION_LABELS: dict[str, str] = {
    "要闻": "要闻",
    "开发生态": "开发生态",
    "模型发布": "模型发布",
    "产品应用": "产品应用",
    "技术与洞察": "技术与洞察",
    "行业动态": "行业动态",
    "其他": "其他",
}

#: Labs whose product changes are 要闻.
#:
#: **US frontier labs only.** The first version included 豆包/千问/文心/混元/元宝 and scored 8%
#: on 产品应用 because every Chinese vendor product became 要闻. All forty of the reference's 要闻 items
#: across ten issues are OpenAI / Anthropic / Google / Meta / Microsoft / xAI -- `豆包工作上线
#: 数据导入` and `千问推出个人 Agent` are 产品应用. The distinction is not "how big is the
#: vendor" but which vendors 参考站 leads with, and the data is unambiguous about that.
_HEADLINE_LABS = re.compile(
    r"(?<![a-z])(openai|anthropic|google|deepmind|meta|microsoft|xai|x\.ai|"
    r"claude|chatgpt|gemini|copilot|codex|gpt-?\d)(?![a-z])|"
    r"谷歌|微软|苹果|英伟达",
    re.I,
)

#: A model is the object being released.
#:
#: Deliberately excludes bare lab names: `Claude Code 新增闲置会话自动压缩` is about the *Code*
#: product, not a model, and matching `claude` here sent it to 模型发布.
_MODEL_NOUN = re.compile(
    r"模型|大模型|权重|参数规模|多模态模型|语音模型|视觉模型|MoE|"
    r"(?<![a-z])(gpt-\d|claude\s+\w+\s*\d|gemini\s*\d|llama|qwen|deepseek|kimi|glm|"
    r"minimax|mistral|grok\s+\w|phi-|gemma|minicpm|nemotron)(?![a-z])|"
    r"开源模型|模型权重|模型系列|模型发布",
    re.I,
)

#: A product or app is shipping.
_PRODUCT_NOUN = re.compile(
    r"应用|助手|客户端|桌面版|app|插件|眼镜|耳机|手机|工作台|工作|studio|bot|"
    r"windows|macos|ios|android|浏览器|输入法|侧边栏|功能|服务|"
    r"play|store|voice|dot|cursor|antigravity|arena|qoder|opencode",
    re.I,
)

#: Developer-facing: tooling, access, pricing, credits, SDKs.
_DEV_NOUN = re.compile(
    r"折扣|折|优惠|额度|限免|免费|积分|定价|价格|订阅|套餐|退役|废弃|弃用|迁移|备案|"
    r"api|sdk|cli|ide|沙箱|追踪|部署|推理引擎|框架|工具链|"
    r"credit|pricing|discount|deprecat|retire",
    re.I,
)

#: Research, evaluation, reports.
_RESEARCH_NOUN = re.compile(
    r"评测|榜单|基准|benchmark|报告|研究|论文|实验|洞察|调查|实测|复现|"
    r"paper|eval\b|study|survey",
    re.I,
)

#: Money, law, org and regulation.
#:
#: Personnel, grants and compliance were missing and cost most of 行业动态's recall:
#: `OpenAI 基础设施负责人将离职`, `谷歌向 17 家机构提供 3600 万美元 AI 科研资助`,
#: `苹果多款国行 iPhone 新增大模型备案编号` all fell through to 其他.
_BUSINESS_NOUN = re.compile(
    r"营收|收入|融资|投资|估值|股价|市值|财报|亏损|盈利|收购|并购|合并|诉讼|起诉|"
    r"监管|罚款|政策|法案|立法|合规|合作|签约|份额|裁员|破产|ipo|"
    r"离职|任命|出任|加入|卸任|辞职|挖角|招聘|"
    r"资助|捐赠|拨款|补贴|专项资金|"
    r"revenue|funding|valuation|acquisition|lawsuit|regulat|resign|appoint|grant",
    re.I,
)

#: A release happened.
_RELEASE_VERB = re.compile(
    r"发布|推出|上线|开放|开源|宣布|正式|新增|更新|支持|接入|开售|开启|"
    r"releas|launch|ship|announc|open-?source|introduc|add|support",
    re.I,
)


def classify(title: str) -> str:
    """The section 参考站 would most likely file this headline under.

    Ordered rules, most specific first. The order encodes the boundary decisions that actually
    occur in the data:

    1. Business and law before anything else -- `OpenAI 第三季度营收` names a lab but is
       行业动态, and 要闻 is checked first precisely so that a lab name cannot pull it up.
    2. Research and evaluation before products -- `AA-Robotics 评测` mentions robots and
       benchmarking, and belongs in 技术与洞察.
    3. Developer tooling and pricing before model releases -- `OpenCode Go 上线 Gemini 4 Argon`
       names a model but is about access to it.
    4. A model being released beats a product shipping, because a model is the more specific
       object.
    5. A major lab plus a product change is 要闻; the same thing from a smaller vendor is
       产品应用.

    Falls back to 其他, which the ranker treats as last -- an unclassifiable headline should not
    be promoted by a guess.
    """
    text = title or ""
    if not text.strip():
        return "其他"

    # 1. Money, law, org.
    if _BUSINESS_NOUN.search(text):
        return "行业动态"

    # 2. Research, benchmarks, reports.
    if _RESEARCH_NOUN.search(text):
        return "技术与洞察"

    has_dev = bool(_DEV_NOUN.search(text))
    has_model = bool(_MODEL_NOUN.search(text))
    has_product = bool(_PRODUCT_NOUN.search(text))
    has_release = bool(_RELEASE_VERB.search(text))
    major = bool(_HEADLINE_LABS.search(text))

    # 3. Developer access, tooling, pricing. Before 模型发布 because naming a model is how a
    #    developer offer is described (`OpenCode Go 上线 Gemini 4 Argon` is about access).
    if has_dev and not has_product:
        return "开发生态"

    # 4. A model *itself* being released. `and not has_product` keeps `豆包工作上线` out: the
    #    object shipped there is an app.
    if has_model and has_release and not has_product:
        return "模型发布"

    # 5. A US frontier lab changing a product it ships is the day's headline.
    #
    #    Checked after 模型发布 so `Meta 发布 Muse Wonder 模型系列` stays a model release, and
    #    before the product fallback so `Claude Code 桌面版更新` leads rather than sitting in
    #    产品应用 with the apps.
    if major and (has_product or has_release):
        return "要闻"

    if has_product:
        return "产品应用"
    if has_model and has_release:
        return "模型发布"
    if has_dev:
        return "开发生态"
    # A release with nothing more specific attached is a product far more often than a model:
    # every remaining `X 发布 Y` in the sample that was not a model or a dev offer shipped an
    # app or a feature.
    if has_release:
        return "产品应用"

    return "其他"


def rank_of(section: str) -> int:
    """Sort key for a section. Unknown sections sort last rather than raising."""
    return SECTION_RANK.get(section, len(SECTIONS))


def sort_key(title: str, score: float) -> tuple[int, float]:
    """`(section_priority, -score)` -- the sort key that reproduces the reference's structure.

    Section first and score second, which is the reverse of a pure score ranking. That is the
    whole finding: a story 参考站 put in 要闻 and a pure score put 47th differs by category, and no
    weighting of a continuous score can move it.
    """
    return (rank_of(classify(title)), -score)
