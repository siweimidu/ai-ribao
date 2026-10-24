"""Analysis: turn events into facts, inferences, opinions and uncertainties.

Two structural choices carry the anti-hallucination guarantee:

* **The model returns text only -- never a link.** Links are attached afterwards from our
  own records, so a fabricated URL cannot reach the digest even if the model tries.
* **The three epistemic buckets are separate fields.** A single "summary" string makes it
  impossible to tell a reported fact from the model's own guess, which is precisely the
  failure mode a news digest must avoid. Keeping them apart also lets the renderer label
  them differently for the reader.

When there is no router, or the budget is gone, `fallback_insight` produces a
rule-based entry from the source's own summary. The digest then says so in `warnings`
instead of pretending the analysis ran.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo
from typing import Iterable

from .llm import LLMError, LLMUnavailable, Router
from .models import Event, NormalizedItem

#: The digest is filed by Beijing date, and the model is shown publish times so it can write
#: "who did what, when". A UTC clock is eight hours behind and names the previous day after
#: 16:00, which is enough for the model to state the wrong date in a fact.
_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")

SYSTEM_PROMPT = (
    "你是 AI 日报的编辑。你只能使用给定的材料，**不得补充任何材料之外的信息**。\n"
    "严格区分四类内容：\n"
    "- facts：材料中直接陈述的事实，每条一句话，不加形容词。\n"
    "- inferences：你基于事实的推断。必须能被材料支持，措辞上体现推断性质。\n"
    "- opinions：评价性判断，不得伪装成事实。\n"
    "- uncertainties：材料没有讲清楚、无法确认的点。宁多勿少。\n"
    "**语言要求：所有输出必须是简体中文。**\n"
    "材料常常是英文的。标题、事实、推断、观点、不确定项一律译成中文，不要保留英文句子。\n"
    "\n"
    "## 术语怎么处理\n"
    "\n"
    "下列内容**整块保留英文原文，不要逐词翻译**：\n"
    "公司名、产品名、模型名、论文名、人名、代码标识符，以及**技术术语的固定搭配**。\n"
    "例如：OpenAI、Gemini 4 Argon、Kimi K3.1 Pro、GPT-6、CUDA、MoE、RLHF、\n"
    "Open Weights、Context Window、Fine-tuning、Zero-shot、Benchmark。\n"
    "\n"
    "**Open Weights 是一个术语，不能拆成「公开组重量」。**\n"
    "同样的：Closed-Weighted 不译「封闭重量」，Context Window 不译「上下文窗户」，\n"
    "Benchmark 不译「长凳标记」。遇到不确定的英文术语，保留原文，比硬译更准。\n"
    "\n"
    "译错的代价比不译大：读者看到「公开组重量」会以为说的是物理重量。\n"
    "\n"
    "## 时间与因果\n"
    "\n"
    "原文说「narrows the gap」就写「差距缩小」，不要写成「重量差距缩小」——\n"
    "不要给术语拆分出来的字面词加上原文没有的限定。\n"
    "\n"
    "## 硬性禁止\n"
    "\n"
    "1. 不得写出任何链接（链接由程序回填）。\n"
    "2. 不得写出材料中没有的日期、数字、模型名或公司名。\n"
    "3. 材料里没有的信息，宁可不写，也不要推测填充。\n"
    "4. **不要为了凑中文而拆解英文术语。** 保留原文永远比造一个错误的中文词好。\n"
    "只输出 JSON，不要 markdown 代码块或解释。"
)

#: Chinese renderings that mean the model split an English term into its words.
#:
#: Measured 2026-10-24: `Fable-5.1-Class Open Weights narrows Closed-Weighted gap` was
#: rewritten as `Fable-5.1-公开组重量差距缩小`. `Open Weights` became 公开组重量 -- `open` as
#: 公开, `weights` as 重量 -- which reads as a statement about physical mass. The prompt now
#: forbids it, but a prompt is a request, not a guarantee; this is the check that catches it.
#:
#: Every entry here is a compound that is meaningless or wrong when split.
_MISTRANSLATED_TERMS = (
    "公开组重量",   # Open Weights
    "开放组重量",
    "封闭重量",     # Closed-Weighted
    "上下文窗户",   # Context Window
    "长凳标记",     # Benchmark
    "微量调",       # Fine-tuning
    "零射击",       # Zero-shot
    "提示工程",     # Prompt engineering -- acceptable in Chinese, listed for contrast only
)

#: Terms that should survive verbatim. If the source had one and the rewrite lost it, the
#: rewrite dropped information.
_KEEP_VERBATIM = ("Open Weights", "Closed-Weighted", "Context Window", "Benchmark", "MoE", "RLHF")


def _safe_title(original: str, rewritten: str) -> str:
    """The rewritten title when it passed the checks, else the original."""
    if not rewritten:
        return original[:200]
    ok, _reason = title_is_safe(original, rewritten)
    return rewritten[:200] if ok else original[:200]

def title_is_safe(original: str, rewritten: str) -> tuple[bool, str]:
    """Whether the rewritten title may replace the original. Returns (ok, reason)."""
    text = (rewritten or "").strip()
    if not text:
        return False, "empty"

    for bad in _MISTRANSLATED_TERMS:
        if bad in text:
            return False, f"term split: {bad}"

    # A model that answers with the original English sentence unchanged has not translated.
    # That is handled elsewhere (the page falls back to the source title), so it is not a
    # failure here -- but a rewrite that keeps an English sentence AND adds invented Chinese
    # is worse than keeping the original alone.
    if len(text) > 120:
        return False, "too long for a headline"

    return True, ""

USER_TEMPLATE = """以下是关于同一事件的材料。请据此产出 JSON。

【事件】{event_title}
【来源数】{source_count}
【材料】
{materials}

只输出如下 JSON：
{{
  "title": "中文一句话概括（不超过 30 字，不加链接；专有名词保留原文）",
  "facts": ["中文事实1", "中文事实2"],
  "inferences": ["中文推断1"],
  "opinions": [],
  "uncertainties": ["中文不确定点1"],
  "key_points": ["中文要点1", "中文要点2"]
}}"""


@dataclass
class EventInsight:
    event_id: str
    title: str
    facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    opinions: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    #: True when produced without the model (no router, or budget exhausted)
    rule_based: bool = False


#: English function words. Their presence is the signal that a string is an English
#: *sentence* rather than a Chinese headline carrying Latin proper nouns.
_EN_FUNCTION_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "for", "with", "without", "at", "on", "in",
    "of", "to", "from", "by", "as", "is", "are", "was", "were", "be", "been", "being",
    "will", "would", "has", "have", "had", "its", "it", "this", "that", "these", "those",
    "his", "her", "their", "our", "your", "new", "how", "why", "what", "when", "where",
    "can", "could", "should", "may", "might", "into", "over", "after", "before", "up",
    "out", "about", "more", "than", "not", "no", "yes", "you", "we", "they", "he", "she",
})

_WORD = re.compile(r"[A-Za-z]+")


def needs_translation(text: str) -> bool:
    """True when a headline is a foreign sentence rather than Chinese prose.

    Used to decide whether the degraded path should say something about it. The digest's
    contract is that everything a reader sees is Chinese; when there is no model available
    to translate, the honest move is to keep the original title **and say so**, not to
    render an English sentence as if it were the digest's own writing.

    The test is **English sentence structure**, not a Latin-character ratio. The ratio was
    the first attempt and it was wrong: proper nouns are Latin by definition, and the
    instruction is precisely to keep them ("OpenAI 发布 GPT-6" scored 0.82 Latin and was
    flagged as foreign although it is a Chinese headline). Function words are what actually
    distinguish a sentence from a headline.
    """
    stripped = text.strip()
    if not stripped:
        return False

    # No CJK at all: nothing Chinese about it.
    if not any("\u4e00" <= ch <= "\u9fff" for ch in stripped):
        return True

    words = [w.lower() for w in _WORD.findall(stripped)]
    if not words:
        return False

    function_words = sum(1 for w in words if w in _EN_FUNCTION_WORDS)
    # One "of" or "the" can appear inside a product name; two or more in a row is a sentence.
    if function_words >= 2:
        return True
    # A single long run of Latin words with no Chinese between them is also a sentence
    # fragment, e.g. "Redesigning source control".
    if function_words >= 1 and len(words) >= 4:
        return True
    return False


def fallback_insight(event: Event, members: list[NormalizedItem]) -> EventInsight:
    """What the digest says when the model is unavailable: the source's own words.

    Deliberately dull. The point is that a degraded digest is still *accurate* -- it
    quotes the feed instead of inventing a summary.

    A foreign headline is kept as-is rather than machine-translated here, because this
    module has no translator: the digest's rule is Chinese on the page, and the only honest
    options are the model's translation or the original plus a note. Inventing a translation
    locally would be worse than showing the source's words. The note is what makes the
    English visible as a *degradation* rather than as the intended output.
    """
    primary = next((m for m in members if m.item_id == event.primary_item_id), None)
    if primary is None and members:
        primary = members[0]
    if primary is None:
        return EventInsight(event_id=event.event_id, title=event.title, rule_based=True)

    body = (primary.summary or primary.content_text or "").strip()
    facts = [body[:300]] if body else [primary.title]
    title = primary.title[:120]

    uncertainties = ["本次未调用大模型，内容为来源原文摘录"]
    if needs_translation(title):
        # Named explicitly so the reader knows the English is a fallback, not a choice.
        uncertainties.append("本条的来源标题为外文，未调用大模型，因此未翻译")

    return EventInsight(
        event_id=event.event_id,
        title=title,
        facts=facts,
        uncertainties=uncertainties,
        rule_based=True,
    )


def _materials(members: list[NormalizedItem], per_item: int = 700) -> str:
    blocks: list[str] = []
    for idx, item in enumerate(members[:6], start=1):
        # Beijing time, and said so.
        #
        # The model is told the publish time so it can write "who did what, when". Handing it a
        # UTC clock while the digest is filed by Beijing date invites it to state the wrong day
        # in a fact -- and a fact is the part a reader trusts.
        when = (
            item.published_at.astimezone(_DISPLAY_TZ).strftime("%Y-%m-%d %H:%M 北京时间")
            if item.published_at else "时间未知"
        )
        body = (item.summary or item.content_text or "").strip()[:per_item]
        blocks.append(f"[材料{idx}] 来源={item.source_id} 时间={when}\n标题：{item.title}\n内容：{body}")
    return "\n\n".join(blocks)


async def analyze_event(
    router: Router, event: Event, members: list[NormalizedItem]
) -> EventInsight:
    prompt = USER_TEMPLATE.format(
        event_title=event.title[:200],
        source_count=len(event.source_ids),
        materials=_materials(members),
    )
    got = await router.complete_json(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=900,
        purpose="summarize_event",
    )
    if not isinstance(got, dict):
        raise LLMError("analysis did not return an object")

    def strings(key: str, cap: int) -> list[str]:
        rows = got.get(key) or []
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        for row in rows[:cap]:
            text = str(row).strip()
            # A link in the body means the model ignored the contract; drop the line
            # rather than publish a link we cannot vouch for.
            if text and "http://" not in text and "https://" not in text:
                out.append(text[:400])
        return out

    return EventInsight(
        event_id=event.event_id,
        # A rewrite that split a technical term is worse than the English original:
        # the reader gets a confident Chinese sentence that says something false. The
        # prompt forbids it and `title_is_safe` enforces it -- a prompt is a request,
        # not a guarantee.
        title=_safe_title(event.title, str(got.get("title") or "")),
        facts=strings("facts", 8),
        inferences=strings("inferences", 5),
        opinions=strings("opinions", 4),
        uncertainties=strings("uncertainties", 5),
        key_points=strings("key_points", 6),
    )


async def analyze_events(
    events: Iterable[Event],
    by_id: dict[str, NormalizedItem],
    router: Router | None,
    *,
    limit: int | None = None,
    concurrency: int = 8,
    
) -> tuple[dict[str, EventInsight], list[str]]:
    """Analyse events, newest-ranked first. Returns (insights, warnings).

    `limit=None` means "everything given". The caller decides what to hand over -- and it
    passes exactly the events that will be published, because analysing a different set is
    how the digest ended up with untranslated English headlines: the items past the cut had
    no insight to render, so they fell back to the source's own words.

    An earlier version defaulted to 40 and sliced here, which also made `limit=None` a
    `TypeError` at `len(events) > limit`. The cap belongs at the call site, where it can be
    compared against the published count and warned about.
    """
    warnings: list[str] = []
    events = list(events)
    targets = events[:limit] if limit else events
    insights: dict[str, EventInsight] = {}

    def members_of(event: Event) -> list[NormalizedItem]:
        return [by_id[i] for i in event.member_item_ids if i in by_id]

    if router is None:
        warnings.append("未配置大模型，本期所有条目为来源原文摘录（规则降级）")
        for event in targets:
            insights[event.event_id] = fallback_insight(event, members_of(event))
        return insights, warnings

    sem = asyncio.Semaphore(concurrency)
    degraded = 0

    async def run(event: Event) -> None:
        nonlocal degraded
        async with sem:
            try:
                insights[event.event_id] = await analyze_event(router, event, members_of(event))
            except (LLMError, LLMUnavailable) as exc:
                degraded += 1
                if degraded == 1:
                    warnings.append(f"部分条目降级为原文摘录（首次失败：{type(exc).__name__}）")
                insights[event.event_id] = fallback_insight(event, members_of(event))

    await asyncio.gather(*(run(e) for e in targets))

    if degraded:
        warnings.append(f"{degraded}/{len(targets)} 个事件降级为规则摘录")
    return insights, warnings
