"""The rail lists what the body shows, and nothing else.

Two user reports, opposite directions:

  2026-10-26  the issue had 21 stories and the rail stopped at 19.
              Cause: the rail skipped non-Chinese titles.

  2026-10-27  the rail ended at 99 while the body numbered up to 106.
              Cause: each ran its own loop with its own counter.

Both are one mistake. The rail no longer runs a loop at all -- it reads `_body_order`, the same
numbered list the body renders, so the counts match by construction. `test_numbering.py` pins
that shared source; this file pins the two properties that must survive it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    start = SITE.index(f"def {name}(")
    rest = SITE[start:]
    match = re.search(r"(?m)^def ", rest[1:])
    return rest if match is None else rest[: match.start() + 1]


def test_the_rail_does_not_filter_by_language() -> None:
    """That was the 2026-10-26 fix and it must stay."""
    body = _function_body("render_toc")
    assert "_looks_chinese(title)" not in body


def test_the_rail_renders_one_row_per_ordered_event() -> None:
    body = _function_body("render_toc")
    assert "for number, event in ordered:" in body
    assert "toc__no" in body


def test_the_untranslated_block_still_exists() -> None:
    """The entries are not dropped, only kept out of the rail."""
    day = _function_body("render_day")
    assert "untranslated_block" in day
    assert "本期待翻译条目" in day