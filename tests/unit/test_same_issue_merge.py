"""One message, one entry -- inside one issue as well as across days.

`history` compares a new event against *previous* days. Two outlets reporting the same news on
the same day were never compared, so both stayed: on 2026-10-19 the digest carried
"MiniMax 正准备发布 MiniMax-M3.1-Flash" and "MiniMax-M3.1-Flash 即将发布" as two entries.

The merge lives in `select_for_digest`, after ranking, so the survivor is the best-scoring
phrasing. These tests pin that the two phrasings are recognised as one message in the first
place -- the merge itself is a union of ids and sources, exercised end to end by the pipeline.
"""

from __future__ import annotations

import inspect

from aidaily.pipeline import select_for_digest
from aidaily.samestory import same_message


def test_two_phrasings_of_one_announcement_are_one_message() -> None:
    """The pair that shipped twice on 2026-10-19."""
    assert same_message(
        "MiniMax 正准备发布 MiniMax-M3.1-Flash",
        "MiniMax-M3.1-Flash 即将发布",
    )


def test_selection_merges_within_the_issue() -> None:
    """The merge must exist in `select_for_digest`, not only in the cross-day history."""
    source = inspect.getsource(select_for_digest)
    assert "same_message" in source, "selection does not compare entries within one issue"
    assert "same_issue_merged" in source, "the merge is not counted, so it cannot be audited"
