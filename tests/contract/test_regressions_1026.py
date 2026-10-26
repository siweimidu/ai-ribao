"""Regression guards for the 2026-10-26 defects.

Three separate causes, all visible in one issue: 21 stories, a rail that listed 19, two feeds
that returned nothing, and five entries with no AI content.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")
HTTP = (ROOT / "src" / "aidaily" / "http.py").read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    rest = source[start:]
    match = re.search(r"(?m)^def ", rest[1:])
    return rest if match is None else rest[: match.start() + 1]


def test_the_rail_does_not_skip_non_chinese_titles() -> None:
    """The rail stopped at 19 of 21 stories because it filtered by language."""
    body = _function_body(SITE, "render_toc")
    assert "_looks_chinese(title)" not in body, (
        "render_toc must not filter by language; every story needs a rail entry"
    )


def test_the_rail_still_emits_one_row_per_event() -> None:
    body = _function_body(SITE, "render_toc")
    assert "for index, event in enumerate(events" in body
    assert "toc__no" in body


def test_the_304_retry_rebuilds_the_conditional_headers() -> None:
    """Built once outside the loop, the retry resent the same If-None-Match."""
    body = _function_body(HTTP, "get")
    loop = body.index("for attempt in range(")
    guard = body.index("if conditional and (v := self.validators.get(url))")
    assert guard > loop, "the header build must sit inside the retry loop"


def test_the_stale_validators_are_cleared_too() -> None:
    body = _function_body(HTTP, "get")
    assert 'req_headers.pop("If-None-Match", None)' in body
    assert 'req_headers.pop("If-Modified-Since", None)' in body