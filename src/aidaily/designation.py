"""Group stories that report the same release into one entry.

## Why this exists

A model launch and an API opening are different events, but four outlets describing **the same
**model release** are one. On 2026-10-17 that release occupied positions 2, 3, 4 and 13.

## Why not the existing L3 clusterer

`coarse_clusters` groups by shared entities inside a 6-hour bucket. Measured that day, the reports
of one release produced entity sets that barely overlapped, so they never shared the two required
entities, and the time buckets split them further.

## How the identity is decided

The key is the family plus its version plus the tier word that follows: `deepseek-v4-1-flash`.
`_MODEL_NAME` already encodes where headlines put a version; this only normalises what it
returned. Everything else in the headline -- the verb, the publisher, the commentary -- is noise
for this purpose and is dropped.

A headline without a version ("DeepSeek opens its own search API") yields None, which is the
distinction the user drew between the model launch and the search API.
"""

from __future__ import annotations

import re

from .significance import _MODEL_NAME

#: Tier words that belong to the designation rather than to the surrounding sentence.
_TIER = re.compile(r"^[\s\-_]*(flash|pro|max|mini|lite|turbo|ultra|opus|sonnet|haiku|air)\b", re.I)

#: A headline about *using* a model is not a report of its release. WorkBuddy promoting a free
#: week of DeepSeek V4.1 Flash carries the same designation but describes a different event.
_USE_OR_PROMO = re.compile(
    r"(?<!\w)(?:free|trial|discount|coupon|promo|giveaway|affiliate|referral|subscription|pricing)(?!\w)"
    r"|\u9650\u514d|\u514d\u8d39|\u8bd5\u7528|\u4f18\u60e0|\u6298\u6263|\u4fc3\u9500"
    r"|\u8fd4\u73b0|\u8d60\u9001|\u8865\u8d34|\u4f1a\u5458|\u4ef7\u683c|\u8ba2\u9605|\u6536\u8d39|\u6309\u6b21",
    re.IGNORECASE,
)


def designation(title: str) -> str | None:
    """Normalised model designation in a headline, or None.

    The boundary case: `_MODEL_NAME` captures `DeepSeek v4.1` when a tier word follows a space,
    and `DeepSeek V4.1-Flash-1017` when the separators are hyphens. Both describe one release, so
    the tier word after the match is pulled in explicitly.
    """
    text = title or ""
    match = _MODEL_NAME.search(text)
    if not match or _USE_OR_PROMO.search(text):
        return None

    raw = match.group(0).strip().lower()
    tail = text[match.end():match.end() + 24]
    extra = _TIER.match(tail)
    if extra:
        raw = raw + " " + extra.group(1).lower()

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
    On 2026-10-17 such an entry took the gpt-6 key, scored as a frontier release, and outranked
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
