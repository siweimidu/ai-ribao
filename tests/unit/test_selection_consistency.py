"""Selection happens twice, and the two passes must agree.

`__main__` selects once to decide what to spend model calls on, then `build_digest` selects
again to produce the final order. The second pass therefore has to receive everything the first
one used, or it re-derives a different answer.

On 2026-10-19 it did not: `build_digest` was handed `rubric_scores` but not `rubric_sections`.
The section is the ranking's **primary** key, so the second pass fell back to the rule-based
classifier for every row, ordered them differently, and selected **nothing** -- the digest
published 0 events while its own counts reported 219 considered. The page was empty for the day.
"""

from __future__ import annotations

import inspect

from aidaily.pipeline import build_digest, select_for_digest


def test_build_digest_forwards_both_rubric_arguments() -> None:
    """Both the scores and the sections must reach the internal selection call."""
    source = inspect.getsource(build_digest)
    call = source[source.index("select_for_digest("):]
    call = call[:call.index("\n    )")]
    assert "rubric_scores=rubric_scores" in call
    assert "rubric_sections=rubric_sections" in call, (
        "build_digest re-selects without rubric_sections; the section is the primary sort key"
    )


def test_build_digest_accepts_rubric_sections() -> None:
    params = inspect.signature(build_digest).parameters
    assert "rubric_sections" in params


def test_select_for_digest_accepts_both() -> None:
    params = inspect.signature(select_for_digest).parameters
    assert "rubric_scores" in params
    assert "rubric_sections" in params
