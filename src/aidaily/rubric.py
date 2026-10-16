"""LLM rubric scoring: let a model judge what a formula cannot.

The heat model in `heat.py` measures signals a formula can see -- corroboration, engagement,
reach, whether a frontier lab is named. It cannot tell that "Meta 与某公司达成战略合作"
matters less than a benchmark result, or that a quiet two-source report about a new capability
outranks a widely-syndicated funding item.

Horizon solves this by having the model score every candidate 0-10 against a rubric written
in markdown. The report on the eight projects calls that scoring the best of the eight. This
adopts the idea with two changes that matter for this pipeline:

**Batched.** Horizon makes one call per item. At sixty candidates that is sixty calls, and
this digest already spends ~108. Scoring ten headlines per call brings a full ranking pass
down to ~6-10 calls. The model returns one score per id.

**Ids, never positions or URLs.** Same contract as `analyze.py`: the model echoes back the
ids it was given. A model that returns a *position* can silently shift every row by one when
it drops an entry, and a model that returns a URL can invent one. Ids fail loudly -- an id
that was not sent is discarded, and a candidate that got no score keeps its formula score.

**Degrades to the formula.** No router, a failed call, a malformed response, or an id that
came back missing all leave that event scored by `heat` alone. The rubric can only ever
*adjust* a ranking, never remove something from it, so a broken model call costs ordering
quality rather than content.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .llm import LLMError, LLMUnavailable, Router
from .models import Event
from .sections import SECTION_RANK

#: Where the editable criteria live. Changing this file changes the ranking; no code change
#: and no redeploy.
PROFILE_PATH = Path(__file__).resolve().parents[2] / "config" / "profile.md"

DEFAULT_PROFILE = """\
给每条 AI 新闻打 0-10 分。10 = 改变行业格局（头部厂商发布新旗舰模型、重大安全事件）；
7-8 = 今天值得知道（重要产品发布、有数据支撑的行业变化）；5-6 = 有趣但不紧急；
3-4 = 边缘相关（营销、招聘、会议预告、教程）；0-2 = 噪音或与 AI 无关。
最重要的一条：热度 != 重要性 —— 被大量转发不等于重要，冷门但描述新能力/已验证突破的要给高分。
聚合站（其他 AI 日报）的内容降分，它们不是原始来源。
"""

SYSTEM = (
    "你是 AI 日报的主编，负责决定今天的新闻排序。\n"
    "你会读到一份栏目判定标准和一份评分标准，然后给若干条新闻标题\n"
    "同时判定栏目并打分。\n"
    "\n"
    "**栏目比分数重要**：最终排序是先按栏目、再按分数。\n"
    "\n"
    "输出要求：\n"
    "- 只输出 JSON，形如 "
    '{"scores": [{"id": "...", "score": 7, "section": "模型发布"}, ...]}\n'
    "- 每个 id 必须原样照抄输入里给的 id，不要改写、不要新增、不要遗漏\n"
    "- score 是 0 到 10 之间的整数\n"
    "- section 只能取：要闻、开发生态、模型发布、产品应用、技术与洞察、行业动态、其他\n"
    "- 不要输出解释以外的任何文字\n"
)

USER = """\
# 栏目判定标准

{section}

# 评分标准

{profile}

# 待处理新闻（{count} 条）

{items}

# 任务

给上面每一条判定栏目并打分，输出 JSON：
{{"scores": [{{"id": "...", "score": 7, "section": "模型发布"}}, ...]}}
必须为全部 {count} 个 id 各给一个栏目和一个分数。
"""


#: Output budget per rubric call.
#
# Ten scores plus their ids is roughly 300 tokens of real output, so the first value tried
# was 1200. Measured against the relay endpoints -- which are **reasoning** models, spending
# `reasoning_content` before producing any `content` -- 40 of 120 ids came back unscored:
# the budget was consumed by the model thinking, and the JSON was truncated mid-array.
#
# 4000 leaves room for the reasoning plus the answer. An unscored id is harmless (it keeps
# its formula score) but it silently weakens the rubric, so the budget is set generously.
RUBRIC_MAX_TOKENS = 4000

#: Ids recovered before giving up and leaving them on their formula score. One retry with
#: smaller batches; a second pass rarely helps when the first was truncated by a hard cap.
MAX_RETRY_ROUNDS = 1


@dataclass
class RubricResult:
    """Scores by event id, plus what happened while getting them."""

    scores: dict[str, float] = field(default_factory=dict)
    #: Section id per event, the ranking's **primary** key. Separate from `scores`
    #: because "important" and "filed under 行业动态" are different judgements, and
    #: folding one into the other loses the distinction the ordering depends on.
    sections: dict[str, str] = field(default_factory=dict)
    batches: int = 0
    calls: int = 0
    failed_batches: int = 0
    #: Ids the model returned that were never sent. Recorded rather than ignored: a nonzero
    #: count means the model is inventing rows, which is worth knowing even though the
    #: invented ids are dropped.
    unknown_ids: int = 0
    #: Ids that came back unscored after every attempt, and so kept their formula score.
    unscored: int = 0
    profile_source: str = "default"

    @property
    def coverage(self) -> str:
        parts = [f"{len(self.scores)} 条已打分", f"{self.calls} 次调用"]
        if self.unscored:
            parts.append(f"{self.unscored} 条未打分（保留公式分）")
        return " / ".join(parts)


def load_profile(path: Path | None = None) -> tuple[str, str, str]:
    """The rubric text and where it came from.

    A missing file is not an error: the pipeline must not stop because someone deleted a
    markdown file. It falls back to the built-in text and says so, because "the professor
    is using the default criteria" is something the run log should admit.
    """
    # Prefer the four-file profile, where scope and scoring are separate documents.
    if path is None:
        from .profiles import load_profile as load_structured

        structured = load_structured()
        if structured is not None and (structured.match or structured.analysis):
            # Scope first, then scoring, in that order.
            #
            # The order is the point of the split: match.md decides whether an item belongs
            # to the section at all, analysis.md decides how important it is. Read the other
            # way round, the model meets the score bands first and answers "does this belong"
            # with a number -- which is how a consumer-hardware story gets rated
            # merely-unimportant instead of out-of-scope.
            parts = []
            if structured.match:
                parts.append(
                    "# 范围判定（先判断是否属于本栏目，不属于的一律 0-2 分）\n\n"
                    + structured.match
                )
            if structured.analysis:
                parts.append("# 评分标准\n\n" + structured.analysis)
            return (
                "\n\n---\n\n".join(parts),
                str(structured.source),
                structured.section or "",
            )

    target = Path(path) if path else PROFILE_PATH
    try:
        text = target.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PROFILE, "default (config/profile.md missing)", ""
    if not text:
        return DEFAULT_PROFILE, "default (config/profile.md empty)", ""
    return text, str(target), ""


def _parse_scores(raw: str) -> tuple[dict[str, float], dict[str, str]]:
    """Pull `{id: score}` and `{id: section}` out of a model response.

    Tolerant about the envelope -- models wrap JSON in prose or a code fence -- and strict about
    the values: a score outside 0-10 or a non-numeric one is dropped rather than clamped,
    because clamping a bogus 99 to 10 would silently promote a row.

    A section that is not one of the known ids is **also dropped**, and that is deliberate. A
    model that invents `模型發布` (traditional characters) or `Model Release` would otherwise
    create a section that sorts last and quietly demotes the story; falling back to the
    rule-based classifier for that row is both safer and more accurate than trusting a string
    outside the taxonomy.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    doc = None
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        # Fall back to the outermost {...} in the response.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                doc = json.loads(text[start:end + 1])
            except (TypeError, ValueError):
                return {}, {}
    if not isinstance(doc, dict):
        return {}, {}

    rows = doc.get("scores")
    if not isinstance(rows, list):
        return {}, {}

    out: dict[str, float] = {}
    sections: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        value = row.get("score")
        if rid is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= number <= 10.0:
            continue
        out[str(rid)] = number
        section = str(row.get("section") or "").strip()
        if section in SECTION_RANK:
            sections[str(rid)] = section
    return out, sections


async def score_events(
    events: list[Event],
    router: Router | None,
    *,
    batch_size: int = 10,
    concurrency: int = 2,
    profile_path: Path | None = None,
) -> RubricResult:
    """Score events against the profile rubric. Never raises.

    With no router, returns an empty result and the caller keeps its formula scores. That is
    the whole failure design: the rubric is an improvement to ordering, not a dependency.

    "Never raises" is load-bearing rather than aspirational. An earlier version called
    `.strip()` on the router's `LLMResponse` object, which raised `AttributeError` inside
    `asyncio.gather` and took the entire run down -- a stage whose stated purpose is to be
    optional must not be able to fail the pipeline. Anything unexpected inside a batch is
    counted as a failed batch instead.
    """
    result = RubricResult()
    profile, source, section_text = load_profile(profile_path)
    result.profile_source = source

    if router is None or not events:
        return result

    batches: list[list[Event]] = [
        events[i:i + max(1, batch_size)] for i in range(0, len(events), max(1, batch_size))
    ]
    result.batches = len(batches)
    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()

    async def run(batch: list[Event]) -> None:
        listing = "\n".join(f"- id={e.event_id} | {e.title[:160]}" for e in batch)
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(
                profile=profile, section=section_text, count=len(batch), items=listing)},
        ]
        # Broad on purpose. This stage is optional by design, so any unforeseen failure --
        # a transport error, a missing attribute, a response shape nobody expected -- must
        # cost the batch rather than the run. The narrow catches below document what is
        # expected; this is the guarantee that the docstring's "never raises" holds.
        try:
            async with sem:
                response = await router.complete(
                    messages, temperature=0.0, max_tokens=RUBRIC_MAX_TOKENS)
            text = getattr(response, "text", None)
            if text is None:
                raise ValueError("router returned a response with no text")
            got, got_sections = _parse_scores(text)
        except (LLMError, LLMUnavailable):
            async with lock:
                result.failed_batches += 1
                result.calls += 1
            return
        except Exception:  # noqa: BLE001
            async with lock:
                result.failed_batches += 1
                result.calls += 1
            return

        async with lock:
            result.calls += 1
            sent = {e.event_id for e in batch}
            result.unknown_ids += sum(1 for rid in got if rid not in sent)
            for event_id, value in got.items():
                if event_id in sent:
                    result.scores[event_id] = value
            for event_id, section in got_sections.items():
                if event_id in sent:
                    result.sections[event_id] = section

    await asyncio.gather(*(run(b) for b in batches))

    # Retry whatever came back unscored, in **smaller** batches.
    #
    # Measured: 40 of 120 ids were returned without a score because the reasoning models
    # spent the output budget thinking and the JSON array was cut short. A shorter batch has
    # a smaller expected output, so it finishes inside the same budget. Anything still
    # missing keeps its formula score and is counted -- never invented.
    for round_index in range(MAX_RETRY_ROUNDS):
        missing = [e for e in events if e.event_id not in result.scores]
        if not missing:
            break
        smaller = max(2, max(1, batch_size) // (2 ** (round_index + 1)))
        retry_batches = [
            missing[i:i + smaller] for i in range(0, len(missing), smaller)
        ]
        result.batches += len(retry_batches)
        await asyncio.gather(*(run(b) for b in retry_batches))

    result.unscored = sum(1 for e in events if e.event_id not in result.scores)
    return result


def rubric_multiplier(score: float | None, *, floor: float = 0.30) -> float:
    """Map a 0-10 rubric score onto a multiplier for the formula score.

    `10 -> 1.0`, `0 -> floor`, linear between. Bounded below rather than at zero so a low
    score demotes a story instead of erasing it: an event the model dislikes should still
    appear on a quiet day, and a reader should be able to disagree with the model without
    losing the item.

    `None` (no score obtained) returns exactly 1.0 -- neutral, so a failed batch leaves the
    formula ranking untouched rather than penalising the events in it.
    """
    if score is None:
        return 1.0
    clamped = max(0.0, min(10.0, float(score)))
    return floor + (1.0 - floor) * (clamped / 10.0)


def band(score: float) -> str:
    """The five-way label from the rubric, for the archived explanation."""
    if score >= 9:
        return "突破性"
    if score >= 7:
        return "高价值"
    if score >= 5:
        return "有趣"
    if score >= 3:
        return "低优先"
    return "噪音"
