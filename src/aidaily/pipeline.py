"""Pipeline stages: window -> L2 dedup -> (later) quality, rank, L3, render.

Kept separate from the fetchers so that every stage is a pure function over data. That
makes the whole pipeline replayable from a stored `items.jsonl` without touching the
network -- which is how the numbers in docs/ROADMAP.md were produced.
"""

from __future__ import annotations

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

    if pool_only is not None:
        # Candidate pool only: no diversity pass, no archive side effects. The caller uses
        # this to choose what to spend model calls on.
        return [row.event for row in ranked[:pool_only]], {
            **(rubric_report or {}),
            "pool_only": pool_only,
            "pool_size": len(ranked),
        }

    chosen = select_diverse(
        ranked,
        cfg.output.deep.max_items,
        sources,
        rank=RankWeights(
            max_per_source=cfg.quality.max_per_source,
            max_per_group=cfg.quality.max_per_group,
            topic_similarity_penalty=cfg.quality.topic_similarity_penalty,
            topic_similarity_threshold=cfg.quality.topic_similarity_threshold,
            topic_overlap_min=cfg.quality.topic_overlap_min,
            topic_overlap_penalty=cfg.quality.topic_overlap_penalty,
            duplicate_url_penalty=cfg.quality.duplicate_url_penalty,
        ),
    )
    # Copied *after* selection: `select_diverse` adds `topic_penalty` and `final_score` to
    # the same dict, and Pydantic snapshots the mapping on assignment. Doing this before
    # selection archived a penalty of 1.0 for every entry -- the audit trail disagreed with
    # the ranking that actually ran.
    for row in ranked:
        row.event.rank_score = row.score
        row.event.rank_components = dict(row.components)

    report = diversity_report(chosen, sources)
    if history is not None:
        # Carried out with the report rather than logged and forgotten: "we demoted 14
        # repeats" is a number a reader of the archive can check, and without it a quiet
        # day looks identical to a broken collector.
        report["cross_day_repeats"] = len(repeats)
        report["cross_day_window_days"] = history.window_days
        if repeats:
            report["cross_day_examples"] = repeats[:10]

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
            "events": len(events),
            "multi_source_events": len(multi),
            "items_after_window": len(stage.window.kept),
            "items_merged_away": sum(len(g.member_item_ids) - 1 for g in stage.result.groups),
            "distinct_sources_in_head": int(rank_report["distinct_sources"]),
            "head_max_source_share": int(float(rank_report["max_share"]) * 100),
            # What was excluded, and why, belongs in the published record -- not only in
            # a console log nobody keeps. A digest that silently discards 3.5k items
            # should be able to say so.
            **{f"dropped_{bucket}": n for bucket, n in stage.window.dropped_by_bucket.items()},
        },
    )
