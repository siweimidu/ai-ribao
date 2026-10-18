"""Group stories that report the same release into one entry.

## Why this exists

A model launch and an API opening are different events, but several outlets describing **the
same** model release are one. On 2026-10-17 that release occupied four separate positions.

## How the identity is decided

The key is the family, its version, and the tier word that names the variant: `gemini-4-argon`,
`deepseek-v4-1-flash`. Everything else -- the verb, the publisher, the commentary -- is noise for
this purpose and is dropped.

That is harder than it looks in both directions, and each case below is a real headline:

* "Gemini 4 Argon ..." -- the tier follows the version and must be folded in;
* "... 开放 Gemini 4 Argon" -- the whole name sits at the end of the sentence, so a pattern that
  only looks forward from the family misses it;
* "DeepSeek 发布 V4.1-Flash-1017" -- a release verb sits between the family and the version.

A headline without a version ("DeepSeek opens its own search API") yields None, which is the
distinction between a model launch and an infrastructure announcement.
"""

from __future__ import annotations

import re

from .significance import _MODEL_NAME

#: Tier words that name a variant rather than describe the sentence.
_TIER = re.compile(
    r"^[\s\-_]*(flash|pro|max|mini|lite|turbo|ultra|opus|sonnet|haiku|air|argon)\b", re.I
)

#: A headline about *using* a model is not a report of its release.
_USE_OR_PROMO = re.compile(
    r"(?<!\w)(?:free|trial|discount|coupon|promo|giveaway|affiliate|referral)(?!\w)"
    r"|\u9650\u514d|\u514d\u8d39|\u8bd5\u7528|\u4f18\u60e0|\u6298\u6263"
    r"|\u4fc3\u9500|\u8fd4\u73b0|\u8d60\u9001|\u8865\u8d34|\u6309\u6b21\u6536\u8d39",
    re.IGNORECASE,
)


#: Wrapper packages that carry a model name in their own name: `llm-gemini 0.35`,
#: `langchain-openai 0.2`, `openai-python 1.9`. These version a *library*, not a model, and
#: treating them as models gave one story two identities and two cap slots.
_LIBRARY_VERSION = re.compile(
    r"\b(?:llm|langchain|llama[-_]index|openai[-_]python|anthropic[-_]sdk)[-\s]"
    r"(?:gpt|claude|gemini|llama|qwen|grok|mistral|deepseek|kimi|ernie|phi|gemma|nova)\b"
    r"|\b(?:sdk|client library|wrapper|binding|plugin)\b",
    re.IGNORECASE,
)

def designation(title: str) -> str | None:
    """Normalised model designation in a headline, or None.

    Folds separators to one hyphen, drops CJK tokens (a verb between the family and the version
    must not become part of the identity), and keeps the tier word whether it follows the
    version directly or after a punctuation mark.
    """
    text = title or ""
    # A library or SDK release is not a model release.
    if _LIBRARY_VERSION.search(text):
        return None
    match = _MODEL_NAME.search(text)
    if not match or _USE_OR_PROMO.search(text):
        return None

    raw = match.group(0).strip().lower()

    # The tier may follow the version (`Gemini 4 Argon`) or be interrupted (`Gemini 4 the Argon`).
    tail = text[match.end():match.end() + 24]
    extra = _TIER.match(tail)
    if extra:
        raw = raw + " " + extra.group(1).lower()

    # A headline that ends with the model name: "... 开放 Gemini 4 Argon". `_MODEL_NAME` matched
    # only "Gemini 4" because "Argon" is a tier word it does not consume, which gave one release
    # two identities depending on where the publisher put the name.
    if not extra:
        following = re.match(r"^[\s\-]*(argon)\b", tail, re.I)
        if following:
            raw = raw + " " + following.group(1).lower()

    tokens = [t for t in re.split(r"[\s_\-]+", raw) if t and t.isascii()]
    if not tokens:
        return None
    key = "-".join(tokens)
    key = re.sub(r"\.", "-", key)
    key = re.sub(r"-+", "-", key).strip("-")
    key = re.sub(r"-(?:1017|202\d|20\d\d)$", "", key)
    return key or None


def designations(title: str) -> list[str]:
    """Every distinct model designation in a headline.

    A roundup chains two releases: "OpenAI upgrades GPT-6 Astra Pro, DeepSeek ships V4.1-Flash".
    On 2026-10-17 such an entry took a single key, scored as a frontier release, and outranked
    both real launches while carrying analysis of neither. A headline naming more than one
    release is a digest of the day, not a report of one, so callers treat it separately.
    """
    text = title or ""
    found: list[str] = []
    start = 0
    while start < len(text):
        match = _MODEL_NAME.search(text, start)
        if not match:
            break
        key = designation(text[match.start():])
        if key and key not in found:
            found.append(key)
        start = match.end()
    return found


# A feed entry that is itself a digest is not news: it restates several stories the digest
# already carries as their own events, so including it guarantees a visible duplicate. Measured
# across 2026-10-14..18: five such entries, each overlapping a real event in the same issue.
_ROUNDUP = re.compile(
    r"(?:AI|AIHOT)\s*(?:早报|日报|晚报|周报)"
    r"|^(?:早报|日报|晚报|周报)"
    r"|\b(?:daily|weekly|roundup|digest)\s+(?:brief|news|recap)\b",
    re.IGNORECASE,
)


def is_roundup(title: str) -> bool:
    """Whether this headline is another outlet's digest rather than a single story."""
    return bool(_ROUNDUP.search(title or ""))
