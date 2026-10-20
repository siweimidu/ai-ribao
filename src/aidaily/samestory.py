"""One message is one message, however it is worded.

## Why this replaces the designation rule

The previous identity was the *model designation* -- "deepseek-v4-1-flash". That was the wrong
unit, and the archive shows how it failed:

   10-17  deepseek-v4.1-flash-1017 发布了
   10-18  DeepSeek发布V4.1-Flash-1017并开放搜索接口        <- same news, reported again

   10-17  WorkBuddy Intl 更新支持 DeepSeek-V4.1-Flash-1017，10 月 31 日前免费
   10-18  WorkBuddy国际版限免DeepSeek模型                  <- same news, reported again

Both pairs slipped through for two different reasons: the second headline of the first pair
parsed as designation "flash" (the verb sat flush against the vendor, so the matcher started
mid-word), and the WorkBuddy pair parsed as None (a promotion word excluded it from the model
rule entirely, so it never took part in deduplication).

Patching either case would leave the real defect in place: **a model name is not a message**.
"DeepSeek ships V4.1-Flash" and "WorkBuddy offers it free" mention the same model and are
different news; "DeepSeek ships V4.1-Flash" in Chinese and in English is one news.

## What identity actually is

A news item is a small set of **actors** and **actions**: who did what. Two reports describe the
same message when they name the same actors and the same kind of event. Language, word order,
punctuation and the presence of a version string are all irrelevant -- and the comparison below
deliberately ignores them.

The key is built from:

* **actors** -- vendors, products and projects, normalised across languages and spellings;
* **event type** -- release, pricing, outage, funding, policy, benchmark. Two items with the same
  actors but conflicting event types are different news.

Two messages match when the actor sets are equal and the event types do not contradict. That is
coarser than a similarity score on purpose: a score is what kept passing "0.686, just under the
threshold" while the reader could see the duplicate.

## Scope

This decides *equality of news*, not importance. It is applied against items already published
inside the window (see `history.py`), never inside one issue -- one day may carry two different
stories about one actor, and the per-issue cap handles that separately.
"""

from __future__ import annotations

import re

#: Actors as they appear in Chinese and English headlines. Keys are canonical; values are every
#: spelling seen in the corpus.
ACTORS: dict[str, tuple[str, ...]] = {
    "deepseek": ("deepseek", "深度求索"),
    "workbuddy": ("workbuddy",),
    "opencode": ("opencode", "open code"),
    "openai": ("openai", "open ai", "chatgpt", "gpt"),
    "anthropic": ("anthropic", "claude"),
    "google": ("google", "deepmind", "gemini", "bard"),
    "meta": ("meta", "llama", "muse"),
    "microsoft": ("microsoft", "azure", "copilot", "mai-"),
    "nvidia": ("nvidia", "nemotron"),
    "alibaba": ("alibaba", "qwen", "阿里", "千问"),
    "bytedance": ("bytedance", "doubao", "字节", "豆包"),
    "moonshot": ("moonshot", "kimi"),
    "zhipu": ("zhipu", "glm", "智谱"),
    "mistral": ("mistral", "mixtral"),
    "xai": ("xai", "grok"),
    "perplexity": ("perplexity",),
    "huggingface": ("huggingface", "hugging face"),
    "baidu": ("baidu", "ernie", "文心"),
    "tencent": ("tencent", "hunyuan", "腾讯", "混元"),
    "stepfun": ("stepfun", "step-", "阶跃"),
    "minimax": ("minimax",),
    "bolt": ("bolt",),
    "flux": ("flux",),
}

#: Event types, keyed on the verb rather than the subject (the subject is covered by ACTORS).
EVENT_TYPES: tuple[tuple[str, str], ...] = (
    ("release", r"发布|推出|上线|开源|面世|登场|亮相|正式版|releas|launch|ship|unveil|introduc|debut|open[- ]sourc"),
    ("pricing", r"限免|免费|试用|优惠|折扣|促销|返现|赠送|补贴|价格|订阅|收费|按次|降价|涨价|定价|\bfree\b|\btrial\b|\bdiscount\b|\bcoupon\b|pricing|\bprice\b"),
    ("outage", r"故障|宕机|停服|中断|崩溃|事故|泄露|outage|\bdown\b|incident|\bleak\b"),
    ("funding", r"融资|估值|投资|收购|并购|上市|rais|funding|valuation|acquir"),
    ("policy", r"监管|政策|法规|出口管制|合规|诉讼|起诉|regulat|polic|lawsuit|\bban\b"),
    ("benchmark", r"评测|基准|得分|刷新纪录|超越|benchmark|\bsota\b|record|outperform"),
)

_EVENT_RES = tuple((name, re.compile(pat, re.IGNORECASE)) for name, pat in EVENT_TYPES)


def _actor_pattern(spelling: str) -> re.Pattern[str]:
    """A matcher for one spelling. Latin tokens need word boundaries; CJK ones do not."""
    if spelling.isascii():
        return re.compile(r"(?<![a-z0-9])" + re.escape(spelling) + r"(?![a-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(spelling))


_ACTOR_RES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (name, tuple(_actor_pattern(s) for s in spellings))
    for name, spellings in ACTORS.items()
)


def actors(text: str) -> frozenset[str]:
    """Every actor named in a headline or body excerpt."""
    low = (text or "").lower()
    return frozenset(
        name for name, patterns in _ACTOR_RES if any(p.search(low) for p in patterns)
    )


def event_types(text: str) -> frozenset[str]:
    """Every event type the wording indicates."""
    return frozenset(name for name, pattern in _EVENT_RES if pattern.search(text or ""))




#: A vendor name alone is too coarse to identify a message: "Anthropic 员工预期", "Anthropic 招聘
#: 占比" and "Anthropic 安全法案" all name one vendor and are three different stories.
#:
#: A message is identified by its *specific* subject: a product or model with a version. Bare
#: vendor aliases (`claude`, `gemini`, `gpt`) are deliberately excluded -- they are how a vendor
#: is named, not what a story is about, and including them made four unrelated Claude items on
#: 2026-10-17 look like one.
SUBJECTS: tuple[str, ...] = (
    r"gpt-?\d+(?:\.\d+)?",
    r"claude\s+(?:opus|sonnet|haiku)\s*\d+(?:\.\d+)?",
    r"gemini\s+\d+(?:\s+(?:pro|flash|ultra|nano))?",
    r"llama\s*\d+(?:\.\d+)?",
    r"qwen\s*\d+(?:\.\d+)?",
    r"grok\s*\d+(?:\.\d+)?",
    r"kimi\s*[kv]\d[\w.]*",
    r"glm\s*\d+(?:\.\d+)*",
    r"doubao\s*[\w.]+",
    r"ernie\s*[\w.]+",
    r"muse\s+spark(?:\s+open)?",
    r"nemotron[\s\d.]*",
    r"mai-base-\d+",
    r"deepseek[\s-]?v?\d[\w.\-]*",
    r"minimax[\s-]?(?:m|h|speech|music|agent)?[\s-]?\d[\w.\-]*"
    r"(?:[\s\-]+(?:flash|pro|max|mini|lite|turbo|ultra))?",
    r"step[\s-]?\d[\w.\-]*",
    r"hunyuan[\s-]?[\w.\-]*",
    r"mimo[\s-]?v?\d[\w.\-]*",
    r"manus[\s-]?\d[\w.\-]*",
    r"ling[\s-]?\d[\w.\-]*",
    r"kling[\s-]?\d[\w.\-]*",
    r"v\d+(?:\.\d+)*(?:[\s\-]?(?:flash|pro|max|mini|lite|turbo|ultra|argon))?(?:[\s\-]?\d{2,4})?",
)

_SUBJECT_RES = tuple(re.compile(p, re.IGNORECASE) for p in SUBJECTS)


def subjects(text: str) -> frozenset[str]:
    """The specific product/model designations named in a headline, normalised.

    Separators are folded so `V4.1-Flash-1017`, `v4.1 flash 1017` and `V4.1-Flash` collapse. A
    trailing build date is dropped: it distinguishes editions of one launch, not two launches.
    """
    found: set[str] = set()
    for pattern in _SUBJECT_RES:
        for match in pattern.finditer(text or ""):
            key = re.sub(r"[\s_.]+", "-", match.group(0).strip().lower())
            key = re.sub(r"-+", "-", key).strip("-")
            key = re.sub(r"-(?:1017|202\d|20\d\d)$", "", key)
            if key:
                found.add(key)
    return frozenset(found)


def message_key(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """The identity of a news item: who, and what kind of thing happened."""
    return actors(text), event_types(text)


#: Event types that never describe the same news as each other, even for the same actor. A
#: release and an outage about one vendor are two stories. Two *different* commercial events, by
#: contrast, are the same kind of thing and often the same story reworded, so pricing is not
#: listed here.
_EXCLUSIVE = frozenset({"release", "outage", "funding", "policy", "benchmark"})






#: Words too common to distinguish one message from another: the actors themselves, the event
#: verbs, and the filler that every headline in this corpus uses.
_STOPWORDS = frozenset(""
    "the a an and or of to in on for with by from is are was were be been"
    "new model models ai llm llms agent agents api apis"
    "发布 推出 上线 开源 宣布 正式 支持 新增 更新 提供 使用 用户 今日 最新"
    "推出 面世 登场 亮相 正式版 预览版 版本 能力 功能 平台 工具 系统"
    "模型 大模型 智能 智能体 应用 技术 产品 服务 公司 团队".split()
)


def _content_tokens(text: str) -> frozenset[str]:
    """Distinctive words in a headline: not actors, not verbs, not filler.

    Latin tokens are lowercased; CJK is split into character bigrams, because Chinese has no
    spaces and a single character carries too little meaning. Bigrams are a crude tokeniser and
    sufficient here: the comparison only needs to notice that two headlines talk about different
    things.
    """
    low = (text or "").lower()
    # Drop the actor spellings first, so "perplexity" does not count as shared content.
    for spellings in ACTORS.values():
        for s in spellings:
            low = low.replace(s.lower(), " ")

    tokens: set[str] = set()
    for word in re.findall(r"[a-z][a-z0-9\-]{2,}", low):
        if word not in _STOPWORDS:
            tokens.add(word)

    for run in re.findall(r"[\u4e00-\u9fff]+", low):
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram not in _STOPWORDS:
                tokens.add(bigram)
    return frozenset(tokens)


#: A headline at most this long, with no verb of its own, is treated as shorthand for the same
#: announcement when the other side names a product.
#:
#: Measured: "WorkBuddy国际版限免DeepSeek模型" is 22 characters and is shorthand;
#: "DeepSeek恢复服务并补偿API用户" is 20 and is a service notice. Length alone cannot separate
#: them, so this is only one of two conditions -- the verb check does the rest.
SHORTHAND_MAX_CHARS = 30

#: Share of the smaller headline's content that must also appear in the other. Two headlines
#: about one event share most of their distinctive words; two headlines about one vendor share
#: almost none once the vendor name is removed.
CONTENT_OVERLAP_MIN = 0.34


def _content_overlap(left: str, right: str) -> float:
    a, b = _content_tokens(left), _content_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))






#: Verbs that make a headline a sentence about something, rather than a product line.
#: "WorkBuddy国际版限免DeepSeek模型" has none of these at the start; "Meta 开源权重模型竞争力展望"
#: has 开源. The distinction is what separates shorthand for one announcement from a separate
#: story that happens to involve the same vendor.
_VERBS = re.compile(
    r"发布|推出|上线|开源|宣布|推出|面世|登场|亮相|交付|收购|融资|裁员|起诉|禁止|批准"
    r"|\b(?:releas|launch|ship|unveil|introduc|debut|announc|acquir|raise|announc|report)"
    r"|降价|涨价|收费|订阅",
    re.IGNORECASE,
)


def _has_own_verb(text: str) -> bool:
    """Whether a headline carries its own verb, i.e. says something beyond naming a product."""
    return bool(_VERBS.search(text or ""))


#: Nouns that name a concrete thing a story is about. A shorthand headline carries one of these
#: (`限免 DeepSeek 模型`); a service notice or a commentary piece describes an action or an
#: opinion and carries none.
_CONCRETE = re.compile(
    r"模型|版本|文档|平台|接口|产品|功能|套餐|会员|价格|收费|基准|榜单|芯片|显卡"
    r"|\b(?:model|version|docs?|platform|api|product|feature|plan|pricing|benchmark|chip)\b",
    re.IGNORECASE,
)


def _has_concrete_noun(text: str) -> bool:
    """Whether a headline names a concrete thing rather than only an action."""
    return bool(_CONCRETE.search(text or ""))


def same_message(left: str, right: str) -> bool:
    """Whether two headlines describe the same piece of news.

    The rule, in order:

    1. **Actor sets must be equal.** A story about DeepSeek alone is not a story about DeepSeek
       and WorkBuddy; that difference is what separates a launch from a promotion about it.
    2. **Event types must not contradict.** "DeepSeek ships V4.1-Flash" and "DeepSeek had a
       five-hour outage" share an actor and are two stories.
    3. **Both name a subject -> the subject decides.** `V4.1-Flash` on both sides is one story
       however it is worded; `V4.1-Flash` against `GPT-6` is two.
    4. **One side names a subject -> still one story** when the event types agree. This is the
       pair the reader reported: "WorkBuddy Intl 更新支持 DeepSeek-V4.1-Flash-1017，10 月 31
       日前免费" and "WorkBuddy国际版限免DeepSeek模型" are one promotion, and the second simply
       omits the version. Their literal word overlap is **zero** -- one is Latin plus a version,
       the other is Chinese shorthand -- so no string measure can join them.
    5. **Neither names a subject -> the wording must overlap.** Otherwise every story about one
       vendor on one day collapses: "Perplexity 发布并开源两款决策模型" and "Perplexity 开源
       SPACE 沙箱平台" share an actor and an event type and are two announcements.

    An item naming no actor returns False: with nothing to compare, matching would delete
    unrelated news.
    """
    left_actors, left_events = actors(left), event_types(left)
    right_actors, right_events = actors(right), event_types(right)

    if not left_actors or left_actors != right_actors:
        return False

    left_specific = left_events & _EXCLUSIVE
    right_specific = right_events & _EXCLUSIVE
    if left_specific and right_specific and not (left_specific & right_specific):
        return False

    left_subjects, right_subjects = subjects(left), subjects(right)
    if left_subjects and right_subjects:
        # A shared product is decisive: same actor, same product, so the same story -- and a
        # headline may name the product without a verb ("DeepSeek: DeepSeek v4.1 Flash 1017").
        return bool(left_subjects & right_subjects)

    if left_subjects or right_subjects:
        # One side names the product and the other does not. Proof requires the shorthand
        # side to look like shorthand: short, and carrying no verb of its own.
        #
        # Length matters as much as the verb. "DeepSeek恢复服务并补偿API用户" has no verb
        # from the list below, yet it is plainly a different story -- a service notice, not
        # the launch. A genuine shorthand is a few words ("WorkBuddy国际版限免DeepSeek模型").
        noun_side = right if left_subjects else left
        return (            len(noun_side) <= SHORTHAND_MAX_CHARS            and not _has_own_verb(noun_side)            and _has_concrete_noun(noun_side)        )

    if not (left_events & right_events):
        return False

    return _content_overlap(left, right) >= CONTENT_OVERLAP_MIN
