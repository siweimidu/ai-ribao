"""Pipeline stages: window -> L2 dedup -> (later) quality, rank, L3, render.

Kept separate from the fetchers so that every stage is a pure function over data. That
makes the whole pipeline replayable from a stored `items.jsonl` without touching the
network -- which is how the numbers in docs/ROADMAP.md were produced.
"""

from __future__ import annotations

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
from .rubric import band, rubric_multiplier
from .select import WindowResult, select_window

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .analyze import EventInsight
    from .collect import CollectReport
    from .history import PublishedHistory

#: Multiplier applied to an event already published inside the cross-day window.
#
#: Not zero. A hard drop would empty the digest on a quiet day and would also discard a
#: story that genuinely developed overnight -- the penalty is applied to the *match*, and a
#: story that gained sources or URLs since yesterday breaks the match on its own. Demote,
#: never delete, which is the same rule the source registry follows.
REPEAT_PENALTY = 0.12

# A bare mention of AI (focus≈0.4) is not sufficient for an AI digest. This floor was selected
# against the measured daily candidate pool: 39/153 stories clear 0.70, while 65 score exactly
# 0.40 on a generic `AI` mention and 47 fall below 0.35. Do not relax this to fill slots.
MIN_AI_RELEVANCE = 0.70


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
    if history is not None:
        # `dedup.cross_day_window_days` was declared in the config and read by nothing --
        # dead configuration that looked like a working feature. It is wired up here.
        history.window_days = cfg.dedup.l3.cross_day_window_days
        now_ref = now or datetime.now(timezone.utc)
        stamp = today or now_ref.astimezone().date().isoformat()

        for row in ranked:
            repeat = history.find_repeat(row.event, today=stamp, now=now_ref)
            if repeat is None:
                continue
            row.score = round(row.score * REPEAT_PENALTY, 6)
            row.components["cross_day_repeat"] = REPEAT_PENALTY
            row.components["cross_day_days_ago"] = float(repeat.days_ago)
            row.components["score"] = row.score
            repeats.append({
                "event_id": repeat.event_id,
                "title": row.event.title[:120],
                "first_seen": repeat.first_seen,
                "days_ago": repeat.days_ago,
                "matched_on": repeat.matched_on,
            })
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
    # The consequence worth stating: a story 橘鸦 led with and a pure score put 47th differs by
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
    for row in ranked:
        focus = row.components.get("focus")
        # Missing relevance is not permission to publish. This used to be `if focus is not
        # None and focus < floor`, so any new event type that skipped the scorer silently
        # bypassed the filter. Absence of evidence now fails closed.
        if not passes_ai_relevance(focus):
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
        kept.append(row)

    # No relaxation and no slot-filling exceptions. `select_diverse` must not reinsert rejected
    # rows, and publication asserts the invariant again after diversity selection.
    report_extra = {
        "relevance_floor": focus_floor,
        "relevance_floor_dropped": dropped_focus,
        "relevance_missing_dropped": missing_focus,
        "relevance_dropped_examples": dropped_focus_examples,
    }

    section_of: dict[str, str] = {}
    for row in kept:
        # The model's judgement first -- it reads the story, and measured 41.8% accuracy is what
        # the rule-based classifier reaches on 橘鸦's own 478 examples, which is not enough on
        # its own. The rules are the fallback for a row the model did not classify.
        section = (rubric_sections or {}).get(row.event.event_id) or classify(row.event.title)
        section_of[row.event.event_id] = section
        row.components["section"] = section
    kept.sort(key=lambda r: (rank_of(section_of[r.event.event_id]), -r.score, r.event.event_id))
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
    violating = [
        row.event.title for row in chosen
        if not passes_ai_relevance(row.components.get("focus"))
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
    # predicts 橘鸦's order; within one, the score is the only signal available.
    chosen.sort(key=lambda r: (
        rank_of(r.components.get("section") or classify(r.event.title)),
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
        rubric_scores=rubric_scores,
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
