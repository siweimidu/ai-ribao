"""Route a story to the date it was **published**, not the date it was collected.

## The rule this implements

A story that surfaces on the 18th but carries a publication timestamp of the 17th belongs in the
17th's issue, slotted by importance and heat like everything else. DeepSeek V4.1 Flash 1017 is the
case that forced this: it is a 10-17 release, the digest that day closed at 14:38 Beijing, and the
story arrived afterwards. Leaving it out means the archive is wrong about what happened on the 17th.

## Why this is not simply "widen the window"

Widening the window would mix two days into one document: today's issue would contain yesterday's
stories, and the 17th would never gain them. The dates would still be wrong, just differently.

So the cut stays at publication time, and a story whose publication date is **earlier than the
issue being built** is routed to its own date instead of being dropped. The two operations are
separate:

* `split_by_date` -- what belongs to the target date, and what belongs to an earlier one;
* `DateSplit.late` -- the per-date payload handed to the issue builder.

Items without a parseable publication time are never back-dated. A missing date is not evidence of
an old date, and inventing one would corrupt the archive more than leaving it in today's issue.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import NormalizedItem

#: How far back a late story may be filed. Beyond this the archive for that day has usually been
#: read, linked and fed downstream; silently rewriting a months-old issue is not a correction,
#: it is a rewrite. Six days covers the realistic delay (a weekly roundup, a weekend gap).
MAX_BACKFILL_DAYS = 6


def local_date(when: datetime, tz_offset_hours: int = 8) -> str:
    """The Beijing calendar date of an instant."""
    return when.astimezone(timezone(timedelta(hours=tz_offset_hours))).strftime("%Y-%m-%d")


@dataclass
class DateSplit:
    """Items partitioned by the date they belong to."""

    target: list[NormalizedItem] = field(default_factory=list)
    #: date -> items published on that date but not yet in its issue
    late: dict[str, list[NormalizedItem]] = field(default_factory=dict)
    #: Published after the target date, or older than MAX_BACKFILL_DAYS
    ignored: int = 0

    @property
    def late_total(self) -> int:
        return sum(len(v) for v in self.late.values())

    def summary(self) -> dict[str, object]:
        return {
            "target": len(self.target),
            "late_by_date": {d: len(v) for d, v in sorted(self.late.items())},
            "late_total": self.late_total,
            "ignored": self.ignored,
        }


def split_by_date(
    items: list[NormalizedItem],
    target_date: str,
    *,
    tz_offset_hours: int = 8,
    min_date: str | None = None,
) -> DateSplit:
    """Partition `items` into the target date and earlier dates that still need them.

    `min_date` bounds how far back routing may go; it defaults to `MAX_BACKFILL_DAYS` before the
    target. An item published **after** the target date is left out entirely -- that is
    tomorrow's news, and filing it into today would be the mirror image of the bug fixed here.
    """
    if min_date is None:
        base = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        min_date = (base - timedelta(days=MAX_BACKFILL_DAYS)).strftime("%Y-%m-%d")

    split = DateSplit()
    late: dict[str, list[NormalizedItem]] = defaultdict(list)

    for item in items:
        if item.published_at is None:
            # Undated: keep it with the target. Back-dating an unknown is worse than a little
            # noise in today's issue.
            split.target.append(item)
            continue
        day = local_date(item.published_at, tz_offset_hours)
        if day == target_date:
            split.target.append(item)
        elif day < target_date:
            if day >= min_date:
                late[day].append(item)
            else:
                split.ignored += 1
        else:
            split.ignored += 1

    split.late = {
        day: sorted(
            group,
            key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        for day, group in late.items()
    }
    return split
