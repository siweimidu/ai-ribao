"""Entity extraction, shared by L3 clustering and by ranking.

Both stages need the same answer to "what is this headline about?", and they need it
cheap. A dictionary plus capitalisation plus CJK bigrams costs nothing and is predictable
enough to reason about; a model-based extractor would add a call per item to a stage that
runs before the budget-aware one.

Kept in its own module so that `rank` does not have to import from `l3` -- ranking a list
should not pull in the clustering machinery.
"""

from __future__ import annotations

import re

#: Organisations, products and people that matter for AI news. Kept small and explicit: a
#: huge list adds noise, and the fallback heuristics cover the rest.
KNOWN_ENTITIES = (
    "openai", "anthropic", "google", "deepmind", "meta", "microsoft", "nvidia", "amd",
    "intel", "apple", "amazon", "aws", "tesla", "xai", "mistral", "cohere", "stability",
    "huggingface", "hugging face", "github", "cloudflare", "vercel", "databricks",
    "deepseek", "qwen", "alibaba", "baidu", "tencent", "bytedance", "moonshot", "zhipu",
    "minimax", "stepfun", "sensetime", "iflytek", "sakana", "figure", "waymo",
    "gpt", "claude", "gemini", "llama", "grok", "qwen", "kimi", "glm", "minicpm",
    "openbmb", "stablediffusion", "midjourney", "sora", "whisper", "phi", "o1", "o3",
    "argon", "antigravity", "codex", "copilot", "cursor", "windsurf", "langchain",
    "智谱", "月之暗面", "商汤", "科大讯飞", "百度", "腾讯", "字节", "阿里", "蚂蚁",
    "华为", "小米", "深度求索", "百川", "零一万物", "面壁", "阶跃", "英伟达", "微软",
    "谷歌", "苹果", "三星", "联想",
)

_LATIN_CAP = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:[-.][A-Za-z0-9]+)*)\b")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,8}")

#: Words that look like entities but carry no topic signal. Two headlines sharing "Best"
#: are not about the same thing, and letting such tokens through creates false candidate
#: clusters that each cost a model call to reject.
_STOP_CAPS = {
    "the", "this", "that", "how", "why", "what", "when", "where", "who", "which",
    "new", "and", "for", "with", "from", "you", "your", "our", "its", "his", "her",
    "show", "ask", "best", "top", "first", "more", "most", "less", "all", "any",
    "introducing", "announcing", "announcement", "update", "updates", "release",
    "released", "launch", "launched", "week", "day", "year", "month", "today",
    "now", "here", "there", "then", "than", "into", "over", "under", "after",
    "before", "about", "just", "only", "also", "can", "will", "would", "could",
    "should", "may", "might", "must", "not", "but", "are", "was", "were", "has",
    "have", "had", "does", "did", "doing", "get", "got", "make", "made", "use",
    "used", "using", "one", "two", "three", "build", "building", "built", "thing",
    "things", "way", "ways", "time", "times", "part", "parts", "need", "needs",
    "want", "wants", "like", "said", "says", "report", "reports", "study", "data",
    "open", "source", "free", "full", "real", "next", "last", "back", "down",
    "ai", "llm", "llms", "model", "models",
}


def extract_entities(text: str, extra_lexicon: set[str] | None = None) -> set[str]:
    """Cheap entity bag: known names + capitalised latin tokens + CJK bigrams."""
    if not text:
        return set()
    low = text.lower()
    found: set[str] = set()

    for entity in KNOWN_ENTITIES:
        if entity.lower() in low:
            found.add(entity.lower())

    for match in _LATIN_CAP.finditer(text):
        token = match.group(1)
        # Stopwords are stored lowercase; compare case-insensitively or the filter
        # silently does nothing.
        if len(token) > 2 and token.lower() not in _STOP_CAPS:
            found.add(token.lower())

    for run in _CJK_RUN.findall(text):
        # **Non-overlapping** 2-grams. The previous version slid one character at a time,
        # so `大模型` produced both `大模` and `模型`. Two unrelated stories that merely both
        # mention 大模型 therefore shared *two* entities, met the clustering threshold, and
        # chain-merged through union-find.
        #
        # Measured on a real day: one candidate cluster of **116 items** whose shared-entity
        # intersection was empty -- items with nothing in common, joined transitively. The
        # thirteen reports of the Gemini 4 Argon launch were inside that blob, so they never
        # formed their own event and scattered across positions 1, 41, 55, 56, 57, 59 and 60
        # of 60 instead of leading the issue.
        #
        # Stepping by two keeps Chinese usable without a segmenter while removing the
        # overlap that let a single word count as two.
        for idx in range(0, len(run) - 1, 2):
            found.add(run[idx:idx + 2])

    if extra_lexicon:
        for entity in extra_lexicon:
            if entity and entity.lower() in low:
                found.add(entity.lower())
    return found


def topic_overlap(left: str, right: str, *, min_len: int = 2) -> int:
    """How many *meaningful* entities two headlines share.

    Used to penalise a second entry about the same story. Raw title similarity is the
    wrong instrument: "Gemini 4 Argon: Built to solve your hardest problems" and "Gemini 4
    Argon for Robotics" score only ~0.5 because the tails differ, yet they are obviously
    one topic. The shared subject is what matters, so compare entity sets.

    CJK bigrams are excluded from the count -- they are useful for clustering, but any two
    Chinese headlines share several by accident, which would make everything look related.
    """
    a = {e for e in extract_entities(left) if not _is_cjk_ngram(e)}
    b = {e for e in extract_entities(right) if not _is_cjk_ngram(e)}
    return len(a & b)


def _is_cjk_ngram(token: str) -> bool:
    return len(token) == 2 and all("\u4e00" <= c <= "\u9fff" for c in token)
