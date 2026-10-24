"""Evidence recorded by the LLM merge must survive the later collapse pass.

Measured 2026-10-24: the run log said

    LLM 去重    7 组，合并 16 条
    · 保留 Moonshot AI Releases Kimi K3.1 Pro: A 2.8T ...

while the archive held `merged_titles: 0` and `independent_source_count: 1` for that entry.

`collapse_by_designation` runs after the LLM pass. It rebuilt `merged_titles` from only the two
titles it was joining, discarding what the earlier merge had recorded -- and only when it merged,
so a single passing event lost the key entirely.

These tests assert the passing-through case, which is what the failure looked like from the
archive: one event, no collapse triggered, evidence gone.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.rank import collapse_by_designation

NOW = datetime.now(timezone.utc)


def _event(eid: str, title: str, *, sources, merged=None) -> Event:
    return Event(
        event_id=eid,
        title=title,
        member_item_ids=[f"m-{eid}"],
        primary_item_id=f"m-{eid}",
        source_ids=list(sources),
        all_urls=[f"https://x/{eid}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
        published_range=(NOW, NOW),
        unique_facts={"merged_titles": list(merged or [])},
        independent_source_count=len(sources),
    )


def test_a_passing_event_keeps_its_merged_titles() -> None:
    """The LLM merge wrote them; nothing downstream may drop them."""
    event = _event(
        "a", "Kimi K3.1 Pro 发布", sources=("s1", "s2"),
        merged=["月之暗面发布 Kimi K3.1 Pro", "[AINews] Kimi 3.1 Pro"],
    )
    out = collapse_by_designation([event])
    assert len(out) == 1
    assert out[0].unique_facts["merged_titles"] == [
        "月之暗面发布 Kimi K3.1 Pro", "[AINews] Kimi 3.1 Pro",
    ]


def test_a_passing_event_keeps_its_source_count() -> None:
    event = _event("a", "Kimi K3.1 Pro 发布", sources=("s1", "s2", "s3"))
    out = collapse_by_designation([event])
    assert out[0].independent_source_count == 3


def test_a_passing_multi_source_event_is_labelled_multi_source() -> None:
    """`factcheck` rejects `single_source` carrying more than one independent source."""
    event = _event("a", "Kimi K3.1 Pro 发布", sources=("s1", "s2"))
    out = collapse_by_designation([event])
    assert out[0].evidence_level == "multi_source"
    assert not (
        out[0].evidence_level == "single_source" and out[0].independent_source_count > 1
    )


def test_an_unmerged_event_is_returned_unchanged() -> None:
    event = _event("a", "某条独立新闻", sources=("s1",))
    out = collapse_by_designation([event])
    assert len(out) == 1 and out[0].event_id == "a"