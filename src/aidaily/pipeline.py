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
from .select import WindowResult, select_window

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .analyze import EventInsight
    from .collect import CollectReport


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

    # Ranking for the digest head: independent corroboration first, then recency. Sorting
    # purely by source count let one duplicated feed pair (HN Algolia + hnrss) fill the
    # entire top of the brief with stories that had no real corroboration at all.
    def rank_key(event: Event) -> tuple:
        when = event.published_range[0] if event.published_range else datetime.min.replace(tzinfo=timezone.utc)
        return (-event.independent_source_count, -when.timestamp(), event.event_id)

    ordered = sorted(events, key=rank_key)

    # The headline is taken from the top-ranked event, not from whichever event happened
    # to be first in the dictionary.
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
        top_events=ordered[: cfg.output.deep.max_items],
        sections={k: sorted(v, key=rank_key) for k, v in sorted(sections.items())},
        source_coverage=coverage,
        llm_usage=llm_usage or {},
        warnings=list(warnings or []),
        counts={
            "events": len(events),
            "multi_source_events": len(multi),
            "items_after_window": len(stage.window.kept),
            "items_merged_away": sum(len(g.member_item_ids) - 1 for g in stage.result.groups),
            # What was excluded, and why, belongs in the published record -- not only in
            # a console log nobody keeps. A digest that silently discards 3.5k items
            # should be able to say so.
            **{f"dropped_{bucket}": n for bucket, n in stage.window.dropped_by_bucket.items()},
        },
    )
