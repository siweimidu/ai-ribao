"""An issue must never contain the same event twice.

Measured 2026-10-29: three events appeared twice each in the published digest --

    positions (15, 82)  大客户直接打1折、模型四个月降价80%
    positions (37, 103) 扩散智能发布并开源扩散语言模型 Clover-35B-A3B-Preview
    positions (38, 104) Artificial Analysis 发布图像生视频评测基准

Same `event_id`, same title, same URL, same source. The reader sees one story twice.

`build_digest` now removes repeats by `event_id`, keeping the first (highest-ranked) one.
Selection, late merging and re-scoring all funnel through that point, so the list is
idempotent regardless of which path produced the duplicate.
"""

from __future__ import annotations

import inspect

from aidaily import pipeline


def test_build_digest_removes_repeated_event_ids() -> None:
    source = inspect.getsource(pipeline.build_digest)
    assert "if event.event_id in seen_ids:" in source
    assert "ordered = unique" in source


def test_the_dedupe_runs_before_the_headline_is_chosen() -> None:
    source = inspect.getsource(pipeline.build_digest)
    dedupe = source.index("if event.event_id in seen_ids:")
    headline = source.index("The headline comes from the top-ranked event")
    assert dedupe < headline


def test_the_dedupe_is_reported() -> None:
    """A silent fix would hide the stage that produced the duplicate."""
    source = inspect.getsource(pipeline.build_digest)
    assert "同一事件重复出现" in source