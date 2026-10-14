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
from datetime import datetime
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
from .pipeline import (
    build_digest,
    dedup_report,
    run_dedup_stage,
    write_groups_jsonl,
    write_json,
)
from .publish import deliver_all
from .registry import apply_overrides, assert_provenance_complete, load_ledger, load_registry
from .render import render_brief, render_deep, render_json_feed
from .state import EXIT_ALREADY_PUBLISHED, RunRecord, append_record, gate, utcnow_iso

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
    events, cluster_result, insights, analyze_warnings = asyncio.run(
        _analyze_async(stage, sources, cfg, router, http, args)
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
    feed_path = out_dir / "feed" / "zh.json"

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
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(feed, encoding="utf-8")

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

    should, reason, already = gate(digest.date)
    if not should:
        print(f"幂等闸门：{reason} —— 跳过分发")
        return EXIT_ALREADY_PUBLISHED
    if already:
        print(f"幂等闸门：{reason}（已完成通道：{', '.join(sorted(already))}）")

    delivery = asyncio.run(
        deliver_all(
            digest, brief, deep, cfg, dict(os.environ), out_dir,
            site_url=args.site_url, already_done=already,
            # The site needs the three-bucket breakdown and the source bodies; both
            # already exist here, so they are passed rather than re-derived.
            insights=insights, items_by_id=by_id,
        )
    )
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
    should, reason, done = gate(date)
    print(json.dumps(
        {"date": date, "publish": should, "reason": reason, "done_channels": done},
        ensure_ascii=False,
    ))
    return 0 if should else EXIT_ALREADY_PUBLISHED


async def _analyze_async(stage, sources, cfg, router, http, args):
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
        insights, analyze_warnings = await analyze_events(
            events, by_id, router, limit=args.analyze_limit
        )
        return events, cluster_result, insights, analyze_warnings
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

    providers = providers_from_env(env, include_relay=bool(args.relay_keys))
    if not providers:
        return None, ["未找到任何可用的模型密钥，本次未调用大模型"], None

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
    r.add_argument("--analyze-limit", type=int, default=40, help="最多用模型分析多少个事件")
    r.add_argument("--relay-keys", help="第三方中转 key 的 JSON 文件（只读入内存，不落仓库）")
    r.add_argument("--no-llm", action="store_true", help="完全跳过模型调用，产出规则降级版")
    r.add_argument("--no-deliver", action="store_true", help="只生成产物，不分发")
    r.add_argument("--site-url", default="https://example.github.io/ai-daily")
    r.add_argument("--no-env", action="store_true")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="幂等闸门：今天是否还需要发布")
    g.add_argument("--date", help="YYYY-MM-DD（默认取配置时区的今天）")
    g.add_argument("--force", action="store_true", help="忽略账本，强制继续")
    g.add_argument("--no-env", action="store_true")
    g.set_defaults(func=cmd_gate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
