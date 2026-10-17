"""Fold late stories into an already-published digest and re-rank it.

## What this is for

A story published on the 17th but first seen on the 18th belongs in the 17th's issue, positioned by
importance. DeepSeek V4.1 Flash 1017 is the case: a 10-17 release, and the 10-17 issue closed at
14:38 Beijing before the story broke.

## Why this does not re-score the existing events

`score_event` reads each event's `member_item_ids` to compute substance, engagement and freshness.
The archive stores events and insights but **not** the NormalizedItem bodies those ids point at, so
a naive re-rank finds no items for the archived events and scores them at zero. Measured: after the
first working merge, DeepSeek V4.1 Flash sat at position 9 (and again at 15 and 60) while unrelated
entries with intact items rose above it -- the ranking had been inverted by missing input, not by
real importance.

So the archived events keep the `rank_score` recorded when they were first ranked, and only the late
stories are scored now. Merging the two score sets orders the whole issue by importance without
inventing input that no longer exists.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from difflib import SequenceMatcher

from .analyze import EventInsight
from .dedup import titles_are_the_same_story
from .history import fingerprint
from .models import Digest, Event, NormalizedItem
from .rank import rank_events


def _event_from_items(
    group: list[NormalizedItem], digest_date: str, now: datetime, cfg
) -> Event:
    # A late story often has no second source when it is filed, so requiring corroboration would
    # discard exactly the stories this exists to save. Members are kept whole, so the evidence
    # badge reflects what was actually in hand.
    #
    # The timestamps are first_seen_at/last_updated_at because that is the pair Event declares;
    # writing first_published_at/last_published_at raised pydantic "field required" on every merge.
    lead = group[0]
    event_id = "late-" + hashlib.sha1(
        f"{digest_date}|{lead.item_id}".encode("utf-8")
    ).hexdigest()[:16]
    published = [i.published_at for i in group if i.published_at]
    first = min(published) if published else now
    last = max(published) if published else now
    source_ids: list[str] = []
    for member in group:
        if member.source_id not in source_ids:
            source_ids.append(member.source_id)
    urls: list[str] = []
    for member in group:
        if member.url and member.url not in urls:
            urls.append(member.url)
    return Event(
        event_id=event_id,
        title=lead.title,
        member_item_ids=[i.item_id for i in group],
        primary_item_id=lead.item_id,
        source_ids=source_ids,
        all_urls=urls,
        independent_source_count=len(source_ids),
        first_seen_at=first,
        last_updated_at=last,
        published_range=(first, last),
    )


def _model_tokens(text: str) -> set[str]:
    '''Distinctive product/version tokens in a headline.

    `V4.1-Flash-1017`, `GPT-6`, `Seedream 5` -- the part that names *which* thing a story is about.
    Extracted with the project's own entity rules so this agrees with the rest of the pipeline
    instead of growing a second, subtly different pattern.
    '''
    from .entities import extract_entities

    tokens = {t.lower() for t in extract_entities(text)}
    # Keep only tokens carrying a digit or a hyphen: a bare product word ("DeepSeek") says which
    # company, not which release, and merging on it would fold every DeepSeek story of the day.
    return {t for t in tokens if any(ch.isdigit() for ch in t) or "-" in t}


def _same_story(left, right) -> bool:
    '''Whether two late items report one release.

    `titles_are_the_same_story` is deliberately strict: it merges only headlines that differ by
    announcement filler, because loosening it lets "same subject, different fact" collide. That is
    right for the daily pipeline and too strict here -- on the 10-17 backfill, seven entries for
    DeepSeek V4.1 Flash survived, each with an extra clause, and the issue showed one release seven
    times.

    Three signals, in increasing looseness:

    1. identical body text (the same article syndicated to two outlets);
    2. a shared version token -- both headlines name `V4.1-Flash-1017`, so they are the same
       release whatever else each adds;
    3. near-identical title text.

    Signal 2 is what does the work on Chinese tech headlines, and it cannot over-merge: two stories
    about different releases do not share a version string.
    '''
    from .dedup import titles_are_the_same_story

    if titles_are_the_same_story(left.title, right.title):
        return True
    if left.content_sha256 and left.content_sha256 == right.content_sha256:
        return True

    shared = _model_tokens(left.title) & _model_tokens(right.title)
    if shared:
        return True

    def body(item):
        return (item.content_text or item.summary or "")[:4000]

    lt, lb = body(left), body(right)
    if len(lt) >= 200 and len(lb) >= 200:
        if SequenceMatcher(None, lt, lb).quick_ratio() > 0.90:
            return True
    return SequenceMatcher(None, left.title, right.title).ratio() >= 0.88


def merge_late_items(
    digest: Digest,
    late_items: list[NormalizedItem],
    *,
    sources,
    cfg,
    insights: dict[str, EventInsight] | None = None,
    now: datetime | None = None,
) -> tuple[Digest, dict[str, EventInsight], dict[str, object]]:
    """Return a digest with `late_items` folded in and ordered by importance.

    Events the late items duplicate are skipped: the same release covered by a second outlet is a
    corroboration of an existing event, not a new one.
    """
    now = now or datetime.now(timezone.utc)
    insights = dict(insights or {})
    report: dict[str, object] = {
        "late_candidates": len(late_items),
        "added": 0,
        "duplicate": 0,
        "dropped_no_url": 0,
        "clustered": 0,
    }

    existing_urls = {u for e in digest.top_events for u in (e.all_urls or [])}
    existing_marks: list[set[str]] = [fingerprint(e) for e in digest.top_events]

    # Cluster the late items among themselves **before** making events. One story arrives from
    # several outlets within the same hour, and one event per article put the same release at
    # positions 1, 2 and 60 -- the same news three times, which is worse than the omission this
    # feature exists to fix.
    groups: list[list[NormalizedItem]] = []
    for item in late_items:
        if not item.url:
            report["dropped_no_url"] = int(report["dropped_no_url"]) + 1
            continue
        if item.url in existing_urls:
            report["duplicate"] = int(report["duplicate"]) + 1
            continue
        for group in groups:
            if any(_same_story(member, item) for member in group):
                group.append(item)
                break
        else:
            groups.append([item])

    new_events: list[Event] = []
    for group in groups:
        group.sort(
            key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        event = _event_from_items(group, digest.date, now, cfg)
        mark = fingerprint(event)
        if any(mark and mark & other for other in existing_marks):
            report["duplicate"] = int(report["duplicate"]) + 1
            continue
        for member in group:
            existing_urls.add(member.url)
        existing_marks.append(mark)
        new_events.append(event)
        if len(group) > 1:
            report["clustered"] = int(report["clustered"]) + 1

    report["added"] = len(new_events)
    if not new_events:
        return digest, insights, report

    # Only the late events are scored: the archived ones have no NormalizedItem bodies left, and
    # re-scoring them would rank them at zero. Their recorded score is the honest ordering.
    scored = rank_events(new_events, late_items, sources, now=now)
    late_by_id = {r.event.event_id: r.score for r in scored}
    for event in new_events:
        event.rank_score = late_by_id.get(event.event_id, 0.0)

    combined = list(digest.top_events) + new_events
    combined.sort(key=lambda e: (-(e.rank_score or 0.0), e.event_id))

    limit = int(getattr(cfg.output.deep, "max_items", 0) or len(combined))
    kept = combined[:limit]

    merged = digest.model_copy(deep=True)
    merged.top_events = kept
    merged.sections = _rebuild_sections(kept, digest)
    merged.counts = dict(merged.counts or {})
    merged.counts["events"] = len(kept)
    merged.counts["late_added"] = len(new_events)
    return merged, insights, report


def _rebuild_sections(events: list[Event], original: Digest) -> dict[str, list[Event]]:
    """Keep each event in the section it was already in; new ones fall back to "other".

    Section assignment is by the primary item's source category, which is not recoverable from the
    archive alone, so an existing event keeps its recorded section and a new one goes to the
    catch-all rather than being guessed into a wrong one.
    """
    section_of: dict[str, str] = {}
    for category, section_events in (original.sections or {}).items():
        for event in section_events:
            section_of[event.event_id] = category
    out: dict[str, list[Event]] = {}
    for event in events:
        out.setdefault(section_of.get(event.event_id, "other"), []).append(event)
    return out
