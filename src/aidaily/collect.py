"""Collection orchestration: run every enabled source, isolate every failure."""

from __future__ import annotations
import os
import sys

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
from .fulltext import extract_body
from .expand import expand_all, drain_notes as _drain_expand_notes
from .ingest import normalize_raw
from .catalogue import is_catalogue_row
from .roundup import split_all
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

    **`needs_credential` names the variable, it does not mean the variable is missing.**
    The old check skipped any source with that field set, so a source stayed unusable even
    after its key was supplied -- the site reported 待凭证 forever and there was no way to
    fix it from outside the code. Measured on 2026-10-22: TAVILY_API_KEY was configured and
    the source was still skipped.

    Now the field is read as "this source wants `NAME`", and the source is skipped only when
    `NAME` is actually absent from the environment.
    """
    collectable: list[SourceSpec] = []
    skipped: list[tuple[str, str]] = []
    for spec in specs:
        if not spec.enabled:
            skipped.append((spec.source_id, f"disabled ({spec.health_status})"))
        elif spec.needs_credential and not os.environ.get(spec.needs_credential, "").strip():
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
    concurrency: int = 20,
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

    # Plan the X rotation before any fetch runs: see `x_timeline.plan_run`.
    x_ids = [s.source_id for s in collectable if s.source_type == "x_timeline"]
    if x_ids:
        from .fetchers import x_timeline as _x

        chosen = set(_x.plan_run(x_ids))
        _x_rotation = (_x, x_ids, chosen)
        skipped += [
            (sid, "X rotation: not this run") for sid in x_ids if sid not in chosen
        ]
        collectable = [
            s for s in collectable
            if s.source_type != "x_timeline" or s.source_id in chosen
        ]

    report = CollectReport(skipped=skipped)
    timeout = timeout_s or cfg.llm.request_timeout_s
    sem = asyncio.Semaphore(concurrency)

    by_id = {s.source_id: s for s in specs}

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

        # **Expand inside the client block.**
        #
        # The expansion fetches article pages, so it needs a live `HttpClient`. Calling it after
        # this block closed raised `RuntimeError: HttpClient must be used as an async context
        # manager` on every item; the handler kept the original and the run looked clean, so a
        # whole day passed with 0 of 488 issues expanded and no error surfaced.
        for result in results:
            if not result.items:
                continue
            try:
                result.items = await expand_all(result.items, http)
            except Exception as exc:  # noqa: BLE001 - one bad page must not kill a run
                report.skipped.append(
                    (result.source_id, f"expand failed: {type(exc).__name__}")
                )
            else:
                for src, note in _drain_expand_notes():
                    report.skipped.append((src, note))

        # Fill in the body for feeds that only carry a teaser. This runs inside the client
        # block because it fetches pages, and before splitting so the splitter sees real text.
        # Opt-in per source (`site_fulltext`).
        for result in results:
            spec = by_id.get(result.source_id)
            if spec is None or not getattr(spec, "site_fulltext", False):
                continue
            if not result.items:
                continue
            filled = 0
            for raw in result.items:
                if len(raw.content_text or "") >= 1500:
                    continue
                if not (raw.url or "").startswith(("http://", "https://")):
                    continue
                try:
                    page = await http.get(
                        raw.url, timeout_s=getattr(spec, "timeout_s", None) or 30
                    )
                except Exception:  # noqa: BLE001 - a page that will not load leaves the teaser
                    continue
                if not getattr(page, "ok", False):
                    continue
                body = extract_body(page.body.decode("utf-8", "replace"))
                if body:
                    raw.content_text = body
                    filled += 1
            if filled:
                report.skipped.append(
                    (spec.source_id, f"full text filled for {filled} item(s)")
                )

    now = datetime.now(timezone.utc)
    for result in results:
        report.results.append(result)
        spec = by_id[result.source_id]
        # **Split roundups before normalisation, not after.**
        #
        # A daily roundup arrives as one item titled `2026-10-15` whose body holds the whole
        # day's news. Normalisation computes `item_id`, `simhash`, `title_norm` and the content
        # hash from the title and body, so splitting afterwards would mean rebuilding all of
        # them by hand -- and `NormalizedItem` has no `native_id` to derive a new identity from.
        #
        # Splitting here means the split stories are normalised like any other item, and every
        # downstream stage sees them as ordinary news.
        # **Expand daily issues before splitting.**
        #
        # A roundup feed carries one entry per *issue*, and the news is inside the issue. The
        # splitter works on the body it is given, so it cannot help when that body is a
        # 46-character summary -- measured on `ainewslog`: 480 such items, while one article
        # page held 21 stories. Fetching the page is what turns one line a day into twenty.

        for raw in split_all(result.items):
            item = normalize_raw(raw, spec, now)
            # Catalogue rows are navigation, not news. Any extractor pointed at a
            # listing page produces them, so the guard lives here rather than in one
            # fetcher.
            if is_catalogue_row(item.title):
                report.catalogue_skipped = getattr(report, "catalogue_skipped", 0) + 1
                continue
            report.items.append(item)

    # Move the rotation cursor past the accounts this run actually served.
    if "_x_rotation" in dir():
        _xmod, _all_ids, _planned = _x_rotation
        _served = sum(1 for r in report.results if r.source_id in _planned and r.verdict == "ok")
        _xmod.advance_cursor(len(_all_ids), max(_served, 0))

    report.finished_at = datetime.now(timezone.utc)
    return report


def wait_window(cfg: AppConfig, now: datetime) -> tuple[bool, str]:
    """Whether the freshness gate is meaningful at `now`.

    The gate exists to cover a source that is a few minutes late for a scheduled run, so it is
    anchored on the **schedule**, not on a single hour. Two collections a day means two windows;
    anchoring on `run.at` alone armed the morning and left the evening run waiting for nothing.

    Outside both windows it does nothing but burn twenty minutes: a manual trigger at 02:00
    Beijing is waiting for an edition that will not exist for hours. The first real GitHub run hit
    exactly that -- `collect` sat for the full timeout.
    """
    local = now.astimezone(ZoneInfo(cfg.timezone))
    tz = ZoneInfo(cfg.timezone)
    for hhmm in cfg.run.schedule_times():
        anchor = datetime.combine(local.date(), hhmm, tzinfo=tz)
        # The lead covers a trigger that fires a little early; the tail covers the retry 17
        # minutes later plus GitHub's documented scheduling delay.
        if anchor - timedelta(minutes=30) <= local <= anchor + timedelta(hours=3):
            return True, ""
    first = cfg.run.at_time()
    return False, (
        f"当前 {local:%H:%M} 不在调度窗口（{cfg.timezone}，"
        f"{first:%H:%M} 起各时段 -30min ~ +3h）内，跳过关键源等待"
    )


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
    in_window, why = wait_window(cfg, now)
    if not in_window:
        print(f"note: {why}")
        return _missing_critical(specs, report, cfg, tz)

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
                    item = normalize_raw(raw, spec, datetime.now(timezone.utc))
                    if is_catalogue_row(item.title):
                        report.catalogue_skipped = (
                            getattr(report, "catalogue_skipped", 0) + 1
                        )
                        continue
                    report.items.append(item)


def _missing_critical(
    specs: list[SourceSpec], report: CollectReport, cfg: AppConfig, tz: ZoneInfo
) -> list[str]:
    """Which critical sources currently lack a current-day edition (no waiting)."""
    results_by_id = {r.source_id: r for r in report.results}
    today = datetime.now(tz).strftime("%Y-%m-%d")
    out: list[str] = []
    for spec in specs:
        if spec.source_id not in set(cfg.run.critical_sources):
            continue
        result = results_by_id.get(spec.source_id)
        if result is None:
            out.append(spec.source_id)
            continue
        if not any(
            item.published_at is not None
            and item.published_at.astimezone(tz).strftime("%Y-%m-%d") == today
            for item in result.items
        ):
            out.append(spec.source_id)
    return out


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
    """Parse a JSONL dump, skipping any line that is not a complete record.

    **One truncated line must not cost the whole run.** Measured on 2026-10-22: a collect job
    wrote `items.jsonl` and was cut off mid-line, leaving `Invalid JSON: EOF while parsing a
    string at column 2067`. This function raised, publish failed, the workflow retried three
    times, and all three failed the same way -- so the day produced no issue at all. The bad
    line was one item out of several thousand.

    A partially written file is an ordinary outcome of an interrupted job, not a bug to
    propagate. Skipping the damaged tail loses at most the records that were never fully
    written.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[NormalizedItem] = []
    skipped = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(NormalizedItem.model_validate_json(line))
        except Exception:  # noqa: BLE001
            skipped += 1
    if skipped:
        print(f"items.jsonl: skipped {skipped} unparseable line(s)", file=sys.stderr)
    return out
