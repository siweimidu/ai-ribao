"""Cross-source keyword frequency: how many *different* headlines talk about a thing.

## Why this is not `independent_source_count`

`heat._corroboration` counts how many publishers carried **one event**. That answers "is this
story confirmed".

It does not answer "what is the whole industry talking about". A model launch that five outlets
each cover once and a name mentioned in passing by nine outlets score the same under
corroboration, though only one of them is the story of the day.

## The idea, taken from TrendRadar

`sansan0/TrendRadar` (63k stars) ranks by how often a keyword appears across its platforms rather
than by any single article score. Their `frequency_words.txt` is hand-maintained; the counting is
the transferable part.

Here the keywords are extracted from the headlines themselves, so the list follows what is being
published instead of what someone guessed in advance.
"""

from __future__ import annotations

import math
import re
from collections import Counter

#: Words that appear everywhere and therefore say nothing. Compared case-folded.
_STOP = frozenset("""
    the a an and or but for to of in on at by with from as is are was were be been being
    this that these those it its they them their we our you your he she his her
    new now just how what why when who which more most less least very can could will would
    may might must should do does did done has have had not no nor so than then there here
    about into over under after before between during without within across
    says said report reports announced announce launch launches launched release releases
    released update updates updated version first next last week month year day
    """.split())

#: Company names are *not* signals. Measured on the 2026-10-21 issue: "openai" appeared in 14 of
#: 109 headlines, so every OpenAI story scored a perfect 1.000 and the ranking stopped
#: discriminating. A reader does not mean "OpenAI is trending" -- OpenAI is always trending. The
#: signal is a *specific* thing being discussed: a model, a product, a person, a technique.
#: Generic industry vocabulary. "AI" appeared in 18 of 109 headlines; "agent" in 5. These are
#: the water the whole digest swims in, so their frequency measures the digest, not the news.
_GENERIC = frozenset({
    "ai", "agi", "llm", "llms", "agent", "agents", "agentic", "model", "models", "chatbot",
    "artificial", "intelligence", "machine", "learning", "deep", "neural", "network", "networks",
    "data", "cloud", "platform", "tool", "tools", "tech", "technology", "software", "system",
    "systems", "service", "services", "product", "products", "company", "companies",
    "人工智能", "智能体", "大模型", "模型", "智能", "技术", "科技", "平台", "产品",
    "发布", "推出", "上线", "宣布", "开源", "研究", "报告", "功能", "服务", "系统",
})

_COMPANIES = frozenset({
    "openai", "anthropic", "google", "microsoft", "meta", "nvidia", "aws", "amazon", "apple",
    "deepmind", "huggingface", "hugging", "face", "mistral", "cohere", "stability", "xai",
    "bytedance", "baidu", "alibaba", "tencent", "huawei", "xiaomi", "samsung", "intel", "amd",
    "tesla", "ibm", "oracle", "salesforce", "adobe", "figma", "notion", "perplexity",
    "新浪财经", "华尔街见闻", "财联社", "澎湃", "界面", "腾讯", "阿里", "百度", "字节",
    "东方财富", "中国江苏网", "中国日报", "南京广播", "新华", "人民网", "央视",
})

#: English words that survive the capitalisation filter because they start a sentence or a title.
#: Measured noise on the 2026-10-21 issue: "using", "here", "what", "how".
_FILLER = frozenset({
    "using", "use", "used", "here", "there", "what", "when", "where", "which", "how", "why",
    "you", "your", "we", "our", "they", "their", "its", "his", "her", "this", "that",
    "these", "those", "with", "without", "from", "into", "over", "under", "about", "after",
    "before", "between", "during", "through", "against", "because", "while", "than", "then",
    "just", "only", "also", "more", "most", "less", "least", "very", "much", "many",
    "says", "said", "show", "shows", "shown", "get", "gets", "got", "make", "makes", "made",
})

_LATIN = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*\b")
_MODEL = re.compile(r"\b(?:gpt|claude|gemini|llama|qwen|deepseek|mistral|kimi|glm|grok)[-\w.]*", re.I)
_CJK = re.compile(r"[\u4e00-\u9fff]{2,8}")


#: A trailing attribution such as " - 中国江苏网" or " | Reuters". It differs per outlet for the
#: same story, so comparing it makes syndicated copies look like distinct articles.
_ATTRIBUTION = re.compile(r"\s+[-|—–]\s+[^-|—–]{2,24}$")


def _strip_attribution(text: str) -> str:
    """Drop a trailing " - Outlet" so two copies of one story compare equal."""
    return _ATTRIBUTION.sub("", (text or "").strip()).strip()


def keywords_of(text: str) -> set[str]:
    """The countable terms in one headline, lower-cased."""
    text = _strip_attribution(text)
    found: set[str] = set()
    for match in _LATIN.finditer(text or ""):
        word = match.group(0)
        if len(word) < 2:
            continue
        lowered = word.lower()
        if lowered in _STOP or lowered in _COMPANIES or lowered in _GENERIC or lowered in _FILLER:
            continue
        found.add(lowered)
    for match in _MODEL.finditer(text or ""):
        found.add(match.group(0).lower().rstrip(".,;:"))
    for match in _CJK.finditer(text or ""):
        term = match.group(0)
        # A CJK run only names something when it is short; a 20-character clause is a sentence
        # fragment and will never match another headline.
        if 2 <= len(term) <= 6 and term not in _COMPANIES and term not in _GENERIC:
            found.add(term)
    return found


def frequency_index(titles: list[str]) -> Counter[str]:
    """How many *distinct stories* mention each term.

    Distinct headlines, not occurrences: one article repeating a name five times is one
    article talking about it, not five.

    **Near-identical headlines collapse first.** Measured on the 2026-10-21 issue: seven
    headlines about 物理AI与世界模型大会 arrived from a single Google News search and were
    never clustered upstream, so the term scored seven hits and all seven stories took the
    maximum bonus. The signal is meaningful over *distinct stories*; over a search result it
    only amplifies repetition.

    Two headlines are the same story when they share a term and their lengths are within a
    factor of two -- cheap, and it catches syndicated rewrites without merging genuinely
    different articles that happen to name the same model.
    """
    counts: Counter[str] = Counter()
    seen: list[str] = []
    for title in titles:
        terms = keywords_of(title)
        if not terms:
            continue
        if any(_same_story(title, prior) for prior in seen):
            continue
        seen.append(title)
        counts.update(terms)
    return counts


def _same_story(left: str, right: str, *, min_share: float = 0.5) -> bool:
    """True when two headlines are two reports of one story.

    **A shared long substring, not a shared token.** Chinese headlines do not split on
    spaces, so the term extractor breaks 物理AI与世界模型大会 into fragments -- three reports of
    that one conference shared only the token 物理 and looked like three unrelated stories.
    What identifies the story is the *phrase*, so the phrase is what gets compared.

    A shared run of eight or more characters is the bar: long enough that a generic phrase
    cannot produce it, short enough that a reworded syndication still matches.
    """
    a = _strip_attribution(left)
    b = _strip_attribution(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 8:
        return False
    # Longest common substring, bounded: stop as soon as the bar is met.
    need = max(8, int(shorter * min_share))
    for size in range(len(a), need - 1, -1):
        for start in range(0, len(a) - size + 1):
            if a[start : start + size] in b:
                return True
    return False


def cross_source_score(
    title: str,
    index: Counter[str],
    *,
    reference: int = 8,
) -> tuple[float, list[str]]:
    """How widely this subject is discussed, on [0, 1], plus the term that produced it.

    Logarithmic for the same reason as `heat._corroboration`: one mention to two is the
    meaningful step, eight to nine is not.
    """
    terms = keywords_of(title)
    if not terms:
        return 0.0, []

    # The strongest term decides. Summing would reward a long headline over a widely discussed
    # subject, which is the wrong incentive.
    best_term = ""
    best_count = 0
    for term in terms:
        count = index.get(term, 0)
        if count > best_count:
            best_term, best_count = term, count

    if best_count < 2:
        # A term nobody else used carries no cross-source signal. Returning a small non-zero
        # value would let every unique headline score, defeating the purpose.
        return 0.0, []

    score = math.log2(1.0 + best_count) / math.log2(1.0 + reference)
    return min(1.0, score), [best_term]
