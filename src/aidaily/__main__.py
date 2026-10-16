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
from .state import EXIT_ALREADY_PUBLISHED, RunRecord, append_record, gate, utcnow_iso

#: "Too early to build today's digest." Its own code, like `EXIT_ALREADY_PUBLISHED`, so that
#: neither condition can ever be read as a failure by the workflow.
EXIT_TOO_EARLY = 11

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
    publish_hour = cfg.run.publish_hour if hasattr(cfg.run, "publish_hour") else 7
    now_local = datetime.now(ZoneInfo(cfg.timezone))
    if not args.allow_early and digest_date == now_local.strftime("%Y-%m-%d") \
            and now_local.hour < publish_hour:
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
    stage = run_dedup_stage(items, cfg)
    print(json.dumps(dedup_report(stage)["dedup"], ensure_ascii=False))
    if not stage.window.kept:
        print("no items inside the window; nothing to publish", file=sys.stderr)
        return 1

    by_id = {i.item_id: i for i in stage.window.kept}

    # 3) L3 semantic clustering + 4) analysis, both need the LLM
    router, llm_warnings, http = _build_router(args)
    (events, cluster_result, insights, analyze_warnings, history,
     rubric_scores, rubric_sections, run_now) = asyncio.run(
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
        history=history, rubric_scores=rubric_scores, now=run_now,
    )

    # 6) fact check -- a failing digest is not published
    check = check_digest(digest, stage.window.kept)
    print(json.dumps(check.summary(), ensure_ascii=False))

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

    if not check.ok:
        print("\n!! 事实校验未通过，不发布：", file=sys.stderr)
        for v in check.violations[:10]:
            print(f"   {v.kind}: {v.detail}", file=sys.stderr)
        _record_run(digest, {}, "failed", "factcheck failed")
        return 2

    if args.no_deliver:
        print("--no-deliver：跳过分发")
        _record_run(digest, {}, "published", "delivery disabled")
        return 0

    should, reason, already = gate(
        digest.date,
        artifact_dir=out_dir,
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
        )
    )
    # Recorded only after delivery, so a run that crashed before publishing does not
    # suppress tomorrow's coverage of the same story. The history describes what readers
    # saw, not what the pipeline attempted.
    written = history.record(digest.top_events, date=digest.date)
    print(f"跨天记忆：记录 {written} 条（窗口 {history.window_days} 天）")

    print("\n分发：" + json.dumps(delivery.summary(), ensure_ascii=False))
    for result in delivery.results:
        if result.skipped and result.detail and "未配置" in result.detail:
            # Loud, because "no email today" is easy to miss otherwise.
            print(f"::warning::{result.channel}: {result.detail}", file=sys.stderr)

    status = "published" if delivery.all_ok else "partial"
    _record_run(digest, delivery.channels, status, reason)
    return 0 if delivery.all_ok else 3


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

    # Two collections a day (07:00 and 19:00 Beijing) are two publications of the same date.
    # Keying the gate on the date alone made the evening run a permanent no-op. A slot is the
    # half-day the run belongs to; a same-slot retry still skips, which is what the gate is for.
    tz = load_config(env={} if getattr(args, "no_env", False) else None).timezone
    now_local_slot = datetime.now(ZoneInfo(tz))
    slot = 0 if now_local_slot.hour < 13 else 1
    should, reason, done = gate(date, artifact_dir=out_dir, slot=slot)
    print(json.dumps(
        {"date": date, "publish": should, "reason": reason, "done_channels": done},
        ensure_ascii=False,
    ))
    return 0 if should else EXIT_ALREADY_PUBLISHED


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
        history = PublishedHistory(
            Path(args.history_file) if getattr(args, "history_file", None)
            else ROOT / "data" / "state" / "published_history.jsonl",
            window_days=cfg.dedup.l3.cross_day_window_days,
        )
        history.load()
        if not history._index and list(archive_dir.glob("????-??-??.json")):
            rebuilt = history.rebuild_from_archives(archive_dir)
            # Kept in a local list: `analyze_warnings` is created further down, and a
            # warning about the history must reach the reader whether or not analysis runs.
            history_notes.append(f"跨天去重记录缺失，已从 {rebuilt} 条归档事件重建")

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
        )
        rubric_scores = rubric_result.scores

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
        selected, _ = select_for_digest(
            events, stage, sources, cfg, history=history, rubric_scores=rubric_scores,
            rubric_sections=getattr(rubric_result, "sections", None),
            now=run_now, today=run_date,
        )

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
                history, rubric_scores, getattr(rubric_result, "sections", None), run_now)
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
    r.add_argument("--no-env", action="store_true")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="幂等闸门：今天是否还需要发布")
    g.add_argument("--date", help="YYYY-MM-DD（默认取配置时区的今天）")
    g.add_argument("--force", action="store_true", help="忽略账本，强制继续")
    g.add_argument("--no-env", action="store_true")
    # The gate checks that the archive exists, so it needs to know where archives live.
    g.add_argument("--out-dir", help="归档目录（默认 data/digests）")
    g.set_defaults(func=cmd_gate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
