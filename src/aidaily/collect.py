"""Collection orchestration: run every enabled source, isolate every failure."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig
from .fetchers import get_fetcher, resolve_adapter
from .fetchers.base import SourceResult
from .http import HttpClient
from .ingest import normalize_raw
from .models import NormalizedItem, RawItem, SourceSpec


@dataclass
class CollectReport:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    results: list[SourceResult] = field(default_factory=list)
    items: list[NormalizedItem] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def stats(self) -> dict[str, object]:
        by_verdict: dict[str, int] = {}
        for r in self.results:
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
        dated = [i for i in self.items if i.published_at]
        return {
            "sources_attempted": len(self.results),
            "sources_skipped": len(self.skipped),
            "sources_ok": by_verdict.get("ok", 0) + by_verdict.get("not_modified", 0),
            "by_verdict": by_verdict,
            "items": len(self.items),
            "items_with_date": len(dated),
            "items_window_source": sum(1 for i in self.items if i.age_bucket == "today_window"),
            "duration_s": round(
                ((self.finished_at or datetime.now(timezone.utc)) - self.started_at).total_seconds(), 1
            ),
        }


def select_sources(specs: list[SourceSpec]) -> tuple[list[SourceSpec], list[tuple[str, str]]]:
    """Split the registry into collectable sources and explained skips.

    A skip always carries a reason. "Silently not collected" is indistinguishable from
    "collected and empty", and that ambiguity is what makes a digest untrustworthy.
    """
    collectable: list[SourceSpec] = []
    skipped: list[tuple[str, str]] = []
    for spec in specs:
        if not spec.enabled:
            skipped.append((spec.source_id, f"disabled ({spec.health_status})"))
        elif spec.needs_credential:
            skipped.append((spec.source_id, f"needs credential: {spec.needs_credential}"))
        elif resolve_adapter(spec) is None:
            skipped.append((spec.source_id, f"adapter not implemented yet: {spec.adapter}"))
        else:
            collectable.append(spec)
    return collectable, skipped


async def collect(
    specs: list[SourceSpec],
    cfg: AppConfig,
    *,
    concurrency: int = 8,
    limit: int | None = None,
    only: list[str] | None = None,
    timeout_s: int | None = None,
) -> CollectReport:
    collectable, skipped = select_sources(specs)
    if only:
        wanted = set(only)
        collectable = [s for s in collectable if s.source_id in wanted]
        skipped += [(s.source_id, "not selected by --only") for s in specs if s.source_id not in wanted]
    if limit:
        collectable = collectable[:limit]

    report = CollectReport(skipped=skipped)
    timeout = timeout_s or cfg.llm.request_timeout_s
    sem = asyncio.Semaphore(concurrency)

    async with HttpClient(
        timeout_s=float(min(timeout, 30)), retries=2, min_host_interval=0.5
    ) as http:

        async def run(spec: SourceSpec) -> SourceResult:
            fetcher = get_fetcher(spec, http)
            if fetcher is None:
                return SourceResult(spec.source_id, "skipped", detail=f"no adapter for {spec.adapter}")
            async with sem:
                return await fetcher.safe_fetch(spec)

        results = await asyncio.gather(*(run(s) for s in collectable))

    now = datetime.now(timezone.utc)
    by_id = {s.source_id: s for s in specs}
    for result in results:
        report.results.append(result)
        spec = by_id[result.source_id]
        for raw in result.items:
            report.items.append(normalize_raw(raw, spec, now))

    report.finished_at = datetime.now(timezone.utc)
    return report


async def wait_for_critical(
    specs: list[SourceSpec],
    report: CollectReport,
    cfg: AppConfig,
    *,
    now: datetime | None = None,
    sleep=asyncio.sleep,
) -> list[str]:
    """Re-fetch the critical sources until their current-day edition exists.

    Why this exists: juya -- the most widely shared Chinese source in the audit -- was
    measured publishing at 09:48 Beijing, and the run starts at 10:00. A twelve-minute
    margin is not a schedule, it is a coincidence. Without this gate a late edition is
    silently replaced by yesterday's, and the digest looks complete while being stale.

    On timeout the caller gets the still-missing ids so the digest can *say* which source
    fell back to T-1, rather than hiding it. A late source never blocks publication.
    """
    critical = [s for s in specs if s.source_id in set(cfg.run.critical_sources)]
    if not critical:
        return []

    tz = ZoneInfo(cfg.timezone)
    now = now or datetime.now(tz)
    deadline = now + timedelta(minutes=cfg.run.critical_wait_minutes)
    by_id = {s.source_id: s for s in specs}
    results_by_id = {r.source_id: r for r in report.results}

    def missing() -> list[str]:
        out: list[str] = []
        for spec in critical:
            result = results_by_id.get(spec.source_id)
            if result is None:
                out.append(spec.source_id)
                continue
            today = datetime.now(tz).strftime("%Y-%m-%d")
            fresh = any(
                item.published_at is not None
                and item.published_at.astimezone(tz).strftime("%Y-%m-%d") == today
                for item in result.items
            )
            if not fresh:
                out.append(spec.source_id)
        return out

    async with HttpClient(timeout_s=20.0, retries=1, min_host_interval=1.0) as http:
        while True:
            gap = missing()
            if not gap:
                return []
            if datetime.now(tz) >= deadline:
                return gap
            await sleep(120)
            for source_id in gap:
                spec = by_id.get(source_id)
                fetcher = get_fetcher(spec, http) if spec else None
                if spec is None or fetcher is None:
                    continue
                result = await fetcher.safe_fetch(spec)
                results_by_id[source_id] = result
                # Replace the previous attempt and re-normalize, so the digest sees the
                # fresh edition rather than the stale one.
                report.results = [r for r in report.results if r.source_id != source_id]
                report.results.append(result)
                report.items = [i for i in report.items if i.source_id != source_id]
                for raw in result.items:
                    report.items.append(normalize_raw(raw, spec, datetime.now(timezone.utc)))


def write_items_jsonl(path: Path | str, items: list[NormalizedItem]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(item.model_dump_json() + "\n")
    return p


def write_source_report_jsonl(path: Path | str, results: list[SourceResult], *, append: bool = True) -> Path:
    """Append one line per source attempt: the raw material for health history."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    mode = "a" if append else "w"
    with p.open(mode, encoding="utf-8") as fh:
        for r in results:
            fh.write(
                json.dumps(
                    {
                        "probed_at": stamp,
                        "source_id": r.source_id,
                        "verdict": r.verdict,
                        "http_status": r.status,
                        "items": len(r.items),
                        "detail": r.detail[:200],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return p


def read_items_jsonl(path: Path | str) -> list[NormalizedItem]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[NormalizedItem] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(NormalizedItem.model_validate_json(line))
    return out
