"""Editorial priority for Chinese model vendors. Explicit user policy.

## The instruction

> 国产几家模型 DeepSeek，GLM，kimi，MiniMax，Qwen，豆包，阶跃星辰，元宝的优先级要放在第一位，
> 尤其是 DeepSeek，GLM，kimi，这三家调高优先级，DeepSeek 最高优先级，Kimi 其次，然后是 GLM

This is a **ranking policy**, not a relevance judgement, so it is deliberately a separate
module from `focus.py` and separate from the rubric. Conflating them would mean a reader cannot
tell whether a story is on the page because it is important or because of who made it, and the
two are tuned against completely different evidence.

It sits in the same place as the other multipliers -- heat, source weight, title quality,
relevance -- so a placement still reports every factor that produced it.

## Why a multiplier rather than a sort key

A hard "Chinese vendors first" sort would order by vendor before looking at the news, putting a
routine version bump above a frontier release. A multiplier raises these stories without making
them the only thing the digest can lead with, which is what "优先级要高" asks for and not
"永远排第一".

## What counts as being about a vendor

The vendor must be **the subject of the headline**, not mentioned in it. `UCSD 用
DeepSeek V4.1-Flash 做机械臂` is a robotics story that happens to use DeepSeek; boosting it
would put it above DeepSeek's own announcements, which is the opposite of the intent.
"""

from __future__ import annotations

import re

#: Vendor id -> multiplier. Ordered by the user's priority: DeepSeek first, then Kimi, then GLM,
#: then the rest of the named set. The gaps are what encode the ordering; a flat tier would
#: rank them together and lose the instruction's "especially these three".
VENDOR_TIERS: dict[str, float] = {
    "deepseek": 1.45,
    "kimi": 1.32,
    "glm": 1.24,
    # The remaining named vendors. Boosted, but below the three the user singled out.
    "minimax": 1.15,
    "qwen": 1.15,
    "doubao": 1.15,
    "stepfun": 1.15,
    "yuanbao": 1.15,
}

#: How a vendor appears in a headline. Latin names are matched on word boundaries so `glm`
#: does not fire inside another word; Chinese names have no boundaries and are matched plainly.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "deepseek": re.compile(r"deepseek|深度求索", re.I),
    "kimi": re.compile(r"kimi|moonshot|月之暗面", re.I),
    "glm": re.compile(r"(?<![a-z])glm(?![a-z])|智谱|chatglm|z\.ai", re.I),
    "minimax": re.compile(r"minimax|海螺", re.I),
    "qwen": re.compile(r"(?<![a-z])qwen(?![a-z])|通义|千问|阿里云百炼", re.I),
    "doubao": re.compile(r"doubao|豆包|火山方舟|volces", re.I),
    "stepfun": re.compile(r"stepfun|阶跃星辰|阶跃", re.I),
    "yuanbao": re.compile(r"元宝|hunyuan|混元", re.I),
}

#: A headline can name two vendors (`DeepSeek 与 Kimi 合作`). Taking the highest keeps the
#: priority the user set, rather than an average that would equalise them.
def vendor_priority(title: str) -> tuple[float, str]:
    """`(multiplier, vendor)` for a headline. `(1.0, "")` when no listed vendor is the subject.

    A phrase that names a vendor only as a *dependency* is excluded -- see the module docstring
    for the measured case.
    """
    text = title or ""
    for vendor, multiplier in VENDOR_TIERS.items():
        pattern = _PATTERNS.get(vendor)
        if pattern and pattern.search(text):
            if _is_only_a_dependency(text, pattern):
                continue
            return multiplier, vendor
    return 1.0, ""


#: Constructions where a vendor appears as a tool or a comparison rather than as the subject:
#: `用 …`, `基于 …`, `借助 …`, `对比 …`, `超越 …`, `… 驱动`. Matched against the text
#: immediately before the vendor name, because the position is what decides the role.
_DEPENDENCY_LEAD = re.compile(
    r"(用|使用|基于|借助|依托|采用|通过|对比|相较于|超越|击败|胜过|媲美|"
    r"using|powered by|built on|based on|compared|versus|vs\.?|beats?|outperforms?)\s*$",
    re.I,
)


def _is_only_a_dependency(text: str, pattern: re.Pattern[str]) -> bool:
    """True when every mention of the vendor is preceded by a dependency marker.

    One mention as the subject is enough to keep the boost, so a headline that both uses and
    discusses a vendor still counts.
    """
    for match in pattern.finditer(text):
        before = text[: match.start()]
        if not _DEPENDENCY_LEAD.search(before):
            return False
    return True


def components(title: str) -> dict[str, float | str]:
    """The audit-trail fields for one placement."""
    multiplier, vendor = vendor_priority(title)
    return {
        "vendor_priority": round(multiplier, 4),
        "vendor_subject": vendor,
    }
