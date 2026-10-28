"""Is this story *about* AI, or does it merely mention it?

## The measured problem

Compared against `daily.juya.uk` for 2026-10-14, this pipeline published 60 items and shared
only **six** with juya's 27. Of this digest's top twenty, **five** were AI stories. The rest
included an Apple smart speaker, Xbox game ports, Ray-Ban glasses, a DLSS patch, and -- worse
than any of those -- V2EX chatter with no AI content whatsoever: "西安杭州两套房资不抵债",
"网友将家中 Wi-Fi 2.4G 与 5G 拆分", "基于十二进制的 XY 音乐记谱法".

Those last three are the tell. They carry no AI signal at all and still scored 0.36, level
with real AI news, because every term in the heat model measures *attention* -- corroboration,
engagement, reach, velocity -- and none of them asks what the story is about.

Meanwhile the stories juya led with and this pipeline missed were AI model and product
releases it had in its own raw data: Fish Audio open-sourcing Drama 3 weights, Alibaba
shipping a personal agent, llama.cpp's Windows app.

## Why a multiplier and not a weight

The existing `_is_ai_related` gate in `significance.py` only guards the *magnitude* term, so a
non-AI item still climbs on corroboration. Relevance is closer to a precondition than to a
peer of "how many outlets covered it": a story that is not about AI does not become AI news by
being widely reported.

So this multiplies. It never reaches zero -- the project's rule is demote, never delete, and a
borderline story should still be able to appear on a quiet day.

## What counts as evidence

Two independent signals, combined by taking the stronger:

* **The source.** A post on `deepmind.google` is AI by construction; one on a general
  community feed is not. A source declared AI-only is the single most reliable signal
  available, and it is the one the previous scoring ignored entirely.
* **The headline.** AI-specific vocabulary against off-topic vocabulary, as a ratio rather
  than a count, so a long consumer-tech headline does not win by being long.
"""

from __future__ import annotations

import re

from .models import Event, SourceSpec

#: Categories whose sources exist to cover AI. A story from one of these is AI news.
AI_ONLY_CATEGORIES = frozenset({
    "lab-official", "lab-blog", "model", "dataset", "paper", "trend",
})

#: Categories that carry AI news among other things.
MIXED_CATEGORIES = frozenset({"media", "zh-media", "digest", "news", "product", "search", "mixed"})

#: Categories that are general-purpose: AI appears, but so does everything else.
GENERAL_CATEGORIES = frozenset({"community", "dev", "social", "other", "example", "preset"})

#: Model and product names, grouped by vendor. **The user supplied this list explicitly** and asked
#: for these to be treated as focus points, so it is data rather than prose: one entry per family,
#: each with the aliases that actually appear in Chinese and English headlines.
#:
#: Two rules keep this from over-matching:
#:
#: * every entry is matched on word boundaries (`(?<![a-z])` / `(?![a-z])`), so `glm` cannot fire
#:   inside `glamorous` and `spark` cannot fire inside `sparkling`;
#: * Chinese names are matched plainly, because CJK has no word boundaries -- `混元` inside
#:   `混元大模型` is the intended hit.
MODEL_FAMILIES: dict[str, tuple[str, ...]] = {
    # ── 通用大模型 ──────────────────────────────────────────────────────────────
    "gpt": ("gpt", "chatgpt", "openai o1", "openai o3", "gpt-oss"),
    "claude": ("claude", "opus", "sonnet", "haiku"),
    "gemini": ("gemini", "bard"),
    "deepseek": ("deepseek", "深度求索"),
    "qwen": ("qwen", "通义", "千问"),
    "minimax": ("minimax", "海螺", "abab"),
    "grok": ("grok", "xai"),
    "kimi": ("kimi", "moonshot", "月之暗面"),
    "glm": ("glm", "chatglm", "智谱", "zhipu", "bigmodel"),
    "mistral": ("mistral", "mixtral", "codestral"),
    "doubao": ("doubao", "豆包", "seed-", "火山方舟", "volces"),
    "hunyuan": ("hunyuan", "混元", "元宝"),
    "mimo": ("mimo", "小米大模型"),
    "step": ("stepfun", "step-", "阶跃星辰", "阶跃"),
    "spark": ("讯飞星火", "iflytek spark", "星火大模型"),
    "ernie": ("ernie", "文心", "wenxin"),
    "gemma": ("gemma",),
    "sensenova": ("sensenova", "商汤日日新", "日日新"),
    "minicpm": ("minicpm", "面壁智能", "openbmb"),
    "wan": ("wan2", "wanx", "通义万相", "万相"),
    "pangu": ("pangu", "盘古"),
    "longcat": ("longcat", "龙猫"),
    "llama": ("llama", "meta ai"),
    "phi": ("phi-", "phi3", "phi4"),
    "nemotron": ("nemotron",),
    # Cohere names its models `Command R` / `Command R+` / `Command A` — with a space, while the
    # API id is `command-r`. Both spellings appear in headlines, so both are listed; the hyphenated
    # form alone missed `Command R++` entirely.
    "command": ("command-r", "command r", "command a", "command-r+", "command r+", "cohere"),
    # Deliberately **absent** here; see `_AMBIGUOUS_MODELS`. Every one of these is an ordinary
    # English word, and a bare match scored 1.00 for `fable of the bees`.
    # "mythos", "fable", "muse", "reflection", "agnes"
    # ── 图像 / 视频生成 ─────────────────────────────────────────────────────────
    "veo": ("veo",),
    "midjourney": ("midjourney",),
    "dalle": ("dall-e", "dalle", "dall·e"),
    "stable diffusion": ("stable diffusion", "sdxl", "sd3", "sd 3"),
    "flux": ("flux", "black forest labs", "bfl"),
    "runway": ("runway", "gen-3", "gen3"),
    "pika": ("pika",),
    "kling": ("kling", "可灵"),
    "seedance": ("seedance", "即梦"),
    "seedream": ("seedream",),
    "vidu": ("vidu", "生数科技"),
    "sora": ("sora",),
    # ── 其它常见 ────────────────────────────────────────────────────────────────
    "whisper": ("whisper",),
}

#: A flattened alternation of every family and alias, longest first.
#:
#: Longest-first matters: with `glm` before `chatglm`, the alternation would match the shorter
#: token and leave `chat` to be scanned again, which changes how many hits a headline scores.
_MODEL_ALTERNATION = "|".join(
    re.escape(alias)
    for alias in sorted(
        {a for aliases in MODEL_FAMILIES.values() for a in aliases},
        key=len,
        reverse=True,
    )
)

#: Model names that are also ordinary English words. They count **only** when the headline carries
#: an AI cue as well.
#:
#: Measured before this existed: `fable of the bees`, `a musing on life` and `mythos in literature`
#: all scored 1.00 and would have been published as AI news. The same mistake as the bare-`AI` case
#: in `_headline_focus`: one ambiguous token is not evidence of the subject.
_AMBIGUOUS_MODELS = re.compile(
    r"(?<![a-z])(mythos|fable|muse|reflection|agnes)(?![a-z])", re.IGNORECASE
)

#: What makes an ambiguous name into an AI story: a model word, a version number, a vendor, or a
#: technical term. `Fable 发布新模型` passes; `fable of the bees` does not.
_AI_CONTEXT = re.compile(
    r"模型|大模型|权重|开源|发布|上线|推出|基准|评测|推理|训练|参数|"
    r"(?<![a-z])(model|llm|release|launch|benchmark|weights?|open-source|"
    r"openai|anthropic|google|deepmind|meta|microsoft|nvidia|mistral|cohere)(?![a-z])|"
    r"\b\d+(\.\d+)?\b",
    re.IGNORECASE,
)

#: Vocabulary that only appears in AI coverage. Deliberately specific: "model" alone is a
#: word in fashion and finance writing, so the bare term is not enough on its own.
#:
#: **The Latin half is wrapped in word boundaries; the CJK half is not.**
#:
#: Measured 2026-10-28: the Latin half was a bare alternation, so `cline` matched `declined`,
#: `rag` matched `average` / `coverage` / `storage`, and `dify` matched `modify`. "Every average
#: coverage" is ordinary news prose, so `_CORE.search()` succeeded on almost any article -- and
#: through the body fallback in `focus_multiplier` that gave **39 of 82** published items a
#: perfect focus of 1.0. Four non-AI stories shipped that day (Axios, Semafor, LWN): a Trump
#: trade-talk piece whose body said "declined", a DOJ filing story, an Africa Finance corridor
#: announcement, and a Fedora/Raspberry Pi post.
#:
#: The boundary is `[a-z0-9]`, not `[a-z]`: a product name never continues into a digit.
_CORE_LATIN = (
    r"llms?|agents?|transformers?|diffusion|rag|embeddings?|tokenizers?"
    r"|benchmarks?|fine-?tun\w*|open-?weight\w*|context window|inference|multimodal"
    r"|neural networks?|machine learning|deep learning|reinforcement learning"
      # Added 2026-10-21: the vocabulary was missing the products this digest writes about most.
      # Measured on a real 670-item window, these headlines all scored 0.18 ("no AI at all"):
      #
      #     Devin 推出按使用效率自动提额机制
      #     MPS in PyTorch 2.15
      #     TRAE 公布程序员节活动，设百万积分大奖
      #
      # A vocabulary that does not contain `pytorch` cannot judge a PyTorch story. The list
      # below is the coding-agent and ML-framework layer -- names that mean AI on their own.
    r"|devin|cursor|copilot|codex|windsurf|replit|cline|aider|bolt\.new|lovable"
    r"|pytorch|tensorflow|jax|onnx|vllm|sglang|ollama|llama\.cpp|safetensors"
    r"|perplexity|character\.ai|midjourney|runway|suno|elevenlabs|synthesia"
    r"|trae|qoder|comfyui|langchain|llamaindex|autogen|crewai|n8n|dify"
    r"|mcp|function calling|tool use"
)

#: CJK AI vocabulary. No boundaries: Chinese has none, and each of these is a compound that
#: does not occur inside an unrelated word.
_CORE_CJK = (
    r"大模型|新模型|模型权重|模型发布|发布模型|开源权重|智能体|多模态|微调|推理|训练"
    r"|预训练|算力|提示词|上下文|向量|基准测试|参数规模|端侧|蒸馏|对齐|神经网络"
    r"|机器学习|深度学习|推理框架|推理引擎|提示词缓存|上下文长度|智能体框架|编程智能体"
      # Added after the 0.70 floor started rejecting real AI news. Measured misses:
      # `可灵AI新一代模型Kling 4.0正式上线` and `范式智能…开源推出 AI 部署平台模域ModelSphere`
      # both scored 0.50 -- below the floor -- because bare `模型` and `开源` were absent.
    r"|模型|开源|上线|推理服务|智能体平台|模型服务"
)

_CORE = re.compile(
    rf"(?<![a-z])({_MODEL_ALTERNATION})(?![a-z])"
    rf"|(?<![a-z0-9])(?:{_CORE_LATIN})(?![a-z0-9])"
    rf"|{_CORE_CJK}",
    re.IGNORECASE,
)

#: `AI` on its own. A weak positive, not a gate.
#:
#: It cannot certify relevance -- "Xbox's AI-powered game ports" and "Meta 打出 AI 翻身牌"
#: both contain it, and only one is this digest's subject. But treating it as *neutral* was
#: also wrong: it dropped Meta's new-model story to the non-AI band. So it counts for a
#: little, and the off-topic vocabulary can outweigh it.
_WEAK = re.compile(r"(?<![a-z])(ai|a\.i\.)(?![a-z])|人工智能", re.IGNORECASE)

#: AI institutions. A headline naming one is about AI even without technical vocabulary.
_LABS = re.compile(
    r"(?<![a-z])(openai|anthropic|deepmind|hugging ?face|mistral|cohere|stability|"
    r"qwen|deepseek|moonshot|zhipu|minimax|stepfun|liquid ai|together ai|"
    r"perplexity|scale ai|figure ai|runway|elevenlabs)(?![a-z])|"
    r"机器之心|量子位|新智元|智谱|阶跃星辰|月之暗面|面壁智能|零一万物",
    re.IGNORECASE,
)

#: Vocabulary that marks a story as *not* about AI even when it says "AI". These are not
#: forbidden topics -- they are topics whose centre of gravity is elsewhere, and the digest is
#: an AI digest.
_OFF_TOPIC = re.compile(
    r"(?<![a-z])(xbox|playstation|nintendo|dlss|geforce|rtx \d|steam deck|epic games|"
    r"hogwarts|fortnite|minecraft|netflix|disney\+?|spotify|tiktok|instagram|facebook|"
    r"ray-?ban|airpods|iphone|ipad|macbook|pixel \d|galaxy s\d|smart ?tv|soundbar)"
    r"(?![a-z])|"
    r"音箱|耳机|眼镜|手表|手机|电视|笔记本|平板|游戏|剧集|综艺|电影|票房|"
    r"房价|楼市|割肉|止损|股票|股价|基金|理财|彩票|"
    r"Wi-?Fi|路由器|记谱法|键盘|沙发|旅行|美食|减肥|"
    # Sports. Measured on 2026-10-21: a Sina headline of football hashtags -- `#斯图加特
    # #马德里竞技 #ai足球 #ai模型 #欧冠` -- scored focus 1.00 and reached the digest, because
    # the tag `#ai模型` contains 模型. It is a football result; the `ai` in the tags is
    # something the poster typed, not the subject. 足球/欧冠/赛季 alone is enough to dilute it.
    r"足球|篮球|欧冠|世界杯|联赛|球队|球员|转会|球迷|赛程|比分|夺冠|"
    r"斯图加特|马德里竞技|皇马|巴萨|曼联|利物浦|拜仁|紫微|斗数|八字|风水|算命|占卜|起卦|六爻|奇门|梅花易数|大六壬|塔罗|星盘|星座|黄历|择日|面相|手相|称骨|命理|排盘|四化|古籍原文|天纪|倪海厦",
    re.IGNORECASE,
)

#: Off-topic markers that are *also* legitimate AI subjects. `gpu` and `芯片` appear in both an
#: AI-compute story and a consumer-graphics story, so they are not negatives on their own.
_NEUTRAL_TECH = re.compile(
    r"(?<![a-z])(gpu|cuda|chip|silicon|datacent(er|re)|cloud)(?![a-z])|芯片|数据中心|算力",
    re.IGNORECASE,
)


#: Words that appear in `_CORE` but describe *any* software, not AI in particular.
#:
#: Measured 2026-10-24: the GitHub Trending row
#: `Renhuai123/ziwei-doushu — 紫微斗数开源排盘引擎` scored `focus: 1.0`, the same as
#: `Anthropic 发布 Claude 5.5`. The only token that matched was `开源` -- in
#: "开源排盘引擎", which is about divination software. A Git repository is open source whether
#: or not it has anything to do with AI, so the word carries no signal on its own.
#:
#: These are counted only when the headline also contains an unambiguous AI cue (a lab name, a
#: model name, or a technique term). Without that context they are worth nothing.
#: Vendors whose hardware or platform work is AI work. A headline naming one of these can
#: pair with a generic word and still be about AI: `英伟达开源 Run:ai，AI 算力编排` matched
#: only `开源`, scored 0.59, and would have been dropped just under the 0.6 floor.
_AI_ANCHORS = (
    "英伟达", "nvidia", "amd", "谷歌", "google", "微软", "microsoft",
    "meta", "苹果", "apple", "亚马逊", "aws", "阿里", "腾讯", "字节",
    "百度", "华为", "小米", "商汤", "科大讯飞",
)


_CONTEXT_DEPENDENT = frozenset({
    "开源", "模型", "上线", "推理", "训练", "预训练", "算力",
    "智能体", "微调", "对齐", "蒸馏", "向量", "多模态",
})


def _headline_focus(title: str) -> float:
    """How centrally the headline is about AI, in [0, 1].

    A ratio, not a count: a long headline should not out-score a short one. The floor is
    above zero because a single AI term is still evidence of *some* relevance.
    """
    text = title or ""
    # `finditer`, not `findall`: `_CORE` contains one capture group, and `findall` returns
    # the *group* rather than the match whenever a pattern has groups. That made every hit read
    # as `""`, so the context filter below saw no words at all and the divination row kept its
    # 1.0.
    core_hits = [m.group(0) for m in _CORE.finditer(text)]
    labs = len(_LABS.findall(text))
    weak = len(_WEAK.findall(text))

    # **Split the core hits into ones that mean AI on their own and ones that do not.**
    #
    # `开源` matched `紫微斗数开源排盘引擎` and pushed a divination tool to focus 1.0, the same
    # score as an Anthropic launch. A repository is open source regardless of subject, so the
    # word proves nothing; the same is true of `模型`, `上线`, `推理` and the rest of
    # `_CONTEXT_DEPENDENT`.
    #
    # They still count when the headline names a lab, a model or a technique -- `DeepSeek
    # 开源新模型` is genuinely AI -- so the rule is co-occurrence, not exclusion.
    has_anchor = (
        labs > 0
        or bool(_AMBIGUOUS_MODELS.search(text))
        or any(a in text.lower() for a in _AI_ANCHORS)
    )
    strong = [w for w in core_hits if w.strip().lower() not in _CONTEXT_DEPENDENT]
    contextual = len(core_hits) - len(strong)
    if not strong and not has_anchor:
        contextual = 0
    core = len(strong) + contextual
    off = len(_OFF_TOPIC.findall(text))
    neutral = len(_NEUTRAL_TECH.findall(text))

    # Weights: a named lab is the strongest single token (it names the subject), specific
    # technique vocabulary next, and a bare `AI` least -- it is the word every non-AI story
    # about an AI feature also uses.
    # An ambiguous name counts only alongside an AI cue; see `_AMBIGUOUS_MODELS`.
    if _AMBIGUOUS_MODELS.search(text) and _AI_CONTEXT.search(text):
        core += 1
    ai_hits = core * 1.0 + labs * 1.6 + weak * 0.45
    if ai_hits == 0:
        # Nothing AI-specific. A neutral technology term is not an AI signal on its own.
        return 0.30 if neutral else 0.18

    # Off-topic terms dilute rather than veto: "Xbox's AI upscaler" is genuinely ambiguous and
    # belongs in the middle, not at the bottom next to "网友将家中 Wi-Fi 拆分".
    # A named lab outranks the topic words.
    #
    # Measured: `Google DeepMind 用 AI 分析足球战术` is a real AI story and scored 0.63 once 足球
    # was added as a diluting term -- below the 0.7 floor, so it would have been dropped. The
    # sports words exist to catch a football result that happens to carry `#ai模型` in its tags;
    # they must not outvote the lab that is the actual subject of the sentence.
    if labs and off:
        off = 0

    score = ai_hits / (ai_hits + off * 1.2)

    # A bare `AI` cannot carry a story on its own, so when it is the *only* evidence the score
    # is capped. Measured: "Show HN: Pulse Local, a Mac budgeting app whose AI models run
    # on-device" scored 0.89 on the word `AI` alone -- a personal-finance app promoted into
    # the AI band. Named models and techniques are what distinguish the two, and this is the
    # cheap rule for "the subject is not actually AI, it just has an AI feature".
    if core == 0 and labs == 0:
        score = min(score, 0.5)
    return max(0.08, min(1.0, score))


#: How much of a body to read when the title says nothing. The first paragraphs name the subject;
#: reading the whole thing would score an opinion column on every term it mentions in passing.
_BODY_PROBE_CHARS = 1200

#: Ceiling for a score that came from the body rather than the headline. Above the 0.50
#: relevance floor so a date-titled digest issue still publishes, and well below 1.0 so a
#: rescued item ranks behind a story whose own headline states what it is.
_BODY_LIFT_CAP = 0.62


def _body_opening(event: Event, items_by_id: dict[str, object] | None) -> str:
    """The opening of the event's body text, or "" when there is none."""
    if not items_by_id:
        return ""
    best = ""
    for item_id in event.member_item_ids:
        item = items_by_id.get(item_id)
        if item is None:
            continue
        text = (getattr(item, "content_text", None) or getattr(item, "summary", None) or "")
        if len(text) > len(best):
            best = text
    return best[:_BODY_PROBE_CHARS].strip()


def _source_focus(event: Event, sources: dict[str, SourceSpec]) -> float:
    """How likely the sources are to be carrying AI news.

    Takes the *best* category present, because an event corroborated by a lab blog and a
    general feed is still AI news -- the lab is the informative part.
    """
    best = 0.0
    for source_id in event.source_ids:
        spec = sources.get(source_id)
        if spec is None:
            continue
        category = spec.category
        if category in AI_ONLY_CATEGORIES:
            best = max(best, 1.0)
        elif category in MIXED_CATEGORIES:
            best = max(best, 0.75)
        elif category in GENERAL_CATEGORIES:
            best = max(best, 0.35)
    return best


#: `AI` standing alone. Not `AI-powered` and not `OpenAI`, which are product names.
_AI_SUBJECT = re.compile(
    r"(?<![a-z])(AI|人工智能)(?![a-z\-])",
    re.IGNORECASE,
)

#: AI named as the subject of a clause: start of the headline, or after a dash/colon.
_AI_PHRASE = re.compile(
    r"(^|[：:—–\-、，,]\s*)(AI|人工智能|大模型|模型)\s",
    re.IGNORECASE,
)

def focus_multiplier(
    event: Event,
    sources: dict[str, SourceSpec] | None = None,
    *,
    floor: float = 0.22,
    items_by_id: dict[str, object] | None = None,
) -> tuple[float, dict]:
    """The multiplier to apply, plus the components that produced it.

    Returns `(multiplier, components)`. Never below `floor`: a story that is not about AI is
    demoted, not removed, so a quiet day still has something to print and a borderline item
    can still appear if it is genuinely the day's biggest thing.

    The source can only ever **raise** the headline's evidence, never lower it:

    * `max(headline, source)` let a category certify anything -- `MIT 林肯实验室主办新兴生物技术
      国家安全委员会路演` scored 1.00 because `lab-blog` counted as an AI-only category, and a
      category says what a publication is *for*, not what an article is *about*.
    * `headline * (0.55 + 0.45 * source)` swung too far the other way: an unambiguously AI
      headline from a general outlet (`OpenAI releases GPT-6` on The Verge) was multiplied by
      0.89. Being published by a general outlet is not evidence against a story being AI news.

    So the source fills part of the gap between the headline and certainty. A weak headline
    from an AI-only source is lifted a little; a certain headline is left exactly alone.
    """
    headline = _headline_focus(event.title)

    # **A title with no AI vocabulary is not the same as a story with no AI content.**
    #
    # Digest feeds title an issue by its date: `DailyDawn · 2026-10-15`. That title contains no
    # lab, no model, no technique word, so it measured 0.18 and the relevance floor dropped the
    # item -- while its body held 20941 characters of AI analysis. Measured across the archive:
    # dailydawn had 30 items in the raw corpus and **zero** in any published issue.
    #
    # So when the title carries no signal, the opening of the body is consulted instead. This
    # can only raise the score, and only for items whose own text says what they are about.
    body_used = ""
    if headline < 0.45:
        body = _body_opening(event, items_by_id)
        if body:
            lifted = _headline_focus(body)
            # **The body fallback may not carry a story on a bare mention of AI.**
            #
            # `_body_opening` exists for the digest feeds that title an issue by its date, so
            # a headline with no AI vocabulary can still be recognised from its own text. It
            # lifts whenever the body scores higher, and a body that says 「AI 与气候方程」 once
            # scored 0.50 -- enough to carry a climate story into an AI digest.
            #
            # Measured 2026-10-27: `MIT 在 2026 纽约气候周对接全球气候网络` published at
            # focus 0.50 with a headline that measures 0.18 on its own and matches no `_CORE`,
            # `_LABS`, `_AI_SUBJECT` or `_AI_PHRASE` pattern. Its only AI content was one
            # mention in one fact.
            #
            # The fallback therefore needs a *structural* signal in the body -- a model, a lab,
            # or a technique word -- not merely the letters `AI`. A genuine digest issue
            # mentions its subjects by name; an article about climate names climate.
            # **A body may rescue a headline, but it may not certify it.**
            #
            # `_headline_focus` is a ratio built for one-line headlines. Applied to 1200
            # characters of prose it degenerates: `score = hits / (hits + off * 1.2)` and a news
            # article matches little of `_OFF_TOPIC`, so **one** stray term gives exactly 1.0.
            # Measured 2026-10-28: a Trump trade story scored focus 1.0 because its body said
            # "declined", which the unanchored `cline` token read as the Cline coding agent. It
            # published in an AI digest.
            #
            # So the body now has to carry *structural* evidence -- a named lab, or several
            # distinct AI terms -- and the lift is capped below certainty. A digest feed that
            # titles its issue by date (`DailyDawn · 2026-10-15`) names many models and clears
            # both tests; an article that mentions AI once in passing clears neither.
            structural = len(_LABS.findall(body)) > 0 or len(_CORE.findall(body)) >= 3
            if lifted > headline and structural:
                headline = min(lifted, _BODY_LIFT_CAP)
                body_used = body

    source = _source_focus(event, sources or {}) if sources else 0.0

    combined = headline + (1.0 - headline) * source * 0.25

    # **A bare `AI` in the headline is weak evidence, not disqualifying evidence.**
    #
    # The cap below used to be 0.40, which sits *under* the 0.50 relevance floor. Every
    # headline that named AI as its subject but no product or technique -- exactly the shape
    # of industry analysis, policy and commentary -- was cut to 0.40 and then dropped by the
    # gate. Measured 2026-10-26: eight of the 21 stories that did publish sat at 0.50 for this
    # reason, and the local run listed eleven more rejected at 0.40:
    #
    #     Apollo 经济学家称 AI 对科技行业外的多数公司财务回报为零
    #     塔勒布：白领中产梦将被 AI 重创
    #     AI 降低攻击成本改变软件安全逻辑
    #     Ethan Mollick 谈用 AI 要更敢想
    #
    # These are AI stories. The old comment justified the cap with a Mac budgeting app whose
    # models run on-device -- still true, but that app is caught by the source check below, not
    # by the headline wording.
    #
    # So the cap now sits at the floor: a bare-AI headline from a general outlet stays at 0.50
    # and competes on its merits, while one from a source with no AI standing is still held
    # under. The distinction that matters is `source`, which the next branch uses.
    evidence = event.title or ""
    if body_used and not (_CORE.search(event.title or "") or _LABS.search(event.title or "")):
        evidence = body_used
    if not _CORE.search(evidence) and not _LABS.search(evidence):
        # **Bare `AI` as the subject is still an AI story.**
        #
        # The cap used to be a flat 0.40, which sits *below* the 0.50 relevance floor. Every
        # headline that named AI as its subject but no product or technique -- the shape of
        # industry analysis, policy and commentary -- was cut to 0.40 and dropped by the gate.
        # Measured 2026-10-26: eight published stories sat at exactly 0.50 for this reason, and
        # the local run listed eleven more rejected at 0.40:
        #
        #     Apollo 经济学家称 AI 对科技行业外的多数公司财务回报为零
        #     塔勒布：白领中产梦将被 AI 重创
        #     AI 降低攻击成本改变软件安全逻辑
        #
        # Those are AI stories. Keeping them out is the "sources plentiful, entries few"
        # complaint.
        #
        # The cap stays at 0.40 for the case it was written for -- "a Mac budgeting app whose
        # AI models run on-device", where AI is a feature rather than the subject. The test is
        # whether AI appears as a **subject**: a standalone `AI` token, or an AI phrase in
        # subject position at the start of the headline.
        if _AI_SUBJECT.search(evidence) or _AI_PHRASE.search(evidence):
            combined = min(combined, 0.50)
        else:
            combined = min(combined, 0.40)

    multiplier = floor + (1.0 - floor) * combined
    return round(multiplier, 4), {
        "focus": round(combined, 4),
        "focus_headline": round(headline, 4),
        "focus_source": round(source, 4),
        "focus_multiplier": round(multiplier, 4),
    }
