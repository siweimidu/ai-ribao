"""Selection happens twice, and the two passes must agree.

`__main__` selects once to decide what to spend model calls on, then `build_digest` selects
again to produce the final order. The second pass therefore has to receive everything the first
one used, or it re-derives a different answer.

On 2026-10-19 it did not: `build_digest` was handed `rubric_scores` but not `rubric_sections`.
The section is the ranking's **primary** key, so the second pass fell back to the rule-based
classifier for every row, ordered them differently, and selected **nothing** -- the digest
published 0 events while its own counts reported 219 considered. The page was empty for the day.

## Why this reads the call tree instead of slicing the source

The first version cut the source at the first `"\n    )"` after `select_for_digest(`. That
worked only while the call had no multi-line comments: adding one meant the slice ended inside a
comment, `rubric_sections=rubric_sections` fell outside it, and the test failed while the
production code was correct. The test was measuring formatting, not behaviour.

Reading the call from the AST asks the question the test actually means: does this call pass
these keywords?
"""

from __future__ import annotations

import ast
import inspect

from aidaily.pipeline import build_digest, select_for_digest


def _select_call_in_build_digest() -> ast.Call:
    """The `select_for_digest(...)` call inside `build_digest`, as a parsed node."""
    tree = ast.parse(inspect.getsource(build_digest))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name == "select_for_digest":
            return node
    raise AssertionError("build_digest no longer calls select_for_digest at all")


def test_build_digest_forwards_both_rubric_arguments() -> None:
    """Both the scores and the sections must reach the internal selection call."""
    call = _select_call_in_build_digest()
    passed = {kw.arg for kw in call.keywords if kw.arg}
    assert "rubric_scores" in passed, (
        "build_digest re-selects without rubric_scores; model judgement is dropped"
    )
    assert "rubric_sections" in passed, (
        "build_digest re-selects without rubric_sections; the section is the primary sort key"
    )


def test_build_digest_accepts_rubric_sections() -> None:
    params = inspect.signature(build_digest).parameters
    assert "rubric_sections" in params


def test_select_for_digest_accepts_both() -> None:
    params = inspect.signature(select_for_digest).parameters
    assert "rubric_scores" in params
    assert "rubric_sections" in params