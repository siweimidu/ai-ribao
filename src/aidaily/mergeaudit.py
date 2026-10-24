"""Pre-publication check: does any published entry merge stories that are not one story?

## The failure this catches

Measured 2026-10-23. One entry in the issue was headlined "企业 AI 越用越复杂，如何用一个
Gateway 管好模型、Agent 和成本？" and listed twelve InfoQ links. Its facts named Qwen kernel
work, a DeepSeek funding round and a Huawei assistant review -- three unrelated stories. The
link the reader clicked was one of the twelve, so it went to an article the entry never
described.

The cause was `content_sha256`: every InfoQ RSS entry carries the same six-character template
body, so twelve different articles hashed identically and were merged as one record. Two fixes
landed in `ingest.py` (a length floor and a boilerplate test). This module is the guard that
notices when a third shape of the same problem appears.

## What it checks

After selection, for every published event: count how many *distinct headlines* its member
items carry. One story reported by several outlets has near-identical headlines, so a high
count is not by itself wrong. What is wrong is many distinct headlines **whose entities do not
overlap** -- that is several stories wearing one entry.

## Why not just re-check the hash

The hash is what broke. Checking the hash again would confirm the same wrong answer. This looks
at the outcome instead: the headlines that ended up in one event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .entities import extract_entities
from .models import Digest, Event

#: Above this many distinct headlines inside one event, the entry is worth looking at.
#:
#: Three is normal: a launch reported by four outlets arrives with four headlines that differ by
#: an adverb. The InfoQ failure had twelve.
HEADLINE_ALERT = 4

#: When this share of an event member headlines share no entity with the event title, the
#: members are about something else.
#:
#: Measured on the broken 10-23 entry: 11 of 12 members shared nothing with the title.
FOREIGN_SHARE_ALERT = 0.5


@dataclass
class Suspicion:
    event_id: str
    title: str
    members: int
    distinct_headlines: int
    foreign: int
    reasons: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.foreign / self.members if self.members else 0.0


def _entities(text: str) -> set[str]:
    try:
        return {e.lower() for e in extract_entities(text)}
    except Exception:
        return set()


def inspect(events, headlines: dict[str, list[str]]) -> list[Suspicion]:
    """Events whose members do not look like one story.

    `events` is any iterable of events; only `event_id`, `title` and `member_item_ids` are read.
    `headlines` maps `event_id` to the member titles, which the caller has and this module does
    not: an `Event` keeps member *ids*, and the titles live on the items.
    """
    out: list[Suspicion] = []
    for event in events:
        titles = [t for t in (headlines.get(event.event_id) or []) if t and t.strip()]
        if len(titles) < 2:
            continue

        distinct = {t.strip() for t in titles}
        title_entities = _entities(event.title)

        foreign = 0
        for title in distinct:
            if title.strip() == event.title.strip():
                continue
            if not (_entities(title) & title_entities):
                foreign += 1

        reasons: list[str] = []
        if len(distinct) >= HEADLINE_ALERT:
            reasons.append(f"{len(distinct)} 个不同标题")
        share = foreign / len(distinct) if distinct else 0.0
        if share >= FOREIGN_SHARE_ALERT:
            reasons.append(f"{foreign}/{len(distinct)} 个标题与事件标题无共同实体")

        if reasons:
            out.append(
                Suspicion(
                    event_id=event.event_id,
                    title=event.title,
                    members=len(titles),
                    distinct_headlines=len(distinct),
                    foreign=foreign,
                    reasons=reasons,
                )
            )
    return out


def report(suspicions: list[Suspicion]) -> dict:
    """The JSON that goes into the digest report.

    Always present, even when empty: a missing key would read as "not checked", and the point of
    the guard is that it is always checked.
    """
    return {
        "checked": True,
        "suspicious_events": len(suspicions),
        "examples": [
            {
                "title": s.title[:100],
                "members": s.members,
                "distinct_headlines": s.distinct_headlines,
                "foreign": s.foreign,
                "reasons": s.reasons,
            }
            for s in suspicions[:5]
        ],
    }
