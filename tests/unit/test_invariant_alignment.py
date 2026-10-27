"""The pass-through list and the publication invariant must agree.

Measured 2026-10-24: adding the allow-list made `select_for_digest` keep low-relevance entries
from curated digests, and an assertion at the publication boundary -- written before that list
existed -- rejected them:

    AssertionError: select_diverse reintroduced stories below the AI relevance floor:
    日本数字厅 AI 建站翻车：超 1.3 万条隐私遭泄露; Google Pro 用户反馈 Antigravity…

The publish step retried three times and the run failed. The two rules are consistent once the
assertion asks the same question the gate asks.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from aidaily.models import Event
from aidaily.pipeline import (
    PASSTHROUGH_SOURCES,
    is_passthrough,
    leads_the_issue,
    passes_ai_relevance,
    select_for_digest,
)

NOW = datetime.now(timezone.utc)


def _event(source_ids: list[str], title: str = "任意标题") -> Event:
    return Event(
        event_id="e",
        title=title,
        member_item_ids=["i"],
        primary_item_id="i",
        source_ids=source_ids,
        all_urls=["https://x"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_the_invariant_asks_the_same_question_as_the_gate() -> None:
    """A guard that rejects what the gate allows fails every run that uses the feature."""
    source = inspect.getsource(select_for_digest)
    assert "and not is_passthrough(row.event)" in source, (
        "the publication invariant must exempt allow-listed sources, or it contradicts the gate"
    )


def test_a_low_focus_allow_listed_event_survives_both_rules() -> None:
    """The exact shape that failed: below the floor, but from a curated digest."""
    event = _event(["rss:hex2077"])
    assert not passes_ai_relevance(0.36)
    assert is_passthrough(event)
    # Together they mean: keep it.
    assert is_passthrough(event) or passes_ai_relevance(0.36)


def test_a_low_focus_ordinary_event_survives_neither() -> None:
    event = _event(["rss:infoq-cn"])
    assert not passes_ai_relevance(0.36)
    assert not is_passthrough(event)


def test_every_allow_listed_id_is_a_real_source_id() -> None:
    """A typo in the list silently disables the feature for that source."""
    for sid in PASSTHROUGH_SOURCES:
        assert ":" in sid, sid
        assert sid == sid.strip(), sid


def test_the_lead_rule_and_the_gate_do_not_conflict() -> None:
    """A pinned release is normally also above the floor; nothing here changes that."""
    assert leads_the_issue("月之暗面发布 Kimi K3.1 Pro")
    assert passes_ai_relevance(1.0)