"""The rail lists what the body shows, and nothing else.

Two user reports, opposite directions:

  2026-10-26  the issue had 21 stories and the rail stopped at 19.
              Cause: the rail skipped non-Chinese titles.

  2026-10-27  the rail listed 11 untranslated entries that live in a collapsed block at the
              page bottom. Cause: the rail was built from top_events, not from the set the
              body renders. Clicking one jumped to an anchor that is not in the body.

Both are one mistake: the rail was built from a list that is not what the page shows. It is now
built from translated_ids -- exactly the body set -- so the count matches and every link
resolves.
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


def test_the_rail_is_scoped_to_the_body() -> None:
    body = _function_body("render_toc")
    assert "translated_ids" in body
    assert "if translated_ids and event.event_id not in translated_ids:" in body


def test_the_rail_does_not_filter_by_language() -> None:
    """That was the 2026-10-26 fix and it must stay."""
    body = _function_body("render_toc")
    assert "_looks_chinese(title)" not in body


def test_the_rail_numbers_only_what_it_renders() -> None:
    body = _function_body("render_toc")
    assert "shown += 1" in body


def test_the_rail_is_built_after_the_body_decides() -> None:
    """translated_ids is final only once the body loop has run."""
    day = _function_body("render_day")
    loop = day.index("for event in digest.top_events:")
    rail = day.index("toc = render_toc(")
    assert rail > loop, "the rail must be built after the body loop"


def test_the_untranslated_block_still_exists() -> None:
    """The entries are not dropped, only kept out of the rail."""
    day = _function_body("render_day")
    assert "untranslated_block" in day
    assert "本期待翻译条目" in day