"""CLI: python -m aidaily <command>

Everything runs locally with no cloud state, which is also what makes the GitHub
Actions version testable: same code, same flags, only the environment differs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .analyze import analyze_events
from .collect import (
    collect,
    read_items_jsonl,
    wait_for_critical,
    write_items_jsonl,
    write_source_report_jsonl,
)
from .config import load_config, validate_critical_sources, validate_delivery
from .dedup import units_from_result
from .factcheck import check_digest
from .l3 import build_events
from .history import PublishedHistory
from .rubric import score_events
from .pipeline import (
    build_digest,
    dedup_report,
    run_dedup_stage,
    select_for_digest,
    write_groups_jsonl,
    write_json,
)
from .publish import deliver_all
from .registry import apply_overrides, assert_provenance_complete, load_ledger, load_registry
from .render import render_brief, render_deep, render_json_feed
from .backfill import local_date, split_by_date
from .state import (
    EXIT_ALREADY_PUBLISHED,
    RunRecord,
    _slot_index,
    append_record,
    gate,
    utcnow_iso,
)

#: "Too early to build today's digest." Its own code, like `EXIT_ALREADY_PUBLISHED`, so that
#: neither condition can ever be read as a failure by the workflow.
EXIT_TOO_EARLY = 11
#: The candidate pool was non-empty but selection produced nothing. Distinct from exit 11
#: ("not yet") and from 10 ("already published"): this one is a bug, and the workflow must
#: not report it as success -- on 2026-10-19 an empty digest shipped with every step green.
EXIT_EMPTY_SELECTION = 12

ROOT = Path(__file__).resolve().parents[2]


def _rel(path: Path) -> str:
    """Display a path relative to the project when possible, else as given.

    `--out-dir` is routinely outside the repository (a CI artefact directory), and
    `Path.relative_to` raises for that case -- which used to crash the run *after* it had
    already produced the digest.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _tz_offset_hours(cfg) -> int:
    """The configured zone's UTC offset, for date bucketing.

    `split_by_date` needs the offset to turn a publication instant into a calendar date, and it
    must use the *configured* zone rather than a hard-coded +8, or a future config change would
    silently file stories one day off.
    """
    return int(datetime.now(ZoneInfo(cfg.timezone)).utcoffset().total_seconds() // 3600)


def _load_sources():
    """Registry + the human correction layer, then assert nothing was lost."""
    sources, _ = apply_overrides(load_registry())
    try:
        assert_provenance_complete(sources, load_ledger())
    except Exception as exc:  # noqa: BLE001
        print(f"warning: provenance guard: {exc}", file=sys.stderr)
    return sources


def cmd_collect(args: argparse.Namespace) -> int:
    cfg = load_config(env={} if args.no_env else None)
    sources = _load_sources()
    validate_critical_sources(cfg, {s.source_id for s in sources})

    for warning in validate_delivery(cfg):
        print(f"note: {warning}", file=sys.stderr)

    report = asyncio.run(
        collect(
            sources,
            cfg,
            concurrency=args.concurrency,
            limit=args.limit,
            only=args.only.split(",") if args.only else None,
        )
    )

    if args.wait_critical:
        # Override the configured wait for ad-hoc runs; 0 disables it entirely.
        cfg = cfg.model_copy(update={"run": cfg.run.model_copy(update={"critical_wait_minutes": args.wait_critical})})
        still_missing = asyncio.run(wait_for_critical(sources, report, cfg))
        if still_missing:
            print(f"::warning::关键源在等待窗口内仍未发布当日版：{', '.join(still_missing)}")
        else:
            print("关键源已全部拿到当日版")

    out = Path(args.out) if args.out else ROOT / "data" / "raw" / "items.jsonl"
    write_items_jsonl(out, report.items)
    report_path = ROOT / "data" / "state" / "collect.jsonl"
    write_source_report_jsonl(report_path, report.results)

    stats = report.stats
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"\nitems -> {_rel(out)}")
    print(f"source attempts -> {_rel(report_path)}")

    if args.show_failures:
        print("\n--- 未成功的源 ---")
        for r in sorted(report.results, key=lambda r: r.verdict):
            if r.verdict not in ("ok", "not_modified"):
                print(f"  {r.verdict:9} {r.source_id:52} {r.detail[:80]}")
        print("\n--- 跳过的源 ---")
        for sid, why in report.skipped:
            print(f"  {sid:52} {why}")
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    """Replay the window + L2 dedup stages over a stored items file (no network)."""
    cfg = load_config(env={} if args.no_env else None)
    items = read_items_jsonl(args.items)
    if not items:
        print(f"no items in {args.items}", file=sys.stderr)
        return 1

    stage = run_dedup_stage(items, cfg)
    report = dedup_report(stage)

    out = Path(args.out) if args.out else ROOT / "data" / "state" / "dup_groups.jsonl"
    write_groups_jsonl(out, stage)
    report_path = ROOT / "data" / "state" / "dedup_report.json"
    write_json(report_path, report)

    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\ngroups -> {_rel(out)}")
    print(f"report -> {_rel(report_path)}")
    return 0


def _drop_events(digest: Digest, event_ids: set[str]) -> Digest:
    """A copy of the digest with the given events removed from both sections and the list.

    Used when fact-check finds an event that cannot be published (a date in the future, a URL
    that is not in the source data). The alternative was discarding the whole issue, which on
    2026-10-19 meant four bad AllenAI entries cost the day's 220 stories.
    """
    keep = [e for e in digest.top_events if e.event_id not in event_ids]
    sections = {
        name: [e for e in events if e.event_id not in event_ids]
        for name, events in (digest.sections or {}).items()
    }
    counts = dict(digest.counts or {})
    counts["events"] = len(keep)
    counts["multi_source_events"] = sum(1 for e in keep if len(e.source_ids) > 1)
    return digest.model_copy(
        update={
            "top_events": keep,
            "sections": {k: v for k, v in sections.items() if v},
            "counts": counts,
        }
    )


def cmd_run(args: argparse.Namespace) -> int:
    """The full chain: collect -> window -> L2 -> L3 -> analyze -> factcheck -> render."""
    cfg = load_config(env={} if args.no_env else None)
    sources = _load_sources()
    validate_critical_sources(cfg, {s.source_id for s in sources})

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "digests"
    out_dir.mkdir(parents=True, exist_ok=True)

    # **Do not build today's digest before the collection hour.**
    #
    # The digest is defined as "the last 24 hours as of 10:00 Beijing". A run at 02:00 has
    # only two hours of the day behind it, so what it produces is not an early edition of
    # today's issue -- it is a different, meaningless document that then occupies the date.
    # Measured: manual `--force` runs at 00:12 and 01:28 created 2026-10-16 issues built from
    # two hours of news, and they were published, so the site's "today" was a two-hour
    # snapshot the whole morning.
    #
    # A guard rather than a warning, because a warning would still ship the file. Exit 11 is
    # its own code so "too early" is never confused with a failure, the same way exit 10 means
    # "already published".
    digest_date = getattr(args, "date", None) or datetime.now(
        ZoneInfo(cfg.timezone)
    ).strftime("%Y-%m-%d")
    # Derived from `run.at`. The old probe asked for a *field* named publish_hour, found none,
    # and silently fell back to 7 -- so moving the first slot earlier would have made the gate
    # reject a run that was already past it.
    publish_hour = cfg.run.publish_hour()
    now_local = datetime.now(ZoneInfo(cfg.timezone))
    # Only **today** can be "too early". A requested earlier date is a deliberate backfill: its
    # collection window is complete by definition, so the guard does not apply. Without this,
    # rebuilding 10-17 on the 18th was refused as "not complete yet" -- for a day that had
    # already ended.
    is_today = digest_date == now_local.strftime("%Y-%m-%d")
    if not args.allow_early and is_today and now_local.hour < publish_hour:
        print(
            f"now {now_local.strftime('%H:%M')} {cfg.timezone} is before the {publish_hour:02d}:00 "
            f"collection hour; {digest_date} is not complete yet, so no digest is built.",
            file=sys.stderr,
        )
        print("（如需强制生成，加 --allow-early）", file=sys.stderr)
        return EXIT_TOO_EARLY

    # 1) collect (or replay a stored items file)
    report = None
    if args.from_items:
        items = read_items_jsonl(args.from_items)
        print(f"replaying {len(items)} items from {args.from_items}")
    else:
        report = asyncio.run(
            collect(sources, cfg, concurrency=args.concurrency, limit=args.limit)
        )
        items = report.items
        print(json.dumps(report.stats, ensure_ascii=False))

    if not items:
        print("no items collected; nothing to publish", file=sys.stderr)
        return 1

    # 2) window + L2
    #
    # **Route by publication date first.** A story that surfaces today but was published on an
    # earlier date belongs to that date's issue, ranked by importance like everything else -- the
    # archive has to say what happened on the 17th, and it cannot do that if a 10-17 release is
    # only ever seen by the 18th. `split_by_date` returns the target date's items plus a bucket
    # per earlier date; each bucket is rebuilt into its own issue below.
    split = split_by_date(items, digest_date, tz_offset_hours=_tz_offset_hours(cfg))
    if split.late:
        print(json.dumps({"late_items": split.summary()}, ensure_ascii=False))

    stage = run_dedup_stage(split.target, cfg)
    print(json.dumps(dedup_report(stage)["dedup"], ensure_ascii=False))
    if not stage.window.kept:
        print("no items inside the window; nothing to publish", file=sys.stderr)
        return 1

    by_id = {i.item_id: i for i in stage.window.kept}

    # 3) L3 semantic clustering + 4) analysis, both need the LLM
    router, llm_warnings, http = _build_router(args)
    (events, cluster_result, insights, analyze_warnings, history,
     rubric_scores, rubric_sections, run_now, selection_report) = asyncio.run(
        _analyze_async(stage, sources, cfg, router, http, args, digest_date)
    )

    warnings = [*llm_warnings, *analyze_warnings]
    if cluster_result.llm_failed:
        warnings.append("事件聚类过程中大模型不可用，已退化为仅 L2 结果")
    if not cluster_result.judged:
        warnings.append("事件聚类未经过模型判定（候选簇为空或未启用模型）")

    llm_usage = router.budget.snapshot() if router else {}
    if router:
        llm_usage["dead_providers"] = router.stats.dead
        # Non-fatal provider errors too: a provider failing every call with a retired
        # model name used to leave no trace anywhere in the output.
        llm_usage["provider_failures"] = router.stats.failures
        llm_usage["calls_per_provider"] = router.stats.used

    # 5) digest
    digest = build_digest(
        stage, events, sources, cfg,
        report=report, insights=insights, warnings=warnings, llm_usage=llm_usage,
        # `rubric_sections` must travel with the scores: the section is the ranking primary
        # key, and a second selection pass without it re-classifies every row. The tier gate in
        # `select_for_digest` also needs the scores, so omitting them here would publish events
        # the caller never analysed.
        history=history, rubric_scores=rubric_scores,
        rubric_sections=rubric_sections, now=run_now,
        pre_date_ignored=split.ignored,
    )

    # 6) fact check -- a failing digest is not published
    # 6) fact check. Violations that belong to a single event drop that event; only
    #    violations about the digest as a whole stop the issue.
    #
    #    This used to be all-or-nothing, and on 2026-10-19 four AllenAI entries arrived
    #    with a published_at of 2026-10-31 (a placeholder date from the feed). They raised
    #    27 future_date violations, the report said "not ok", and 220 good events were
    #    never published -- the whole day was empty. One bad input must not cost the day.
    check = check_digest(digest, stage.window.kept)
    offending = check.offending_event_ids
    if offending:
        print(f"事实校验：剔除 {len(offending)} 条问题事件", file=sys.stderr)
        digest = _drop_events(digest, offending)
        insights = {k: v for k, v in insights.items() if k in {e.event_id for e in digest.top_events}}
        check = check_digest(digest, stage.window.kept)
    print(json.dumps(check.summary(), ensure_ascii=False))

    # 6.5) images
    #
    #     Fetching happens here, after selection and fact-check, so it only ever runs for the
    #     stories that will actually be published -- thirty candidates instead of three hundred.
    #
    #     It is skippable and it never raises: `cfg.output.images` gates it, and every fetch
    #     inside `media` returns None on failure. An issue without pictures is the same issue.
    images_by_event: dict[str, bytes] = {}
    if cfg.output.images:
        images_by_event = asyncio.run(
            _fetch_images(digest, cfg, limit=cfg.output.images_max)
        )
        print(
            f"配图：{len(images_by_event)} / {len(digest.top_events)} 条拿到图",
            file=sys.stderr,
        )
    # GitHub repositories get their own card: the metadata is rich enough to lay out, and the
    # official Social Preview is a fixed grey template that ignores the site theme.
    #
    # One PNG per repository, stored beside the article images and referenced from the feed
    # `<enclosure>` and the download link. The page itself renders `ghcard.card_html` inline, so
    # the bitmap is only produced for repositories -- a dozen per issue, not hundreds.
    github_cards: dict[str, str] = {}
    if cfg.output.images:
        try:
            github_cards = asyncio.run(_render_github_cards(digest, cfg))
        except Exception:
            github_cards = {}
        if github_cards:
            # **Write the card back onto the event, not only into a local map.**
            #
            # The page renders the HTML card from `repo_meta`, and the RSS needs the PNG URL on
            # the event. An earlier version kept the URLs in `github_cards` alone, so five cards
            # were rendered, uploaded and reported -- and the page showed none of them.
            for event in digest.top_events:
                url = github_cards.get(event.event_id)
                if url and url not in event.image_urls:
                    event.image_urls = [*event.image_urls, url]
            print(f"仓库卡片：{len(github_cards)} 张", file=sys.stderr)

    # 7) render
    brief = render_brief(digest, insights, by_id, max_items=cfg.output.brief.max_items)
    deep = render_deep(digest, insights, by_id, max_items=cfg.output.deep.max_items)
    feed = render_json_feed(digest, insights, site_url=args.site_url)

    brief_path = out_dir / f"{digest.date}.brief.md"
    deep_path = out_dir / f"{digest.date}.deep.md"
    json_path = out_dir / f"{digest.date}.json"

    brief_path.write_text(brief, encoding="utf-8")
    deep_path.write_text(deep, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                # `sections` holds the same Event objects that `top_events` already
                # carries, so serialising both doubled the archived file for no
                # information gain (253 KB/day, ~132 MB of git history per year). The
                # section *layout* is kept; the event bodies are not repeated.
                "digest": digest.model_dump(mode="json", exclude={"sections"}),
                "sections": {k: [e.event_id for e in v] for k, v in digest.sections.items()},
                "insights": {k: vars(v) for k, v in insights.items()},
                "factcheck": check.summary(),
            },
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    # The JSON Feed goes into `site/` with the RSS feed: that is the directory Pages
    # deploys, and both feeds are linked from the page. Writing them to `digests/feed/`
    # built them correctly and published neither.
    feed_dir = out_dir / "site" / "feed"
    feed_dir.mkdir(parents=True, exist_ok=True)
    feed_dir.joinpath("zh.json").write_text(feed, encoding="utf-8")

    print(f"\nevents        : {digest.counts['events']}  (多源 {digest.counts['multi_source_events']})")
    print(f"brief         : {_rel(brief_path)}  ({len(brief)} chars)")
    print(f"deep          : {_rel(deep_path)}  ({len(deep)} chars)")
    print(f"machine json  : {_rel(json_path)}")

    if not check.ok_to_publish:
        # Only digest-wide problems reach here; per-event ones were dropped above.
        print("\n!! 事实校验未通过，不发布：", file=sys.stderr)
        for v in check.blocking[:10]:
            print(f"   {v.kind}: {v.detail}", file=sys.stderr)
        _record_run(digest, {}, "failed", "factcheck failed")
        return 2

    # An empty digest is a failure, not a quiet day.
    #
    # This is the check whose absence let 2026-10-19 ship nothing while every job reported
    # success: selection returned 0 of 220 events, the fact-check had nothing to object to,
    # and the run went green with an empty page. A pipeline that can silently publish zero
    # stories is worse than one that fails loudly -- the failure is invisible for days.
    #
    # The threshold is 1, not a fraction of `max_items`: `max_items` is an upper bound and a
    # genuine quiet day may legitimately carry few stories. Zero is never legitimate on a day
    # with a non-empty pool, so the pool size distinguishes "nothing happened" from "we broke".
    pool_size = int((digest.counts or {}).get("events_considered") or 0)
    if not digest.top_events and pool_size:
        print(
            f"\n!! 事件池有 {pool_size} 条，却选出 0 条 —— 视为故障，不发布",
            file=sys.stderr,
        )
        _record_run(digest, {}, "failed", "empty selection from a non-empty pool")
        return EXIT_EMPTY_SELECTION

    if args.no_deliver:
        print("--no-deliver：跳过分发")
        _record_run(digest, {}, "published", "delivery disabled")
        return 0

    # Same slot derivation as `cmd_gate`, for the same reason: without it a third run of the
    # day is compared against a two-slot schedule and can skip a slot that never published.
    _slot_hours = tuple(t.hour for t in cfg.run.schedule_times())
    _slot = _slot_index(datetime.now(ZoneInfo(cfg.timezone)).hour, _slot_hours)
    should, reason, already = gate(
        digest.date,
        artifact_dir=out_dir,
        slot=_slot,
        slot_hours=_slot_hours,
        # The gate compares this against what was last published. A same-day re-trigger
        # produces a different digest as new items arrive (219 events became 223), and
        # skipping delivery then left the live page describing 219 while its own archived
        # JSON said 223 -- the site contradicted its own data.
        digest_id=f"{digest.date}-{digest.counts.get('events', 0)}",
    )
    if not should:
        print(f"幂等闸门：{reason} —— 跳过分发")
        return EXIT_ALREADY_PUBLISHED
    if already:
        print(f"幂等闸门：{reason}（已完成通道：{', '.join(sorted(already))}）")
    else:
        print(f"幂等闸门：{reason}")

    delivery = asyncio.run(
        deliver_all(
            digest, brief, deep, cfg, dict(os.environ), out_dir,
            site_url=args.site_url, already_done=already,
            # The site needs the three-bucket breakdown and the source bodies; both
            # already exist here, so they are passed rather than re-derived.
            insights=insights, items_by_id=by_id,
            # And the source registry, for the "信息源" page. Passed as plain dicts so the
            # site layer does not depend on the registry's model.
            sources=[s.model_dump() for s in sources],
            # Repository cards, for the RSS enclosure and the download link.
            images=github_cards,
        )
    )
    # Recorded only after delivery, so a run that crashed before publishing does not
    # suppress tomorrow's coverage of the same story. The history describes what readers
    # saw, not what the pipeline attempted.
    written = history.record(digest.top_events, date=digest.date)
    print(f"跨天记忆：记录 {written} 条（窗口 {history.window_days} 天）")
    # Report what deduplication *removed*, not only what it recorded. The count was the
    # missing half: "recorded 60" looks identical whether zero or twenty stories were
    # dropped as repeats, so a broken rule was invisible in the log.
    repeat_stats = (selection_report or {}).get("cross_day_repeats")
    if repeat_stats:
        print(f"跨天去重：剔除/降权 {repeat_stats} 条")
        for example in (selection_report or {}).get("cross_day_examples") or []:
            kind = example.get("matched_on", "?")
            days = example.get("days_ago", "?")
            print(f"  · {kind}/{days}天  {example.get('title', '')[:60]}")

    print("\n分发：" + json.dumps(delivery.summary(), ensure_ascii=False))
    for result in delivery.results:
        if result.skipped and result.detail and "未配置" in result.detail:
            # Loud, because "no email today" is easy to miss otherwise.
            print(f"::warning::{result.channel}: {result.detail}", file=sys.stderr)

    status = "published" if delivery.all_ok else "partial"
    _record_run(digest, delivery.channels, status, reason)
    return 0 if delivery.all_ok else 3


def cmd_backfill(args: argparse.Namespace) -> int:
    """Fold late stories into the issues of the dates they were published on.

    This is the operator entry point for one rule: **a story belongs to the day it was published,
    not the day it was collected.** DeepSeek V4.1 Flash 1017 is a 10-17 release; the 10-17 issue
    closed at 14:38 Beijing and never saw it. Re-running that whole day is not an option -- the raw
    items are pruned -- but the archive still holds the events, and a new story can be added to it
    and re-ranked.
    """
    from .backfill import split_by_date
    from .backfill_merge import merge_late_items

    cfg = load_config(env={} if args.no_env else None)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "digests"
    items = read_items_jsonl(args.items)
    if not items:
        print(f"{args.items} 里没有条目", file=sys.stderr)
        return 1

    offset = _tz_offset_hours(cfg)
    today = datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d")
    split = split_by_date(items, today, tz_offset_hours=offset)

    targets = {args.date: None} if args.date else dict(split.late)
    if not args.date:
        print(json.dumps({"late_by_date": split.summary()["late_by_date"]}, ensure_ascii=False))

    chapters: list[dict[str, object]] = []
    for date_str, bucket in sorted(targets.items()):
        if bucket is None:
            # Explicit --date: take everything published on that date, regardless of routing.
            bucket = [
                i for i in items
                if i.published_at is not None
                and local_date(i.published_at, offset) == date_str
            ]
        archive = out_dir / f"{date_str}.json"
        if not archive.exists():
            chapters.append({"date": date_str, "skipped": "无归档"})
            continue
        payload = json.loads(archive.read_text(encoding="utf-8"))
        digest, insights = _load_archive(payload)
        merged, insights, report = merge_late_items(
            digest, bucket, sources=_load_sources(), cfg=cfg, insights=insights
        )
        report["date"] = date_str
        chapters.append(report)
        if merged.counts.get("late_added"):
            _write_archive(archive, merged, insights, payload)

    print(json.dumps({"chapters": chapters}, ensure_ascii=False))
    return 0


def _load_archive(payload: dict) -> tuple[Digest, dict]:
    """Rebuild the Digest from an archived JSON, reattaching the section layout.

    `digest` is stored with `sections` excluded and the layout kept separately as
    `{category: [event_id]}`; validating `digest` alone yields a Digest whose sections are empty,
    which would silently move every story to "其它".
    """
    from .analyze import EventInsight as _Insight
    from .models import Digest as _Digest

    doc = dict(payload["digest"])
    by_id = {e["event_id"]: e for e in doc.get("top_events", [])}
    doc["sections"] = {
        cat: [by_id[i] for i in ids if i in by_id]
        for cat, ids in (payload.get("sections") or {}).items()
    }
    digest = _Digest.model_validate(doc)
    insights = {k: _Insight(**v) for k, v in (payload.get("insights") or {}).items()}
    return digest, insights


def _write_archive(path: Path, digest: Digest, insights: dict, original: dict) -> None:
    """Write the archive back in the same shape `run` uses, so every reader keeps working."""
    payload = {
        "digest": digest.model_dump(mode="json", exclude={"sections"}),
        "sections": {k: [e.event_id for e in v] for k, v in digest.sections.items()},
        "insights": {k: (vars(v) if hasattr(v, "__dict__") else v) for k, v in insights.items()},
        "factcheck": original.get("factcheck"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已更新 {path.name}：events={digest.counts.get('events')}")


def cmd_backfill(args: argparse.Namespace) -> int:
    """Fold late stories into the issues of the dates they were published on.

    This is the operator entry point for one rule: **a story belongs to the day it was published,
    not the day it was collected.** DeepSeek V4.1 Flash 1017 is a 10-17 release; the 10-17 issue
    closed at 14:38 Beijing and never saw it. Re-running that whole day is not an option -- the raw
    items are pruned -- but the archive still holds the events, and a new story can be added to it
    and re-ranked.
    """
    from .backfill import split_by_date
    from .backfill_merge import merge_late_items

    cfg = load_config(env={} if args.no_env else None)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "digests"
    items = read_items_jsonl(args.items)
    if not items:
        print(f"{args.items} 里没有条目", file=sys.stderr)
        return 1

    offset = _tz_offset_hours(cfg)
    today = datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d")
    split = split_by_date(items, today, tz_offset_hours=offset)

    targets = {args.date: None} if args.date else dict(split.late)
    if not args.date:
        print(json.dumps({"late_by_date": split.summary()["late_by_date"]}, ensure_ascii=False))

    chapters: list[dict[str, object]] = []
    for date_str, bucket in sorted(targets.items()):
        if bucket is None:
            # Explicit --date: take everything published on that date, regardless of routing.
            bucket = [
                i for i in items
                if i.published_at is not None
                and local_date(i.published_at, offset) == date_str
            ]
        archive = out_dir / f"{date_str}.json"
        if not archive.exists():
            chapters.append({"date": date_str, "skipped": "无归档"})
            continue
        payload = json.loads(archive.read_text(encoding="utf-8"))
        digest, insights = _load_archive(payload)
        merged, insights, report = merge_late_items(
            digest, bucket, sources=_load_sources(), cfg=cfg, insights=insights
        )
        report["date"] = date_str
        chapters.append(report)
        if merged.counts.get("late_added"):
            _write_archive(archive, merged, insights, payload)

    print(json.dumps({"chapters": chapters}, ensure_ascii=False))
    return 0


def _load_archive(payload: dict) -> tuple[Digest, dict]:
    """Rebuild the Digest from an archived JSON, reattaching the section layout.

    `digest` is stored with `sections` excluded and the layout kept separately as
    `{category: [event_id]}`; validating `digest` alone yields a Digest whose sections are empty,
    which would silently move every story to "其它".
    """
    from .analyze import EventInsight as _Insight
    from .models import Digest as _Digest

    doc = dict(payload["digest"])
    by_id = {e["event_id"]: e for e in doc.get("top_events", [])}
    doc["sections"] = {
        cat: [by_id[i] for i in ids if i in by_id]
        for cat, ids in (payload.get("sections") or {}).items()
    }
    digest = _Digest.model_validate(doc)
    insights = {k: _Insight(**v) for k, v in (payload.get("insights") or {}).items()}
    return digest, insights


def _write_archive(path: Path, digest: Digest, insights: dict, original: dict) -> None:
    """Write the archive back in the same shape `run` uses, so every reader keeps working."""
    payload = {
        "digest": digest.model_dump(mode="json", exclude={"sections"}),
        "sections": {k: [e.event_id for e in v] for k, v in digest.sections.items()},
        "insights": {k: (vars(v) if hasattr(v, "__dict__") else v) for k, v in insights.items()},
        "factcheck": original.get("factcheck"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已更新 {path.name}：events={digest.counts.get('events')}")


def _record_run(digest, channels: dict[str, str], status: str, note: str) -> None:
    append_record(
        RunRecord(
            date=digest.date,
            status=status,
            at=utcnow_iso(),
            digest_id=f"{digest.date}-{digest.counts.get('events', 0)}",
            channels=channels,
            counts={k: int(v) for k, v in digest.counts.items()},
            llm=digest.llm_usage,
        )
    )


def cmd_gate(args: argparse.Namespace) -> int:
    """Cheap first step for every scheduled trigger.

    Exit 0 means "proceed"; exit 10 means "today is already published, stop here". Having
    its own exit code keeps "nothing to do" from ever being mistaken for a failure.
    """
    date = args.date or datetime.now(ZoneInfo(load_config(env={}).timezone)).strftime("%Y-%m-%d")
    if args.force:
        print(json.dumps({"date": date, "publish": True, "reason": "--force"}, ensure_ascii=False))
        return 0
    # 传产物目录：账本说「已发布」而归档不存在时，必须重建而不是永远跳过。
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else ROOT / "data" / "digests"

    # Several collections a day are several publications of the same date. Keying the gate on the
    # date alone made every later run a permanent no-op. A slot is the scheduled collection the run
    # belongs to; a same-slot retry still skips, which is what the gate is for.
    #
    # `slot` comes from **`run.slots`**, not a fixed 13:00 split. The old `0 if hour < 13 else 1`
    # collapsed three collections into two, so the 20:00 run was told it repeated the 12:00 slot
    # and skipped -- the evening's news never got published.
    cfg_for_slot = load_config(env={} if getattr(args, "no_env", False) else None)
    tz = cfg_for_slot.timezone
    slot_hours = tuple(t.hour for t in cfg_for_slot.run.schedule_times())
    now_local_slot = datetime.now(ZoneInfo(tz))
    slot = _slot_index(now_local_slot.hour, slot_hours)

    # "Too early" belongs here, not only in `run`.
    #
    # The gate is the cheap step; `run` is the ten-minute one. Before this check the gate said
    # "go" for a trigger that arrived before the collection window, the workflow paid for a full
    # collection, and `run` then answered exit 11 -- which the gate step reported as a failure
    # because it only understood 0 and 10. Both halves of that are fixed: the decision is made
    # where it is cheap, and exit 11 is treated as the normal no-op it is.
    #
    # Only *today* can be too early. A requested earlier date is a deliberate backfill whose
    # window has already closed, so the guard must not apply to it.
    publish_hour = cfg_for_slot.run.publish_hour()
    is_today = date == now_local_slot.strftime("%Y-%m-%d")
    if not getattr(args, "allow_early", False) and is_today and now_local_slot.hour < publish_hour:
        print(json.dumps({
            "date": date,
            "publish": False,
            "reason": f"too early: {now_local_slot.strftime('%H:%M')} {tz} is before the "
                      f"{publish_hour:02d}:00 collection hour",
            "done_channels": {},
        }, ensure_ascii=False))
        return EXIT_TOO_EARLY

    should, reason, done = gate(
        date, artifact_dir=out_dir, slot=slot, slot_hours=slot_hours
    )
    print(json.dumps(
        {"date": date, "publish": should, "reason": reason, "done_channels": done},
        ensure_ascii=False,
    ))
    return 0 if should else EXIT_ALREADY_PUBLISHED




#: A picture used by this many stories is site furniture, not a story picture.
#: Measured: two AWS decorations each appeared under five unrelated articles.
SHARED_IMAGE_LIMIT = 3

#: Hard ceiling on the whole image stage. A picture is decoration; an issue that never
#: ships is worse than an issue with fewer pictures.
#: Hard ceiling on the whole image stage.
#:
#: 150s was measured to be too tight: with 40 events, two candidate pages each and up to
#: three images per page at concurrency 12, the stage hit the cap before finishing and
#: produced **zero** pictures while reporting nothing but a timeout count. 300s lets a
#: normal day complete and still bounds a pathological one.
#: Hard ceiling on the whole image stage. A picture is decoration; an issue that never ships is
#: worse than an issue with fewer pictures.
#:
#: Sized for the whole issue, not the first forty: measured 2026-10-23 at 96 events, which at
#: concurrency 24 finishes in well under a minute. The ceiling exists for a day when several
#: publishers hang at once, not to bound a normal run.
IMAGE_STAGE_SECONDS = 600


async def _fetch_images(
    #: Forty stories, twenty-four in flight. The count is the reader-visible top of the digest,
    #: not the whole issue; the concurrency is high enough that forty page loads finish well
    #: inside the stage budget, and low enough that no publisher sees a burst.
    digest: "Digest", cfg: "AppConfig", *, limit: int = 10_000, concurrency: int = 32
) -> dict[str, list[bytes]]:
    """WebP bytes for every published event, one to four pictures each. Never raises.

    The URL tried first is the most *direct* one -- the original publisher rather than an
    aggregator, because a picture taken from a page that copied the story is a picture of a copy.

    A story often has more than one picture and the layout shows them side by side: a wide hero,
    a tall diagram, a long terminal screenshot. Cropping those to a single frame would throw away
    what the reader came for, so `images_for` returns all usable ones and the page keeps each in
    its own proportions.

    Bounded concurrency: forty articles means forty page fetches plus a few hundred image fetches,
    and firing them all at once gets the run rate-limited by the more careful publishers.
    """
    from . import media, mediastore
    from .l3 import _url_directness

    events = digest.top_events[:limit]
    if not events:
        return {}

    # **A hard deadline for the whole stage.**
    #
    # Measured on 2026-10-22: publish sat in this function for over thirty minutes and was killed
    # by the job timeout. The per-request timeouts were fine; what was missing was a bound on the
    # stage as a whole, so one slow publisher could hold the entire issue hostage.
    #
    # A picture is decoration. Twenty seconds of them is worth having; five minutes is not, and
    # an issue that never ships is worse than an issue with fewer pictures.
    deadline = asyncio.get_event_loop().time() + IMAGE_STAGE_SECONDS

    out: dict[str, list[bytes]] = {}
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async with media.default_client() as client:

        async def one(event) -> tuple[str, list[bytes]]:
            if asyncio.get_event_loop().time() > deadline:
                return event.event_id, []
            # **Only the publisher own page.** Fetching a picture off an aggregator would mean
            # republishing someone else copied-and-redistributed asset -- the aggregator does not
            # own it, and neither do we. When an event has no direct publisher URL it gets the
            # generated placeholder instead, which claims nothing about the story.
            direct = [u for u in (event.all_urls or []) if _url_directness(u) == 0]
            if not direct:
                return event.event_id, []
            async with semaphore:
                # Two candidates: the first direct source, then the next. Beyond that the gain
                # stops justifying the extra requests.
                for candidate in direct[:2]:
                    if asyncio.get_event_loop().time() > deadline:
                        break
                    images = await media.images_for(client, candidate, keep=3)
                    if images:
                        return event.event_id, images
            return event.event_id, []

        # `wait_for` is the guarantee, not the per-request timeout. The inner guards stop new
        # work; this stops work already in flight when the deadline passes.
        tasks = [asyncio.ensure_future(one(e)) for e in events]
        done, pending = await asyncio.wait(tasks, timeout=IMAGE_STAGE_SECONDS)
        for task in pending:
            task.cancel()
        if pending:
            print(
                f"配图：{len(pending)} 条超时未完成，已放弃（上限 {IMAGE_STAGE_SECONDS}s）",
                file=sys.stderr,
            )
        for task in done:
            try:
                event_id, images = task.result()
            except Exception:
                continue
            out[event_id] = images

    # **Cross-story de-duplication: a picture shared by many stories is site furniture.**
    #
    # Measured on the 2026-10-21 issue: two AWS blog images appeared under *five* different
    # articles. Both were brand decoration -- a wireframe-cube motif and a gradient-orb banner --
    # and neither had anything to do with any of those stories. They passed every per-image
    # check because they are real, large, well-shaped photographs; they are simply not *about*
    # the article they sit next to.
    #
    # A per-story hash comparison cannot catch this, because the bytes differ per page. What
    # gives it away is the reuse: no genuine article image appears under three unrelated
    # headlines. So any hash used by `SHARED_IMAGE_LIMIT` or more stories is dropped everywhere.
    #
    # The cost is real and worth stating: a publisher whose every article carries the same hero
    # banner loses all of them. That is the right trade -- a banner repeated five times tells the
    # reader nothing, while an empty slot at least admits there is no picture.
    # Perceptual fingerprints, not byte hashes: the same decoration is served at several sizes,
    # so a byte comparison misses it while the picture is visibly identical.
    counts: dict[str, int] = {}
    for images in out.values():
        for data in images:
            digest_of = media.perceptual_hash(data)
            counts[digest_of] = counts.get(digest_of, 0) + 1

    shared = {h for h, n in counts.items() if n >= SHARED_IMAGE_LIMIT}
    if shared:
        print(f"配图：丢弃 {len(shared)} 张被多篇文章共用的站点装饰图", file=sys.stderr)
        for event_id, images in list(out.items()):
            out[event_id] = [d for d in images if media.perceptual_hash(d) not in shared]

    # **No picture is better than a fake one.**
    #
    # An earlier version filled every gap with a deterministic gradient so the layout would never
    # show a hole. Seen on a real page it reads as a broken image: a large coloured rectangle
    # above a headline looks like a failed load, not like a design decision, and it pushes the
    # text the reader came for below the fold.
    #
    # So the rule is simply: a story with a real picture shows it, a story without one shows
    # nothing. The page handles both -- `image_html` is empty and the item closes up.
    #
    # `media.placeholder` is kept for the cases where a bitmap is genuinely required (a share
    # card needs *something*), but it is no longer used to pad the article list.
    out = {k: v for k, v in out.items() if v}

    urls = mediastore.store_images(out, date=digest.date)
    for event in digest.top_events:
        event.image_urls = urls.get(event.event_id, [])
    return out



async def _attach_repository_age(events: list, stage) -> int:
    """Write each repository creation date onto the items that carry it. Returns how many.

    Only repository stories are touched: an aggregator page that mentions GitHub is not a
    repository, and asking the API about it would waste a request and attach a wrong date.

    The date lands in `item.metrics["repo_created"]` because that is what `heat` reads. Putting
    it on the event instead would mean a field that exists for one ranking rule and is
    meaningless everywhere else.
    """
    from . import github_meta

    by_id = {i.item_id: i for i in stage.window.kept}

    # Which events are about a repository, and which repository.
    targets: dict[str, str] = {}
    for event in events:
        for url in event.all_urls or []:
            repo = github_meta.repo_of(url)
            if repo:
                targets[event.event_id] = repo
                break
    if not targets:
        return 0

    meta = await github_meta.fetch_many(sorted(set(targets.values())))
    attached = 0
    for event in events:
        repo = targets.get(event.event_id)
        if not repo:
            continue
        data = meta.get(repo) or {}
        created = str(data.get("created") or "")
        if not created:
            continue
        for item_id in event.member_item_ids:
            item = by_id.get(item_id)
            if item is None:
                continue
            item.metrics = {**(item.metrics or {}), "repo_created": created}
            attached += 1
    if attached:
        print(f"仓库年龄：{len(targets)} 个仓库，{attached} 条记录已标注创建日期", file=sys.stderr)
    return attached


async def _render_github_cards(digest: "Digest", cfg: "AppConfig") -> dict[str, str]:
    """PNG card URL for every GitHub repository among the published events. Never raises.

    The page uses HTML cards, so this exists only for the two consumers that cannot read HTML: the
    RSS `<enclosure>` and the download link. Rendering is therefore limited to repositories --
    a handful per issue rather than every story.
    """
    from . import ghcard, github_meta, mediastore

    # Which events are about a repository? The first direct URL decides; an aggregator page that
    # happens to mention GitHub is not a repository story.
    targets: dict[str, str] = {}
    for event in digest.top_events:
        for url in event.all_urls or []:
            repo = github_meta.repo_of(url)
            if repo:
                targets[event.event_id] = repo
                break
    if not targets:
        return {}

    meta = await github_meta.fetch_many(sorted(set(targets.values())))
    if not meta:
        return {}

    pngs: dict[str, bytes] = {}
    for event_id, repo in targets.items():
        data = meta.get(repo)
        if not data:
            continue
        png = await ghcard.card_png(
            "light",
            full_name=data["full_name"],
            description=data["description"],
            stars=data["stars"],
            forks=data["forks"],
            contributors=data.get("contributors"),
            discussions=data.get("discussions"),
            languages=data.get("languages"),
            license_=data.get("license", ""),
        )
        if png:
            pngs[event_id] = png

    if not pngs:
        return {}

    urls = mediastore.store_images({k: [v] for k, v in pngs.items()}, date=digest.date)
    return {k: v[0] for k, v in urls.items() if v}
async def _analyze_async(stage, sources, cfg, router, http, args, run_date: str):
    """L3 + analysis in one event loop, with the HTTP client closed on the way out.

    They share a loop because an `httpx.AsyncClient` is bound to the loop that created
    its connections: running each stage under its own `asyncio.run()` leaves the client
    attached to a closed loop.
    """
    try:
        # L3 clusters *units* (one per L2 group), never raw items: feeding it raw items
        # would split apart the duplicates L2 just merged.
        units = units_from_result(stage.result, stage.window.kept)
        source_groups = {s.source_id: (s.dedup_group or s.source_id) for s in sources}
        events, cluster_result = await build_events(
            units,
            router,
            source_groups=source_groups,
            entity_overlap_min=cfg.dedup.l3.entity_overlap_min,
            time_bucket_hours=cfg.dedup.l3.time_bucket_hours,
            confidence_threshold=cfg.dedup.l3.confidence_threshold,
            max_clusters=cfg.dedup.l3.max_clusters,
            judge_concurrency=cfg.dedup.l3.judge_concurrency,
        )
        by_id = {i.item_id: i for i in stage.window.kept}

        # Select *before* analysing. The digest publishes `deep.max_items` events chosen by
        # rank + diversity, while analysis used to run on `events[:limit]` in arrival order
        # -- two different sets that overlapped by 8 of 40. Every other model call was paid
        # for and discarded, and the published items mostly fell back to a source excerpt.
        # Cross-day memory. The config field `dedup.l3.cross_day_window_days` existed and was
        # read by nothing, so a story that led yesterday's issue could lead today's with no
        # new information -- the most visible quality problem a daily can have.
        history_notes: list[str] = []

        # **One timestamp for the whole run.**
        #
        # `select_for_digest` falls back to `datetime.now()` when `now` is None, and this run
        # selects three times: the candidate pool, the final list the model's scores feed,
        # and `build_digest`'s own recomputation. Each call therefore ranked against a
        # slightly different clock. Recency is a scoring term, so events sitting near a score
        # boundary swapped places between calls -- and the digest analysed one set of sixty
        # while publishing a different sixty, leaving twenty entries with no insight and the
        # source's English headline on a Chinese page.
        #
        # One instant is now used everywhere, and it is handed to `build_digest` so its
        # selection is identical by construction rather than by timing luck.
        #
        # When `--date` pins a day, the instant must move with it: the digest's date,
        # its window and (via the window) which items are in scope all derive from this
        # value. Leaving it at `now` while pinning the filename elsewhere would produce a
        # file named for one day containing another day's selection.
        if getattr(args, "date", None):
            from zoneinfo import ZoneInfo as _ZI
            _d = datetime.strptime(args.date, "%Y-%m-%d")
            # End of the pinned day, not noon: a replay covers everything published that
            # day, and anything after noon would otherwise be flagged `future_date`.
            run_now = datetime.now(_ZI(cfg.timezone)).replace(
                year=_d.year, month=_d.month, day=_d.day, hour=23, minute=59, second=59, microsecond=0
            ).astimezone(timezone.utc)
        else:
            run_now = datetime.now(timezone.utc)
        #
        # The archive directory comes from the caller's arguments: this function is handed
        # `args`, and `out_dir` is resolved in `cmd_run`. Re-deriving it here from the same
        # default would silently disagree with an explicit `--out-dir`.
        #
        # Rebuilt from the archived digests when the record is missing, because the archive
        # is authoritative and the history file is only a cache over it. Starting from empty
        # would silently re-publish a week of old news.
        archive_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "digests"
        # Resolution order: the flag, then `AIDAILY_HISTORY_FILE`, then the committed path.
        #
        # The environment variable exists for tests: a fixture story matched a real archived
        # event as "the same message" and was dropped from the digest, so the suite failed for
        # a reason unrelated to the code under test. An isolated run needs an isolated memory.
        history_path = getattr(args, "history_file", None) or os.environ.get("AIDAILY_HISTORY_FILE")
        history = PublishedHistory(
            Path(history_path) if history_path
            else ROOT / "data" / "state" / "published_history.jsonl",
            window_days=cfg.dedup.l3.cross_day_window_days,
        )
        history.load()
        if not history._index and list(archive_dir.glob("????-??-??.json")):
            rebuilt = history.rebuild_from_archives(archive_dir)
            # Kept in a local list: `analyze_warnings` is created further down, and a
            # warning about the history must reach the reader whether or not analysis runs.
            history_notes.append(f"跨天去重记录缺失，已从 {rebuilt} 条归档事件重建")

        # --- Repository age, before anything is scored ---
        #
        # GitHub Trending has no publication date, so every repository there is scored as
        # "unknown freshness". That conflates a project created last week with one created two
        # years ago that merely had a busy afternoon. Measured 2026-10-23:
        # `anthropics/knowledge-work-plugins` placed third; GitHub says it was created
        # 2026-01-23, nine months earlier, and it trended because a commit landed that morning.
        #
        # The date is one API call per repository, and there are a handful per issue. Failure is
        # silent: an entry with no age keeps the neutral freshness it had before.
        try:
            await _attach_repository_age(events, stage)
        except Exception as exc:  # noqa: BLE001
            print(f"仓库年龄：获取失败（{type(exc).__name__}），按未知处理", file=sys.stderr)

        # --- Rubric pass: two phases, so model calls land on candidates that can matter ---
        #
        # Phase 1 ranks by formula and returns the top of the list **without** the diversity
        # pass. Scoring all ~280 events would cost ~28 batched calls to grade rows that can
        # never reach the digest; the pool is what the final selection actually draws from,
        # with headroom so a story the formula underrates can still be promoted by the model.
        rubric_scores: dict[str, float] = {}
        rubric_result = None
        pool_target = max(cfg.output.deep.max_items * 2, cfg.output.deep.max_items + 40)
        pool, _ = select_for_digest(
            events, stage, sources, cfg, history=history, pool_only=pool_target,
            now=run_now, today=run_date,
        )
        rubric_result = await score_events(
            pool, router,
            batch_size=cfg.llm.batch_size.rubric,
            concurrency=cfg.llm.batch_size.rubric_concurrency,
            # Two independent samples, averaged (see `rubric.py`). Configurable so the cost of
            # the second pass can be weighed against the stability it buys.
            passes=cfg.quality.score_passes,
        )
        rubric_scores = rubric_result.scores

        # **How the order was decided belongs in the log, not only in the JSON.**
        #
        # A reader who sees an odd ordering needs to know whether the model chose it
        # or it fell back to the formula. Those are different problems: one is a
        # grading question, the other is an outage.
        _mode_label = {
            "llm": "模型排序",
            "degraded": "模型排序（部分降级）",
            "formula": "公式排序（模型不可用）",
        }
        print("  排序依据        %s" % _mode_label.get(rubric_result.mode, rubric_result.mode))

        rubric_note = (
            f"rubric 评分 {rubric_result.coverage}"
            f"（标准来源：{rubric_result.profile_source}）"
        )
        if rubric_result.unknown_ids:
            # Recorded, not silently dropped. The ids themselves are discarded, but a model
            # inventing rows is worth surfacing.
            rubric_note += f"；模型返回了 {rubric_result.unknown_ids} 个未发送的 id（已丢弃）"
        if rubric_result.failed_batches:
            rubric_note += f"；{rubric_result.failed_batches} 批失败（这些条目仍用公式分）"
        history_notes.append(rubric_note)

        # Phase 2: the real selection, now that the model's judgement is on the table.
        selected, selection_report = select_for_digest(
            events, stage, sources, cfg, history=history, rubric_scores=rubric_scores,
            rubric_sections=getattr(rubric_result, "sections", None),
            rubric_mode=getattr(rubric_result, "mode", ""),
            now=run_now, today=run_date,
        )

        # Print what selection decided, not only what it returned. A run that publishes 0 of
        # 218 events has to say why in its own log; on 2026-10-19 the archive recorded
        # "events: 0, considered: 219" and nothing else, so the cause had to be guessed at from
        # the source. The report already carries every reason -- it was simply never shown.
        print("选择：%d / %d 事件" % (len(selected), len(events)))
        for key in (
            "relevance_floor",
            "relevance_floor_dropped",
            "relevance_missing_dropped",
            "pool_size",
        ):
            if key in (selection_report or {}):
                print("  %-26s %s" % (key, selection_report[key]))
        for example in (selection_report or {}).get("relevance_dropped_examples") or []:
            print("  · focus=%s %s  %s" % (
                example.get("focus"), example.get("reason"), str(example.get("title"))[:52]))

        # The merge audit has to be visible in the run log, not only in the JSON. The failure it
        # catches -- one entry carrying several unrelated stories -- is invisible from the
        # outside until a reader clicks a link and lands somewhere else.
        audit = (selection_report or {}).get("merge_audit") or {}
        if audit.get("checked") is False:
            print("  合并自检        未运行：%s" % audit.get("error"))
        else:
            count = int(audit.get("suspicious_events") or 0)
            print("  合并自检        可疑 %d 条" % count)
            for example in audit.get("examples") or []:
                print("  · %s" % str(example.get("title"))[:64])
                print("      %s" % "；".join(example.get("reasons") or []))

        # The limit must cover everything that will be published, not just "the first N".
        # When it did not, the items past the cut fell back to the source's own headline --
        # and for an English feed that put English sentences on a Chinese page. Defaulting
        # to the full selected set means the digest's language rule holds by construction
        # rather than by luck.
        analyse = selected[: args.analyze_limit] if args.analyze_limit else selected

        if len(analyse) < len(selected):
            analyse_note = (
                f"分析上限 {len(analyse)} 少于发布条数 {len(selected)}，"
                f"后 {len(selected) - len(analyse)} 条将回落为来源原文（可能为外文）"
            )
        else:
            analyse_note = None

        insights, analyze_warnings = await analyze_events(
            analyse, by_id, router, limit=None
        )
        if analyse_note:
            analyze_warnings = [*analyze_warnings, analyse_note]
        # `rubric_sections` travels with the scores: the section is the ranking's primary key,
        # so the caller that re-selects with the scores must receive the sections too, or the
        # final order would fall back to the rule-based classifier for rows the model classified.
        return (events, cluster_result, insights, analyze_warnings + history_notes,
                history, rubric_scores, getattr(rubric_result, "sections", None), run_now,
                selection_report)
    finally:
        if http is not None:
            await http.aclose()


def _build_router(args: argparse.Namespace):
    """Build the LLM router from the environment, or explain why there is none.

    Returns (router | None, warnings, http_client | None); the caller owns the client.
    """
    import os

    from .llm import Budget, Router, providers_from_env

    if args.no_llm:
        return None, ["--no-llm：本次运行未调用大模型"], None

    warnings: list[str] = []
    env = dict(os.environ)

    if args.relay_keys:
        path = Path(args.relay_keys)
        if path.exists():
            # Read the key file into the one env var the router looks at, so keys never
            # pass through a config file inside the repository.
            env["RELAY_KEYS_JSON"] = path.read_text(encoding="utf-8")
        else:
            warnings.append(f"relay 密钥文件不存在：{path}")

    # Validate the relay payload here, where a message can still reach the reader.
    #
    # `providers_from_env` swallows a `json.JSONDecodeError` and returns no relay providers,
    # which is the same "configured but silently ignored" failure this section already
    # documents -- just one layer down. A secret stored through a shell pipeline can arrive
    # UTF-16 encoded or with a BOM, and the symptom is not an error: it is a digest that
    # quietly degrades to English with two providers instead of a hundred.
    relay_raw = env.get("RELAY_KEYS_JSON")
    if relay_raw:
        try:
            rows = json.loads(relay_raw.lstrip("\ufeff"))
            if not isinstance(rows, list):
                raise ValueError("not a JSON list")
            env["RELAY_KEYS_JSON"] = json.dumps(rows)
            warnings.append(f"中转密钥已读取：{len(rows)} 条")
        except (TypeError, ValueError) as exc:
            warnings.append(
                f"RELAY_KEYS_JSON 存在但无法解析（{type(exc).__name__}: {str(exc)[:60]}）；"
                f"本次不使用中转。长度 {len(relay_raw)} 字节，"
                f"首字节 {relay_raw[:1]!r}"
            )
            env.pop("RELAY_KEYS_JSON", None)

    # Relay is enabled by **either** a key file or an already-populated `RELAY_KEYS_JSON`.
    #
    # The gate used to be `include_relay=bool(args.relay_keys)` -- the flag alone. The
    # workflow sets `RELAY_KEYS_JSON` from a secret and calls `run` without the flag, so in
    # production the relay was never consulted: the secret was configured, the environment
    # variable was populated, and the router silently ignored all of it, degrading to
    # rule-based English summaries with no error anywhere. A configured credential that the
    # code declines to read is indistinguishable from a missing one, which is exactly the
    # failure this project keeps having to fix.
    providers = providers_from_env(
        env, include_relay=bool(args.relay_keys) or bool(env.get("RELAY_KEYS_JSON"))
    )
    if not providers:
        # The accumulated warnings are kept, not replaced.
        #
        # Returning a fresh one-element list discarded the relay-parse warning -- so the
        # single message explaining *why* there were no providers was thrown away on the
        # exact path where it is the only useful information. "No keys found" and "a secret
        # arrived unparseable" need completely different responses from an operator, and
        # only one of them was ever shown.
        return None, [*warnings, "未找到任何可用的模型密钥，本次未调用大模型"], None

    cfg = load_config(env={})
    budget = Budget(
        max_calls=cfg.llm.max_calls_per_run, max_tokens=cfg.llm.max_tokens_per_run
    )
    http = httpx.AsyncClient(timeout=cfg.llm.request_timeout_s)
    router = Router(
        providers, http, budget, env=env,
        relay_max_calls=cfg.llm.relay_max_calls_per_run,
    )
    warnings.append(
        f"模型供应商 {len(providers)} 个（{', '.join(p.id for p in providers[:4])}"
        + ("…" if len(providers) > 4 else "") + "）"
    )
    return router, warnings, http


def cmd_leaderboard(args) -> int:
    """Refresh the leaderboard page without building a digest.

    Exists so a workflow run that publishes nothing (the gate said today is already done) can
    still update this one page. It reads the snapshot, rewrites one file, and touches nothing
    else -- no collection, no analysis, no delivery.
    """
    from .leaderboard import refresh_site_page

    changed, note = refresh_site_page(ROOT, max_age_hours=args.max_age_hours)
    print(note)
    # Exit 0 either way: "already fresh" is success, and a failed fetch must not paint a
    # scheduled run red when every other channel worked.
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aidaily", description="统一 AI 日报聚合平台")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="采集所有已启用且适配器可用的源")
    c.add_argument("--out", help="items JSONL 输出路径")
    c.add_argument("--concurrency", type=int, default=8)
    c.add_argument("--limit", type=int, help="只采集前 N 个源（调试用）")
    c.add_argument("--only", help="逗号分隔的 source_id 白名单（调试用）")
    c.add_argument("--no-env", action="store_true", help="忽略 AIDAILY_* 环境变量覆盖")
    c.add_argument("--show-failures", action="store_true", help="打印未成功与跳过的源")
    c.add_argument(
        "--wait-critical", type=int, default=None,
        help="关键源当日版缺失时最多等待多少分钟（覆盖配置；0 = 不等待）",
    )
    c.set_defaults(func=cmd_collect)

    d = sub.add_parser("dedup", help="对已采集的 items 跑时间窗 + L2 去重（离线可重放）")
    d.add_argument("--items", default=str(ROOT / "data" / "raw" / "items.jsonl"))
    d.add_argument("--out", help="dup groups JSONL 输出路径")
    d.add_argument("--no-env", action="store_true")
    d.set_defaults(func=cmd_dedup)

    r = sub.add_parser("run", help="完整链路：采集 → 时间窗 → L2 → L3 → 分析 → 校验 → 渲染")
    r.add_argument("--from-items", help="跳过采集，直接重放已存储的 items.jsonl")
    r.add_argument("--out-dir", help="日报输出目录（默认 data/digests）")
    # The cross-day memory. Exposed as a flag because tests must be able to point it at an
    # empty file: reading the real history made a fixture story match a genuine archived
    # event as "the same message" and vanish from the digest, so the suite failed for a
    # reason unrelated to the code under test.
    r.add_argument("--history-file", help="跨天去重记录（默认 data/state/published_history.jsonl）")
    r.add_argument("--concurrency", type=int, default=10)
    r.add_argument("--limit", type=int, help="采集阶段只跑前 N 个源")
    # Defaults to 0 = "no cap", i.e. analyse everything that will be published. A cap below
    # the published count is what put English source headlines on a Chinese page: the items
    # past the cut had no translation to fall back on.
    r.add_argument("--analyze-limit", type=int, default=0,
                   help="最多用模型分析多少个事件（0 = 全部，即覆盖所有发布条目）")
    r.add_argument("--relay-keys", help="第三方中转 key 的 JSON 文件（只读入内存，不落仓库）")
    r.add_argument("--no-llm", action="store_true", help="完全跳过模型调用，产出规则降级版")
    r.add_argument("--no-deliver", action="store_true", help="只生成产物，不分发")
    r.add_argument("--allow-early", action="store_true",
                   help="允许在采集时间（默认 10:00）之前生成当天日报；默认拒绝")
    r.add_argument("--site-url", default="https://example.github.io/ai-daily")
    # `cmd_run` already reads `getattr(args, "date", None)` when deciding `digest_date`;
    # the flag was simply never registered, so a replayed run could only ever be dated
    # "today". Replaying an older items.jsonl (backfill, a restricted-source rerun)
    # needs the date pinned, so expose it here.
    r.add_argument("--date", help="YYYY-MM-DD（默认取配置时区的今天）")
    r.add_argument("--no-env", action="store_true")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="幂等闸门：今天是否还需要发布")
    g.add_argument("--date", help="YYYY-MM-DD（默认取配置时区的今天）")
    g.add_argument("--force", action="store_true", help="忽略账本，强制继续")
    g.add_argument("--no-env", action="store_true")
    # The gate checks that the archive exists, so it needs to know where archives live.
    g.add_argument("--out-dir", help="归档目录（默认 data/digests）")
    g.set_defaults(func=cmd_gate)

    lb = sub.add_parser("leaderboard", help="只刷新模型榜页面，不构建日报")
    lb.add_argument("--max-age-hours", type=float, default=6.0,
                    help="快照超过这个小时数才重新抓取（默认 6）")
    lb.set_defaults(func=cmd_leaderboard)

    b = sub.add_parser(
        "backfill",
        help="把迟到条目并入它发布日期那一天已有的日报，并按重要性重排",
    )
    b.add_argument("--items", default=str(ROOT / "data" / "raw" / "items.jsonl"),
                   help="采集结果 JSONL")
    b.add_argument("--out-dir", help="归档目录（默认 data/digests）")
    b.add_argument("--date", help="只处理这一天（YYYY-MM-DD）；省略则按发布日期自动分组")
    b.add_argument("--no-env", action="store_true")
    b.set_defaults(func=cmd_backfill)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
