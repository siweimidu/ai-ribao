"""Window selection: decide what "today" means before anything else looks at the data.

A feed like OpenAI News returns its entire archive in one response (1287 items spanning
years during the first real run). Deduplicating or ranking that set without a window
first would let a 2024 post into today's digest, so the window is applied *before* every
other stage.

Two rules that keep the result honest:

* An undated item is never silently treated as today. Items from window sources
  (GitHub Trending) are today's signal *by definition* and carry `today_window`. An
  undated item from an ordinary feed is genuinely unknown and is excluded -- but counted
  and sampled, so the exclusion is visible rather than invisible.
* A missing critical source is reported, not swallowed. The caller decides whether to
  wait or to publish with an explicit warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import AppConfig
from .unfiltered import is_unfiltered
from .models import NormalizedItem

#: Buckets that count as "inside the window". `unknown` is deliberately absent.
IN_WINDOW_BUCKETS = {"today", "today_window", "past_72h"}


@dataclass
class WindowResult:
    kept: list[NormalizedItem] = field(default_factory=list)
    dropped_by_bucket: dict[str, int] = field(default_factory=dict)
    #: source_ids with no item inside the window -- the freshness-gate input
    sources_with_items: set[str] = field(default_factory=set)
    undated_samples: list[str] = field(default_factory=list)
    future_dated_samples: list[str] = field(default_factory=list)
    no_url_samples: list[str] = field(default_factory=list)
    #: Items whose publication date was not the issue date. Recorded because "the issue is
    #: thin today" and "the feeds are serving last week" look identical without them.
    wrong_date_samples: list[str] = field(default_factory=list)

    def missing_critical(self, critical: list[str]) -> list[str]:
        return [s for s in critical if s not in self.sources_with_items]

    @property
    def stats(self) -> dict[str, object]:
        return {
            "items_in": len(self.kept) + sum(self.dropped_by_bucket.values()),
            "items_kept": len(self.kept),
            "dropped_by_bucket": dict(sorted(self.dropped_by_bucket.items())),
            "sources_with_items": len(self.sources_with_items),
            "undated_examples": self.undated_samples[:5],
            "future_dated_examples": self.future_dated_samples[:5],
            "no_url_examples": self.no_url_samples[:5],
        }


def select_window(
    items: list[NormalizedItem],
    cfg: AppConfig,
    now: datetime | None = None,
    *,
    include_unknown: bool = False,
    future_tolerance_hours: int = 6,
) -> WindowResult:
    """Keep only items inside the configured window.

    `include_unknown=True` keeps undated items too. It is off by default because an
    undated item has no way to prove it is new, and a daily digest that repeats the same
    undated entries forever is worse than one that names them as missing.

    Two kinds of junk are excluded here rather than at the final fact check, because a
    single bad feed must not block the whole digest:

    * **future-dated items.** Ai2's news feed dates every entry `2026-10-31` (17 days
      ahead when this was written). A digest cannot present that as today's news, and
      publishing a future date is a visible defect. A small tolerance absorbs ordinary
      timezone skew.
    * **items with no URL.** The digest's contract is that every item links to its
      source; a changelog feed with link-less entries cannot satisfy it.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg.run.window_hours)
    # The calendar day the issue covers, in Beijing time.
    issue_day = now.astimezone(timezone(timedelta(hours=8))).date()
    future_limit = now + timedelta(hours=future_tolerance_hours)
    result = WindowResult()

    def drop(bucket: str, item: NormalizedItem, samples: list[str]) -> None:
        result.dropped_by_bucket[bucket] = result.dropped_by_bucket.get(bucket, 0) + 1
        if len(samples) < 20:
            samples.append(f"{item.source_id}: {item.title[:60]}")

    for item in items:
        if not item.url:
            drop("no_url", item, result.no_url_samples)
            continue
        if item.published_at is not None and item.published_at > future_limit:
            drop("future_dated", item, result.future_dated_samples)
            continue
        # **The date must match the issue date, not merely fall inside a rolling window.**
        #
        # `window_hours: 36` was a rolling cutoff: an issue built at 12:00 on the 25th accepted
        # anything published after noon on the 24th. The instruction is 「信息源只收纳当天的
        # 信息，日期必须对得上」 -- the calendar date has to be the issue date.
        #
        # Measured on the 2026-10-25 issue with the rolling window: 129 entries, of which only
        # 22 were published that day. The page led with a 3-day-old Kimi release and two
        # 9-day-old items; the tail reached back to 2025-10-08.
        #
        # Undated items follow `include_unknown`: a source that omits the date cannot be judged
        # either way, and dropping it silently would hide the source entirely.
        if item.published_at is not None:
            published_day = item.published_at.astimezone(timezone(timedelta(hours=8))).date()
            if published_day != issue_day:
                result.dropped_by_bucket["wrong_date"] = (
                    result.dropped_by_bucket.get("wrong_date", 0) + 1
                )
                if len(result.wrong_date_samples) < 20:
                    result.wrong_date_samples.append(
                        f"{item.source_id}: {published_day} {item.title[:50]}"
                    )
                continue
        elif not include_unknown and item.age_bucket not in IN_WINDOW_BUCKETS:
            drop("unknown", item, result.undated_samples)
            continue

        result.kept.append(item)
        result.sources_with_items.add(item.source_id)

    result.kept.sort(
        key=lambda i: (i.published_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True
    )
    return result
