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
_CORE = re.compile(
    rf"(?<![a-z])({_MODEL_ALTERNATION})(?![a-z])|"
    r"llms?|agents?|transformers?|diffusion|rag|embeddings?|tokenizers?|"
    r"benchmarks?|fine-?tun\w*|open-?weight\w*|context window|inference|multimodal|"
    r"neural networks?|machine learning|deep learning|reinforcement learning|"
    r"大模型|新模型|模型权重|模型发布|发布模型|开源权重|智能体|多模态|微调|推理|训练|"
    r"预训练|算力|提示词|上下文|向量|基准测试|参数规模|端侧|蒸馏|对齐|神经网络|"
    r"机器学习|深度学习|"
    # Added after the 0.70 floor started rejecting real AI news. Measured misses:
    # `可灵AI新一代模型Kling 4.0正式上线` and `范式智能…开源推出 AI 部署平台模域ModelSphere`
    # both scored 0.50 -- below the floor -- because bare `模型` and `开源` were absent from this
    # list while `大模型` and `开源权重` were present. A vocabulary that only recognises the
    # longer compound is a vocabulary that misses how headlines are actually written.
    r"模型|开源|上线|推理服务|智能体平台|模型服务",
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
    r"Wi-?Fi|路由器|记谱法|键盘|沙发|旅行|美食|减肥",
    re.IGNORECASE,
)

#: Off-topic markers that are *also* legitimate AI subjects. `gpu` and `芯片` appear in both an
#: AI-compute story and a consumer-graphics story, so they are not negatives on their own.
_NEUTRAL_TECH = re.compile(
    r"(?<![a-z])(gpu|cuda|chip|silicon|datacent(er|re)|cloud)(?![a-z])|芯片|数据中心|算力",
    re.IGNORECASE,
)


def _headline_focus(title: str) -> float:
    """How centrally the headline is about AI, in [0, 1].

    A ratio, not a count: a long headline should not out-score a short one. The floor is
    above zero because a single AI term is still evidence of *some* relevance.
    """
    text = title or ""
    core = len(_CORE.findall(text))
    labs = len(_LABS.findall(text))
    weak = len(_WEAK.findall(text))
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
    score = ai_hits / (ai_hits + off * 1.2)

    # A bare `AI` cannot carry a story on its own, so when it is the *only* evidence the score
    # is capped. Measured: "Show HN: Pulse Local, a Mac budgeting app whose AI models run
    # on-device" scored 0.89 on the word `AI` alone -- a personal-finance app promoted into
    # the AI band. Named models and techniques are what distinguish the two, and this is the
    # cheap rule for "the subject is not actually AI, it just has an AI feature".
    if core == 0 and labs == 0:
        score = min(score, 0.5)
    return max(0.08, min(1.0, score))


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


def focus_multiplier(
    event: Event,
    sources: dict[str, SourceSpec] | None = None,
    *,
    floor: float = 0.22,
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
    source = _source_focus(event, sources or {}) if sources else 0.0

    combined = headline + (1.0 - headline) * source * 0.25

    # Evidence consisting only of a bare `AI` cannot be certified by the source either. The
    # cap is applied to the combined value, not to the headline: "a Mac budgeting app whose AI
    # models run on-device" is not AI news whether it appears on Hacker News or The Verge.
    if not _CORE.search(event.title or "") and not _LABS.search(event.title or ""):
        combined = min(combined, 0.40)

    multiplier = floor + (1.0 - floor) * combined
    return round(multiplier, 4), {
        "focus": round(combined, 4),
        "focus_headline": round(headline, 4),
        "focus_source": round(source, 4),
        "focus_multiplier": round(multiplier, 4),
    }
