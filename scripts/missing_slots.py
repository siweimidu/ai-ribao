#!/usr/bin/env python3
"""Which collection slots should have published by now, and have not.

## The question this answers

The old watchdog asked two things: "does today have a digest?" and "was the last scheduled run a
failure?". Both miss the failure that actually happens, because GitHub does not run crons on time.
Measured over eight scheduled triggers on 2026-10-20/21:

    daily.yml wanted UTC 20:00 / 04:00 / 12:00
    observed        23:10   17:15 / 16:12   22:50, and one slot produced no run at all

A drift of two to four hours. At 23:50 the last run was the 23:10 *success*, so "was the last run
a failure?" answered no -- while the 12:00 Beijing slot had silently never happened. Meanwhile
juya had published 14 stories at 01:28 UTC that never reached the issue.

So this script does not reason about triggers. It reasons about *slots*: for the current Beijing
time, which slots are already due, and did the ledger record a publish for each of them?

A slot gets one hour of grace before it counts as missing, because the collection itself takes
20-35 minutes when it waits for critical sources.

## Output

Writes `retry` and `reason` to `$GITHUB_OUTPUT`. Exit code is always 0: this is a check, and a
check that cannot decide must not paint the workflow red.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "state" / "runs.jsonl"
ARCHIVE = ROOT / "data" / "digests"

#: Beijing hours at which a slot’s digest should exist. One hour after the collection hour in
#: `config/daily.yaml` (04:00 / 12:00 / 20:00), which is enough for the wait-for-sources step.
#: Beijing hours at which a slot's digest should exist. The collection runs at 04:00 / 12:00 / 20:00
#: and waits up to 20 minutes for critical sources, so one hour of grace is the point at which
#: "it did not run" is a better explanation than "it is still running".
SLOT_DEADLINES = (5, 13, 21)

#: Pages that must exist in the built site. A digest that published but lost a page is still a
#: broken site: the rail links every one of these, and a missing file turns a navigation item
#: into a 404 nobody notices until a reader clicks it.
#:
#: `leaderboard.html` is listed for a second reason: it is the only page whose content comes from
#: an outside service. When artificialanalysis.ai is unreachable the page still renders -- with an
#: explanation instead of a table -- so a *missing* file means the build step itself did not run,
#: which is a different failure from a failed fetch.
REQUIRED_PAGES = ("index.html", "tibo.html", "sources.html", "leaderboard.html")

#: A page smaller than this is not a page. The real ones are 100-200 KB; an error stub or a
#: half-written file is a few hundred bytes.
MIN_PAGE_BYTES = 8_000


def page_problems(site_dir: Path) -> list[str]:
    """Which required pages are missing or too small to be real."""
    problems: list[str] = []
    for name in REQUIRED_PAGES:
        path = site_dir / name
        if not path.exists():
            problems.append(f"{name} 不存在")
            continue
        size = path.stat().st_size
        if size < MIN_PAGE_BYTES:
            problems.append(f"{name} 只有 {size} 字节")
    return problems


def leaderboard_problem(site_dir: Path, *, max_age_hours: float = 36.0) -> str | None:
    """Why the leaderboard looks stale, or None when it looks current.

    The page embeds its fetch date. A date older than `max_age_hours` means the leaderboard
    stopped refreshing while the rest of the build kept working -- the kind of silent
    degradation a "did it publish?" check cannot see.
    """
    path = site_dir / "leaderboard.html"
    if not path.exists():
        return None  # page_problems already reports this
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    match = re.search(r"抓取于 (\d{4}-\d{2}-\d{2})", html)
    if not match:
        return "模型榜没有抓取日期"
    try:
        fetched = datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError:
        return f"模型榜抓取日期无法解析: {match.group(1)}"
    age_hours = (beijing_now() - fetched).total_seconds() / 3600
    if age_hours > max_age_hours:
        return f"模型榜数据已是 {age_hours / 24:.1f} 天前"
    return None


def beijing_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def published_dates() -> dict[str, list[str]]:
    """date -> list of publish timestamps (UTC ISO) recorded in the ledger."""
    out: dict[str, list[str]] = {}
    if not LEDGER.exists():
        return out
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("status") != "published":
            continue
        date = str(row.get("date") or "")
        if not date:
            continue
        out.setdefault(date, []).append(str(row.get("at") or ""))
    for stamps in out.values():
        stamps.sort()
    return out


def slots_due(now: datetime) -> list[int]:
    """The slot deadlines that have passed today, Beijing time."""
    return [h for h in SLOT_DEADLINES if now.hour >= h]


def main() -> int:
    now = beijing_now()
    today = now.strftime("%Y-%m-%d")
    due = slots_due(now)

    print(f"北京时间 {now:%Y-%m-%d %H:%M}，今天应已完成 {len(due)} 个时段：{due}")

    # **Page completeness is checked even before the first slot.** A build that published nothing
    # yet still left a broken site is worth reporting, and the rail links these pages from every
    # issue -- a missing one is a 404 behind a navigation item.
    site_dir = ARCHIVE / "site"
    problems = page_problems(site_dir)
    if problems:
        _output("true", f"站点缺页面：{'；'.join(problems)}")
        return 0

    stale = leaderboard_problem(site_dir)
    if stale:
        _output("true", f"{stale} —— 重新构建会刷新模型榜")
        return 0

    if not due:
        print("第一个时段还没到，页面完整，无需检查时段")
        return 0

    # The artifact is the thing itself: a ledger row saying "published" for a date whose archive
    # is missing is not a publication. Same rule the CLI gate applies.
    archive = ARCHIVE / f"{today}.json"
    if not archive.exists():
        _output("true", f"{today} 应有 {len(due)} 个时段，但归档 {archive.name} 不存在")
        return 0

    try:
        events = len(json.loads(archive.read_text(encoding="utf-8"))["digest"]["top_events"])
    except Exception:
        events = 0

    if events == 0:
        _output("true", f"{today} 的归档存在但 0 条事件")
        return 0

    # Which slot does each publish belong to? The one whose *collection hour* it follows.
    #
    # Collection hours are 04:00 / 12:00 / 20:00 Beijing and the deadlines are one hour later, so
    # a publish at 07:10 belongs to the 04:00 slot, not to the next one. The first version
    # compared against the deadline instead and put the 07:10 publish in the 13:00 bucket, which
    # then reported the 05:00 slot as missing every afternoon.
    collection_hours = (4, 12, 20)
    done: set[int] = set()
    for at in published_dates().get(today, []):
        try:
            hour_cn = (int(at[11:13]) + 8) % 24
        except (ValueError, IndexError):
            continue
        owner = None
        for hour, deadline in zip(collection_hours, SLOT_DEADLINES):
            if hour <= hour_cn < hour + 8:
                owner = deadline
                break
        if owner is None:
            # Published before 04:00 or after 20:00: attribute to the nearest slot that is due.
            owner = SLOT_DEADLINES[0] if hour_cn < 4 else SLOT_DEADLINES[-1]
        done.add(owner)

    missing = [d for d in due if d not in done]
    print(f"账本记录今天已发布 {len(done)} 个时段 {sorted(done)}，缺 {missing}")

    if missing:
        _output(
            "true",
            f"{today} 应完成 {len(due)} 个时段（{due}），账本只有 {sorted(done)}；"
            f"缺 {missing}，已归档 {events} 条 —— 重新触发采集",
        )
    else:
        print("所有应完成的时段都已发布，无需重试")
    return 0


def _output(retry: str, reason: str) -> None:
    print(f"retry={retry}")
    print(f"reason={reason}")
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"retry={retry}\n")
            fh.write(f"reason={reason}\n")


if __name__ == "__main__":
    sys.exit(main())
