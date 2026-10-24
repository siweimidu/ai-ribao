"""Pipeline stages: window -> L2 dedup -> (later) quality, rank, L3, render.

Kept separate from the fetchers so that every stage is a pure function over data. That
makes the whole pipeline replayable from a stored `items.jsonl` without touching the
network -- which is how the numbers in docs/ROADMAP.md were produced.
"""

from __future__ import annotations

import re

from collections import Counter

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .config import AppConfig
from .dedup import DedupConfig, DedupResult, cluster
from .models import Digest, Event, NormalizedItem, SourceCoverage, SourceSpec
from .rank import RankWeights, diversity_report, rank_events, select_diverse
from .sections import classify, rank_of
from .focus import focus_multiplier
from .rubric import band, rubric_multiplier, to_percent
from .tiers import DEFAULT_THRESHOLDS, threshold_for, tier_of
from .select import WindowResult, select_window

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .analyze import EventInsight
    from .collect import CollectReport
from .designation import is_roundup
from .history import PublishedHistory

#: Multiplier applied to an event already published inside the cross-day window.
#
#: Not zero. A hard drop would empty the digest on a quiet day and would also discard a
#: story that genuinely developed overnight -- the penalty is applied to the *match*, and a
#: story that gained sources or URLs since yesterday breaks the match on its own. Demote,
#: never delete, which is the same rule the source registry follows.
REPEAT_PENALTY = 0.12

# **The relevance floor is a noise gate, not a taste filter.**
#
# It used to be 0.70, then 0.55. Both were too strict for the same reason: `_headline_focus`
# scores in bands, not on a continuum. Measured on 657 in-window items:
#
#     0.18   255 items   (no AI term at all)
#     0.50   131 items   (the word AI, nothing more specific)
#     1.00   258 items   (a named model, lab or technique)
#
# A floor of 0.55 therefore keeps *only* the 1.00 band and discards all 131 of the 0.50 band --
# and that band is roughly half real news: "Notion 升级 AI：自动选模降成本", "英伟达GTC柏林大会即将开幕",
# "RISC-V 加速进入 AI 与高性能计算". The other half is noise ("AI赋能场馆思政教学研讨会").
#
# A threshold cannot separate those halves; they score identically. So the floor drops to 0.40,
# which admits the whole 0.50 band, and telling the halves apart becomes the rubric stage job --
# it reads the story and has an opinion. The floor now only removes items with no AI signal at all.
#
# The cost is more candidates reaching the model: a few more batched calls, not a redesign.
MIN_AI_RELEVANCE = 0.50


#: A title that names a *container* rather than a story: a bare date, a period label, an issue
#: number. Measured on 2026-10-22, `2026-10-22日刊` -- hex2077 own table of contents -- entered
#: the digest. Clicking it leaves the site and lands on someone else issue.
#:
#: The rubric had already called it 噪音 and its heat was 0.31, but both of those are demotions,
#: and nothing applied a structural test. This is that test, and it reads the string rather than
#: a score so no ranking can override it.
#:
#: Deliberately narrow: a headline that merely *contains* a date is a story ("OpenAI ships on
#: 2026-10-22"); only a title that is *nothing but* the container is rejected.
_CONTAINER_TITLE = re.compile(
    r"""^\s*(?:
        \d{4}[-/年.]\d{1,2}(?:[-/月.]\d{1,2}日?)?
        |第?\s*\d+\s*[期刊号]
    )
    \s*(?:日刊|周报|周刊|月报|月刊|年报|年鉴|日报|晚报|早报|特刊|专刊)?
    \s*$""",
    re.I | re.X,
)


def is_container_title(title: str) -> bool:
    """True when the title names a container (a date, a period, an issue number).

    Returns False for anything with real words in it, so a story that carries a date still
    publishes.
    """
    text = (title or "").strip()
    if not text or len(text) > 40:
        return False
    return bool(_CONTAINER_TITLE.match(text))

#: Sources the user asked to include without the relevance gate.
#:
#: These are curated AI digests -- a human already decided every entry is about AI, so applying
#: our own focus score to them double-filters work that was done upstream. They still go through
#: ranking, so a major story leads and a minor one sits low; what they skip is the *drop*.
#:
#: The gate stays for everything else. Removing it globally is what let consumer-electronics
#: items into the issue, which is the complaint this floor was added to fix.
PASSTHROUGH_SOURCES = frozenset({
    "rss:aihot-news-picks",
    "rss:aihot-news-full",
    "rss:aihot-news-all",
    "rss:aihot-news-daily",
    "rss:aihot-news-weekly",
    "rss:aihot-news-monthly",
    "rss:aihot-cat-models",
    "rss:aihot-cat-products",
    "rss:aihot-cat-industry",
    "rss:aihot-cat-paper",
    "rss:aihot-cat-tip",
    "rss:aihot-cat-opinion",
    "rss:daily-juya-uk",
    "rss:ainewslog-com",
    "rss:hex2077",
    "rss:hex2077-dev-rss-zh-cn",
    "api:aibase-ai-news",
    "api:aibase-daily-news",
})


def is_passthrough(event) -> bool:
    """True when any source carrying this event is on the allow-list."""
    return bool(PASSTHROUGH_SOURCES.intersection(event.source_ids or ()))


def passes_ai_relevance(focus: float | str | None) -> bool:
    """Fail closed: missing scores and scores under the high-relevance floor never publish."""
    if focus is None:
        return False
    try:
        return float(focus) >= MIN_AI_RELEVANCE
    except (TypeError, ValueError):
        return False


def dedup_config_from(cfg: AppConfig) -> DedupConfig:
    l2 = cfg.dedup.l2
    return DedupConfig(
        simhash_distance=l2.simhash_distance,
        title_similarity_merge=l2.title_similarity_merge,
        title_similarity_ambiguous=l2.title_similarity_ambiguous,
        publish_window_hours=l2.publish_window_hours,
        ambiguous_window_hours=l2.ambiguous_window_hours,
    )


@dataclass
class DedupStage:
    window: WindowResult
    result: DedupResult
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def run_dedup_stage(
    items: list[NormalizedItem], cfg: AppConfig, now: datetime | None = None
) -> DedupStage:
    window = select_window(items, cfg, now)
    return DedupStage(window=window, result=cluster(window.kept, dedup_config_from(cfg)))


def dedup_report(stage: DedupStage) -> dict[str, object]:
    """Every number the digest will quote about its own compression.

    Reported rather than estimated: `runs.jsonl` records exactly this, so a claim like
    "we deduplicated 40% of items" is always traceable to a run.
    """
    window = stage.window
    result = stage.result
    kept = len(window.kept)
    merged_away = sum(len(g.member_item_ids) - 1 for g in result.groups)
    multi_source = [g for g in result.groups if len(g.source_ids) > 1]
    return {
        "window": window.stats,
        "dedup": {
            "items_after_window": kept,
            "groups": len(result.groups),
            "merged_away": merged_away,
            "merge_rate": round(merged_away / kept, 4) if kept else 0.0,
            "multi_source_groups": len(multi_source),
            "ambiguous_pairs": len(result.ambiguous),
        },
        "top_merges": [
            {
                "group": g.dup_group_id,
                "title": g.title[:80],
                "members": len(g.member_item_ids),
                "sources": g.source_ids,
                "matched_by": g.matched_by,
            }
            for g in sorted(result.groups, key=lambda g: -len(g.member_item_ids))[:10]
            if len(g.member_item_ids) > 1
        ],
        "ambiguous_samples": [
            {"similarity": a.similarity, "left": a.left_item_id, "right": a.right_item_id}
            for a in sorted(result.ambiguous, key=lambda a: -a.similarity)[:5]
        ],
    }


def write_groups_jsonl(path: Path | str, stage: DedupStage) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for group in stage.result.groups:
            fh.write(group.model_dump_json() + "\n")
    return p


def write_json(path: Path | str, payload: object) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


# --- digest assembly --------------------------------------------------------------
#: Verbs that mark a release rather than a mention.
#:
#: A headline needs one of these *and* a model name to lead the issue: 发布 / 上线 /
#: 正式推出 describe something new, while 评测 / 实测 / 访谈 describe commentary on
#: something old.
_RELEASE_VERBS = (
    "发布", "上线", "推出", "开源", "正式可用", "开放",
    "announce", "release", "launch", "ship", "introduce", "available",
)

#: Model-name patterns that make a release worth leading with.
#:
#: Narrower than the focus vocabulary on purpose: a chat-app point release should not outrank
#: a frontier model, so only named model families are here.
#: Any of these names a model family. The version may sit anywhere in the headline:
#: `DeepSeek 发布 V4` puts a verb between the two, so one regex over the whole string cannot
#: see them as adjacent.
_MODEL_FAMILY = re.compile(
    r"(kimi|deepseek|claude|gpt|gemini|qwen|llama|glm|grok|mistral|sora)",
    re.IGNORECASE,
)

#: A version marker: `V4`, `K3.1`, `5.5`, `Pro`.
_VERSION = re.compile(r"\bv?k?\d+(\.\d+)?\b|\d+\.\d+|\bpro\b", re.IGNORECASE)


def leads_the_issue(title: str) -> bool:
    """True when this headline is a named-model release.

    Measured 2026-10-24: Moonshot shipped Kimi K3.1 Pro and it was not in the issue at all.
    Once collected it would still rank by score, and a release carried by one source loses to
    a story carried by four. A named-model launch is the day headline by definition, so it is
    pinned rather than left to the arithmetic.
    """
    text = title or ""
    lower = text.lower()
    if not (_MODEL_FAMILY.search(lower) and _VERSION.search(text)):
        return False
    return any(v in lower for v in _RELEASE_VERBS)

def select_for_digest(
    events: list[Event],
    stage,
    sources: list[SourceSpec],
    cfg: AppConfig,
    *,
    now: datetime | None = None,
    history: PublishedHistory | None = None,
    today: str | None = None,
    rubric_scores: dict[str, float] | None = None,
    #: How the rubric stage ended: llm, degraded, or formula. Recorded so the
    #: archive can say whether an ordering was a model decision or a fallback.
    rubric_mode: str = "",
    rubric_sections: dict[str, str] | None = None,
    pool_only: int | None = None,
) -> tuple[list[Event], dict]:
    """Rank and diversify, returning the events the digest will actually publish.

    Split out of `build_digest` so the analysis stage can run on **these** events rather
    than on whatever happened to come first. It did not, and the cost was real: the digest
    analysed `events[:40]` in arrival order and then ranked all 224 and published a
    different 60, so only 8 of 40 paid-for insights reached a reader while most published
    items showed a bare source excerpt. Analysing after selection means every model call is
    spent on something a reader will see.

    `history`, when given, demotes anything already published inside the cross-day window.
    Demoted rather than dropped, deliberately -- see `history.py` for the reasoning and for
    what a hard drop would cost on a quiet day.

    `rubric_scores`, when given, multiplies each event's score by the model's judgement of
    it (see `rubric.py`). An event with no score keeps exactly its formula value, so a failed
    batch is neutral rather than a penalty.

    `pool_only`, when given, returns the top N by formula **without** the diversity pass.
    It exists so the caller can decide which candidates deserve a model's attention before
    spending calls on them: scoring every one of ~280 events would cost twenty-eight batched
    calls to rank items that can never reach the digest anyway.
    """
    ranked = rank_events(
        events,
        stage.window.kept,
        sources,
        weights=cfg.quality.source_weights,
        rank=RankWeights(
            recency_half_life_hours=cfg.quality.recency_half_life_hours,
            recency_floor=cfg.quality.recency_floor,
            content_substance=cfg.quality.content_substance,
            corroboration=cfg.quality.corroboration,
            engagement=cfg.quality.engagement,
            max_per_source=cfg.quality.max_per_source,
            max_per_group=cfg.quality.max_per_group,
        ),
        now=now,
    )

    repeats: list[dict] = []
    # Used by both the roundup report below and the history lookup inside the guard, so it is
    # computed once here rather than at the first of the two uses.
    now_ref = now or datetime.now(timezone.utc)
    stamp = today or now_ref.astimezone().date().isoformat()
    # Another outlet's digest is not a story: it restates events this issue already carries,
    # which reads as duplication no matter how the ranking works. Removed before the repeat
    # check, because a roundup usually matches several events and would otherwise be counted
    # as a repeat of whichever one it happened to resemble.
    roundups = [r for r in ranked if is_roundup(r.event.title)]
    if roundups:
        ranked = [r for r in ranked if not is_roundup(r.event.title)]
        for r in roundups:
            repeats.append({
                "event_id": r.event.event_id,
                "title": r.event.title[:120],
                "matched_on": "roundup",
                "days_ago": 0,
                "first_seen": stamp,
            })

    if history is not None:
        # `dedup.cross_day_window_days` was declared in the config and read by nothing --
        # dead configuration that looked like a working feature. It is wired up here.
        history.window_days = cfg.dedup.l3.cross_day_window_days

        survivors: list = []
        dropped = 0
        for row in ranked:
            repeat = history.find_repeat(row.event, today=stamp, now=now_ref)
            if repeat is None:
                survivors.append(row)
                continue

            repeats.append({
                "event_id": repeat.event_id,
                "title": row.event.title[:120],
                "first_seen": repeat.first_seen,
                "days_ago": repeat.days_ago,
                "matched_on": repeat.matched_on,
            })

            # Every kind except the bare "designation" hint is proof: an exact headline, an
            # exact URL, a reworded match, or the same model already covered in the window.
            # The user's rule is that a story already reported must not reappear, and the
            # cross-day model case is what made Gemini 4 run on four consecutive days.
            if repeat.matched_on != "designation":
                # Proven repeat: the same headline or the same URL already ran inside the
                # window. This is **removed**, not demoted. The user's rule is explicit --
                # "之前报道过的消息，不得再次出现" -- and a penalty was the wrong answer:
                # measured on 2026-10-14..18, a repeat that keeps 12% of its score still
                # outranked genuine news on a thin day and reappeared near the top.
                dropped += 1
                continue

            # Same model, different wording. That is a hint rather than proof: on one day
            # three separate Gemini 4 stories are legitimate, so this must not delete. It is
            # demoted hard, and only for the model, not for the story.
            row.score = round(row.score * REPEAT_PENALTY, 6)
            row.components["cross_day_repeat"] = REPEAT_PENALTY
            row.components["cross_day_days_ago"] = float(repeat.days_ago)
            row.components["score"] = row.score
            survivors.append(row)

        if dropped:
            repeats.append({"dropped_repeats": dropped})
        ranked = survivors
        # The penalty is applied after ranking, so the order has to be rebuilt.
        ranked.sort(key=lambda r: (-r.score, r.event.event_id))

    rubric_report: dict = {}
    if rubric_scores:
        # The model's judgement multiplies the formula score. `rubric_multiplier` returns
        # exactly 1.0 for an event the model did not score, so a batch that failed leaves
        # those rows where the formula put them rather than dropping them down the list.
        graded = 0
        for row in ranked:
            raw = rubric_scores.get(row.event.event_id)
            if raw is None:
                continue
            multiplier = rubric_multiplier(raw)
            row.score = round(row.score * multiplier, 6)
            row.components["rubric_score"] = float(raw)
            row.components["rubric_multiplier"] = round(multiplier, 4)
            row.components["rubric_band"] = band(float(raw))
            row.components["score"] = row.score
            graded += 1
        ranked.sort(key=lambda r: (-r.score, r.event.event_id))
        rubric_report = {
            "rubric_scored": graded,
            "rubric_scored_total": len(rubric_scores),
            # How the order was decided. llm = the model graded enough of the pool to
            # order it; degraded = it graded most of it; formula = it contributed nothing
            # usable and the formula took over. A reader can tell an odd ordering from a
            # model decision, which are different problems to fix.
            "rubric_mode": rubric_mode,
        }

    # **Section first, score second.** This is the reverse of a pure score ranking and it is the
    # whole point of the section analysis.
    #
    # Reverse-engineered from `daily.juya.uk`: every story carries a rank (`... ↗ #17`) and the
    # ranks are handed out **by section in contiguous blocks**. Over ten issues the pairwise
    # "A before B" tally is 100% for thirteen pairs and 5:4 for one, giving
    #
    #     要闻 > 开发生态 > 模型发布 > 产品应用 > 技术与洞察 > 行业动态 > 其他
    #
    # Within a section, no title feature predicts position (Spearman below 0.35 for every
    # candidate, signs flipping between sections), so that part stays with the score.
    #
    # The consequence worth stating: a story 参考站 led with and a pure score put 47th differs by
    # *category*, and no weighting of a continuous score can move it across a category boundary.
    # **The relevance floor is a hard filter, applied before the section sort.**
    #
    # It was a demotion multiplier ("demote, never delete"), and ten days of published output
    # settled the argument: a demoted non-AI story still lands in the digest, and 60 slots are
    # more than the AI pool needs. Dropped rows are counted in the report so a thin day reads as
    # "今天AI新闻少", which is true, rather than being padded back to sixty with consumer
    # electronics, which is not.
    focus_floor = MIN_AI_RELEVANCE
    kept: list = []
    dropped_focus = 0
    missing_focus = 0
    dropped_focus_examples: list[dict[str, object]] = []
    dropped_container = 0
    dropped_container_examples: list[dict[str, object]] = []
    for row in ranked:
        focus = row.components.get("focus")
        # Missing relevance is not permission to publish. This used to be `if focus is not
        # None and focus < floor`, so any new event type that skipped the scorer silently
        # bypassed the filter. Absence of evidence now fails closed.
        if not passes_ai_relevance(focus) and not is_passthrough(row.event):
            dropped_focus += 1
            missing = focus is None
            missing_focus += int(missing)
            try:
                focus_value = float(focus) if focus is not None else 0.0
            except (TypeError, ValueError):
                focus_value = 0.0
                missing_focus += 1
            if len(dropped_focus_examples) < 12:
                dropped_focus_examples.append({
                    "event_id": row.event.event_id,
                    "title": row.event.title[:100],
                    "focus": round(focus_value, 3),
                    "reason": "missing_or_invalid_focus" if missing or focus_value == 0.0 else "below_floor",
                })
            continue

        # **An index page is not a story.**
        #
        # Measured on 2026-10-22: `2026-10-22日刊` from hex2077 entered the digest. It is the
        # table of contents for that site own issue -- clicking it leaves this site and lands on
        # someone else digest. The rubric had already called it 噪音 (multiplier 0.30) and its
        # heat was 0.31, yet it published, because both of those are *demotions* and nothing
        # here was a structural test.
        #
        # The test is on the title, not the score: a container names a date or a period, never a
        # subject. That is a fact about the string, and it cannot be talked out of by a
        # favourable ranking.
        if is_container_title(row.event.title):
            dropped_container += 1
            if len(dropped_container_examples) < 8:
                dropped_container_examples.append({
                    "event_id": row.event.event_id,
                    "title": row.event.title[:100],
                })
            continue

        kept.append(row)

    # No relaxation and no slot-filling exceptions. `select_diverse` must not reinsert rejected
    # rows, and publication asserts the invariant again after diversity selection.
    report_extra = {
        "relevance_floor": focus_floor,
        "relevance_floor_dropped": dropped_focus,
        "container_titles_dropped": dropped_container,
        "container_titles_examples": dropped_container_examples,
        "relevance_missing_dropped": missing_focus,
        "relevance_dropped_examples": dropped_focus_examples,
    }

    # **Tier decides the order, not admission.**
    #
    # This was a hard gate: a media source needed 68 points, and on 2026-10-21 that dropped 91% of
    # the candidates -- 308 considered, 26 published. The reader asked for the opposite: put
    # everything in, ordered by importance.
    #
    # So the bar is recorded and used as a *sort term* instead. A first-party story that scores
    # below its tier bar is demoted relative to one that clears it, but it still appears.
    #
    # What still filters is the relevance floor above: an item with no AI signal at all is not
    # news for this digest, and no amount of ordering makes it so.
    if rubric_scores:
        for row in kept:
            raw = rubric_scores.get(row.event.event_id)
            if raw is None:
                continue
            percent = to_percent(raw)
            categories = [
                src.category for src in sources if src.source_id in row.event.source_ids
            ]
            best = min(
                categories or [""],
                key=lambda c: ("T1", "T1_5", "T2").index(tier_of(c)),
            )
            bar = threshold_for(best, cfg.quality.tier_thresholds)
            row.components["tier"] = tier_of(best)
            row.components["tier_threshold"] = bar
            row.components["tier_shortfall"] = bool(percent is not None and percent < bar)

    report_extra.update({
        # The tier bar no longer drops anything, so the interesting count is how many stories fell
        # below theirs and were demoted rather than removed.
        "tier_shortfall": sum(
            1 for row in kept if row.components.get("tier_shortfall")
        ),
        "tier_thresholds": dict(cfg.quality.tier_thresholds),
    })

    section_of: dict[str, str] = {}
    for row in kept:
        # The model's judgement first -- it reads the story, and measured 41.8% accuracy is what
        # the rule-based classifier reaches on the reference's own 478 examples, which is not enough on
        # its own. The rules are the fallback for a row the model did not classify.
        section = (rubric_sections or {}).get(row.event.event_id) or classify(row.event.title)
        section_of[row.event.event_id] = section
        row.components["section"] = section
    # Section first, then whether the story clears its tier bar, then score.
    #
    # `tier_shortfall` is a *demotion*, not a filter: since the tier bar no longer drops anything,
    # a story that scores below its source bar sorts after the ones that clear theirs. That is how
    # a first-party announcement still leads even when the model rated it a point lower.
    kept.sort(
        key=lambda r: (
            rank_of(section_of[r.event.event_id]),
            bool(r.components.get("tier_shortfall")),
            -r.score,
            r.event.event_id,
        )
    )
    ranked = kept

    if pool_only is not None:
        # Candidate pool only: no diversity pass, no archive side effects. The caller uses
        # this to choose what to spend model calls on.
        return [row.event for row in ranked[:pool_only]], {
            **(rubric_report or {}),
            "pool_only": pool_only,
            "pool_size": len(ranked),
        }

    # Do not ask diversity selection to repopulate a fixed-size issue with irrelevant stories.
    # At 0.70 the measured daily candidate pool retains ~39/153 high-confidence AI stories;
    # max_items is an upper bound, not a target. Preserve that complete eligible pool, ranked
    # by the already-applied section-first order and score. Source caps are not allowed to
    # exclude/replace a high-relevance item with a weaker one.
    # One message, one entry -- inside the issue too.
    #
    # `history` only compares against *previous* days. Two outlets reporting the same news on the
    # same day stayed as two entries: on 2026-10-19 the digest carried both "MiniMax 正准备发布
    # MiniMax-M3.1-Flash" and "MiniMax-M3.1-Flash 即将发布". The reader sees one piece of news
    # twice, which is exactly what the cross-day rule exists to prevent.
    #
    # Ranked first, so the survivor is the best-scoring phrasing; the others are merged into it
    # by unioning their member ids, sources and URLs. `same_message` decides, so wording and
    # language do not matter -- only who did what.
    from .samestory import same_message as _same_message

    deduped: list = []
    for row in ranked:
        target = None
        for kept_row in deduped:
            if _same_message(kept_row.event.title, row.event.title):
                target = kept_row
                break
        if target is None:
            deduped.append(row)
            continue
        for member in row.event.member_item_ids:
            if member not in target.event.member_item_ids:
                target.event.member_item_ids.append(member)
        for source in row.event.source_ids:
            if source not in target.event.source_ids:
                target.event.source_ids.append(source)
        for url in row.event.all_urls:
            if url not in target.event.all_urls:
                target.event.all_urls.append(url)
        target.event.independent_source_count = max(
            target.event.independent_source_count, row.event.independent_source_count
        )
    same_issue_merged = len(ranked) - len(deduped)
    if same_issue_merged:
        print("同一条消息合并：%d 条" % same_issue_merged)
    ranked = deduped

    chosen = list(ranked[:cfg.output.deep.max_items])
    # Copied *after* selection: `select_diverse` adds `topic_penalty` and `final_score` to
    # the same dict, and Pydantic snapshots the mapping on assignment. Doing this before
    # selection archived a penalty of 1.0 for every entry -- the audit trail disagreed with
    # the ranking that actually ran.
    for row in ranked:
        row.event.rank_score = row.score
        row.event.rank_components = dict(row.components)

    # Final invariant at the publication boundary: diversity selection is permitted to reorder
    # or omit candidates, never to restore one below the high-relevance floor.
    # **The pass-through list is part of the rule, not an exception to it.**
    #
    # This assertion was written before cur curated digests could skip the gate, so it
    # failed the whole publish with `select_diverse reintroduced stories below the AI
    # relevance floor` -- three times, on 2026-10-24. The two rules are consistent once
    # the assertion asks the same question the gate asks: is this below the floor *and*
    # not from a source the user allow-listed?
    violating = [
        row.event.title for row in chosen
        if not passes_ai_relevance(row.components.get("focus"))
        and not is_passthrough(row.event)
    ]
    if violating:
        raise AssertionError(
            "select_diverse reintroduced stories below the AI relevance floor: "
            + "; ".join(title[:80] for title in violating[:5])
        )

    report = diversity_report(chosen, sources)
    if history is not None:
        # Carried out with the report rather than logged and forgotten: "we demoted 14
        # repeats" is a number a reader of the archive can check, and without it a quiet
        # day looks identical to a broken collector.
        report["cross_day_repeats"] = len(repeats)
        report["cross_day_window_days"] = history.window_days
        if repeats:
            report["cross_day_examples"] = repeats[:10]

    # **The section sort goes here, not before `select_diverse`.**
    #
    # It was placed with the other score sorts, and `select_diverse` -- which reorders by its
    # own `final_score` after applying the max-per-source and topic-overlap penalties -- undid
    # it immediately. Measured on the published 10-16 digest: 25 of 60 stories carried
    # `section: 其他`, and `其他` sorts last, yet four of them were in the top four positions.
    # The ordering was the diversity pass's, not the taxonomy's.
    #
    # A stable sort, so `select_diverse`'s judgement still decides the order *within* a section,
    # which is exactly where the analysis said it belongs: outside a section, no title feature
    # predicts the reference's order; within one, the score is the only signal available.
    # A named-model release leads, whatever its score. Everything else keeps the section
    # order and the score inside it.
    # **The model orders the issue; the formula is the fallback.**
    #
    # Measured 2026-10-24: `Chinese AI model Kimi K3.1 Pro is closing in on` had the highest
    # formula score in the issue (36.7) and was published at position 18, because the first
    # sort key was the *section* and the score only ordered rows inside a section. The
    # reader asked why the day biggest launch was buried; the answer was that a taxonomy
    # label outranked the model judgement and the evidence.
    #
    # Now the rubric score is the primary key. `-1.0` for an ungraded event puts it after
    # every graded one instead of letting a missing score masquerade as a high one --
    # measured: 3 of 36 events had no rubric score and two of them sat in the top twelve.
    # Section drops to a tiebreak inside the same rubric band, so a 7.5 from a side column
    # still beats a 7.5 from the lead column rather than being reordered by taxonomy.
    chosen.sort(key=lambda r: (
        0 if leads_the_issue(r.event.title) else 1,
        -(r.components.get("rubric_score") if r.components.get("rubric_score") is not None else -1.0),
        -r.score,
    ))

    # Where the sections came from. Without this, a run where the model returned no sections at
    # all looks the same as one where the model classified everything as 其他 -- and the fix is
    # in a different place for each.
    from_model = sum(
        1 for r in chosen if r.event.event_id in (rubric_sections or {})
    )
    report["section_source"] = {
        "from_model": from_model,
        "from_rules": len(chosen) - from_model,
        "model_returned": len(rubric_sections or {}),
    }
    report["section_distribution"] = dict(
        Counter(r.components.get("section") or classify(r.event.title) for r in chosen)
    )

    if dropped_focus:
        report["relevance_floor_dropped"] = dropped_focus
        report.update(report_extra)

    # **Last check before publication: did any entry merge stories that are not one story?**
    #
    # The dedup keys are what broke on 2026-10-23 -- twelve InfoQ articles shared a six-character
    # template body and hashed identically, so one entry ended up carrying three unrelated
    # stories and a link to an article it never described. Re-checking the hash would confirm the
    # same wrong answer; this looks at the outcome instead, at the headlines that landed together.
    #
    # It reports, it does not drop. A wrong drop costs a real story, and the reader-visible
    # damage here is a misleading entry -- worth surfacing, not worth silently deleting.
    try:
        from .mergeaudit import inspect as _inspect_merges, report as _merge_report

        # Built here rather than reused from below: `by_id` is defined further down the
        # function, and reaching for it before its line would raise NameError inside the
        # guard -- which the except would swallow, leaving the audit silently off.
        title_of = {i.item_id: i.title for i in stage.window.kept if i.title}
        titles_by_event: dict[str, list[str]] = {
            row.event.event_id: [
                title_of[i] for i in row.event.member_item_ids if i in title_of
            ]
            for row in chosen
        }
        suspicions = _inspect_merges(
            [row.event for row in chosen],

            titles_by_event,
        )
        report["merge_audit"] = _merge_report(suspicions)
        # Keep the headlines the check looked at. Without them the audit cannot be re-run on an
        # archive, and "we checked" becomes a claim about a past run rather than something a
        # reader can verify -- the same reason `cross_day_examples` is carried out.
        report["merge_audit_headlines"] = {
            event_id: titles[:12] for event_id, titles in titles_by_event.items() if len(titles) > 1
        }
    except Exception as exc:  # noqa: BLE001
        # A guard that can crash the publish is worse than no guard. Record that it did not run.
        report["merge_audit"] = {"checked": False, "error": f"{type(exc).__name__}: {exc}"[:120]}

    return [row.event for row in chosen], report


def build_digest(
    stage: DedupStage,
    events: list[Event],
    sources: list[SourceSpec],
    cfg: AppConfig,
    *,
    report: "CollectReport | None" = None,
    insights: dict[str, "EventInsight"] | None = None,
    warnings: list[str] | None = None,
    llm_usage: dict | None = None,
    now: datetime | None = None,
    history: PublishedHistory | None = None,
    rubric_scores: dict[str, float] | None = None,
    rubric_sections: dict[str, str] | None = None,
    pre_date_ignored: int = 0,
) -> Digest:
    """Assemble the Digest from the stages' output.

    Sectioning is by the *source's* category, not by anything the model produced: a
    model-assigned category could move a story into a section that misrepresents it, and
    the reader uses sections to decide what to skip.
    """
    now = now or datetime.now(timezone.utc)
    by_id = {i.item_id: i for i in stage.window.kept}
    category_of: dict[str, str] = {s.source_id: s.category for s in sources}

    def category_for(event: Event) -> str:
        primary = by_id.get(event.primary_item_id)
        if primary is None:
            return "other"
        return category_of.get(primary.source_id, "other")

    sections: dict[str, list[Event]] = {}
    for event in events:
        sections.setdefault(category_for(event), []).append(event)

    consumed_sources: set[str] = set()
    for event in events:
        consumed_sources.update(event.source_ids)

    # Coverage is reported, never estimated: `active` comes from the window stage and
    # `failed`/`skipped` from the collection report, so the number printed in the digest
    # is the number the run actually observed.
    total = len(sources)
    active = stage.window.sources_with_items
    results = list(report.results) if report is not None else []
    failed = sum(1 for r in results if r.verdict in ("dead", "blocked", "error", "bad_payload"))
    skipped = len(report.skipped) if report is not None else 0

    coverage = SourceCoverage(
        total=total, active=len(active), failed=failed, skipped=skipped
    )

    multi = [e for e in events if e.independent_source_count > 1]

    ordered, rank_report = select_for_digest(
        events, stage, sources, cfg, now=now, history=history,
        today=(now or datetime.now(timezone.utc)).astimezone().date().isoformat(),
        # The rubric scores **must** be passed here, or this call re-selects a different
        # sixty events than the caller analysed.
        #
        # That is not hypothetical: omitting them produced a digest whose `top_events` shared
        # only 40 ids with its own `insights` map. Twenty entries rendered the source's
        # English headline while their analyses sat in the archive attached to events nobody
        # would see -- and it is the exact failure `select_for_digest`'s own docstring warns
        # about, reintroduced by adding a second selection pass without threading the scores
        # through. Selection happens in two places and they must agree.
        # `rubric_sections` matters as much as the scores: the section is the ranking's
        # primary key, so a pass holding the scores but not the sections re-classifies every
        # row with the rule-based fallback and orders them differently. On 2026-10-19 that
        # divergence emptied the issue: the caller selected 200+ events, this call selected
        # none, and the digest published 0 while reporting 219 considered.
        rubric_scores=rubric_scores,
        rubric_sections=rubric_sections,
    )

    # The headline comes from the top-ranked event that actually has an insight.
    headline = ""
    for event in ordered:
        insight = (insights or {}).get(event.event_id)
        if insight is not None and insight.title:
            headline = insight.title
            break
    if not headline and ordered:
        headline = ordered[0].title

    return Digest(
        # The digest's date comes from the *configured* timezone, not the machine's.
        # GitHub Actions runs in UTC, so `now.astimezone()` would date a 00:30 Beijing
        # digest as the previous day -- and the filename, the ledger key and the RSS
        # guid all derive from it.
        date=now.astimezone(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d"),
        kind="deep",
        generated_at=now,
        window_start=now - timedelta(hours=cfg.run.window_hours),
        window_end=now,
        headline=headline,
        top_events=ordered,
        sections={k: sorted(v, key=lambda e: -e.rank_score) for k, v in sorted(sections.items())},
        source_coverage=coverage,
        llm_usage=llm_usage or {},
        warnings=list(warnings or []),
        counts={
            # **What was published, not what was considered.**
            #
            # This was `len(events)` -- every event the clusterer produced, before the relevance
            # floor and the item cap. Measured consequence: the 2026-10-16 issue published 60
            # stories while its own `counts.events` said 297, so the page header, the archive
            # index and the fact-check summary all quoted a number no reader could see. The
            # preceding two issues were correct only because nothing had been filtered out of
            # them yet.
            "events": len(ordered),
            "events_considered": len(events),
            "multi_source_events": len(multi),
            "items_after_window": len(stage.window.kept),
            "items_merged_away": sum(len(g.member_item_ids) - 1 for g in stage.result.groups),
            "distinct_sources_in_head": int(rank_report["distinct_sources"]),
            "head_max_source_share": int(float(rank_report["max_share"]) * 100),
            # What was excluded, and why, belongs in the published record -- not only in
            # a console log nobody keeps. A digest that silently discards 3.5k items
            # should be able to say so.
            **{f"dropped_{bucket}": n for bucket, n in stage.window.dropped_by_bucket.items()},
            # Items that `split_by_date` sent to another date, or left out because they were
            # published after this issue's date. They never reach `select_window`, so without
            # these the digest would under-report how much input it set aside.
            **({"late_or_ignored": pre_date_ignored} if pre_date_ignored else {}),
        },
    )
