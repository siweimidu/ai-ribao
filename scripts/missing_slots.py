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

    if not due:
        print("第一个时段还没到，无需检查")
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
