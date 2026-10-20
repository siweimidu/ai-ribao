"""Another outlet's digest is filtered regardless of whether history is available.

The filter used to live inside `if history is not None:`, so any call without a history object
skipped it entirely. The candidate-pool pass also returns before that block. The result: on
2026-10-19 the digest carried both

  "AIHOT 周报 · 2026-W42 — Google 发布 Gemini 4 Argon…"
  "AIHOT 日报 · 2026-10-19 — Anthropic 内部研究显示…"

as stories, while `is_roundup` classified both correctly. The rule was right; the call site was
unreachable for them.
"""

from __future__ import annotations

import inspect

from aidaily.designation import is_roundup
from aidaily.pipeline import select_for_digest


def test_a_weekly_and_a_daily_digest_are_roundups() -> None:
    assert is_roundup("AIHOT 周报 · 2026-W42 — Google 发布 Gemini 4 Argon：面向复杂工程与科研任务的前沿模型")
    assert is_roundup("AIHOT 日报 · 2026-10-19 — Anthropic 内部研究显示初级技术岗位占比下降")
    assert not is_roundup("MiniMax 正准备发布 MiniMax-M3.1-Flash")


def test_the_roundup_filter_does_not_depend_on_history() -> None:
    """It must run before the `history is not None` guard, not inside it."""
    source = inspect.getsource(select_for_digest)
    lines = source.splitlines()

    filter_line = next(i for i, ln in enumerate(lines) if "is_roundup(r.event.title)" in ln)
    guard_line = next(i for i, ln in enumerate(lines) if ln.strip() == "if history is not None:")

    assert filter_line < guard_line, (
        "the roundup filter sits inside the history guard; a call without history skips it",
    )


def test_the_roundup_filter_precedes_the_pool_return() -> None:
    """`pool_only` returns early, so the filter has to come before it."""
    source = inspect.getsource(select_for_digest)
    lines = source.splitlines()

    filter_line = next(i for i, ln in enumerate(lines) if "is_roundup(r.event.title)" in ln)
    pool_line = next(i for i, ln in enumerate(lines) if "if pool_only is not None:" in ln)

    assert filter_line < pool_line, (
        "pool_only returns before the roundup filter runs, so roundups leak into the pool",
    )
