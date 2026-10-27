"""One numbered list, shared by the body, the rail and the overview.

Three reports, all the same bug:

  2026-10-26  overview opened at 03        counter advanced before the skip test
  2026-10-26  rail stopped at 19 of 21    rail filtered by language
  2026-10-27  rail ended at 99, body 106  body and rail counted different things

Every one came from a consumer running its own loop with its own counter. Numbers that appear
in one list and not another look like missing stories, which is worse than having no numbers.

`_body_order` decides once: which events the page shows, in what order, numbered. The body, the
rail and the overview all read that result.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from aidaily import site as site_module

ROOT = Path(__file__).resolve().parents[2]
SITE = (ROOT / "src" / "aidaily" / "site.py").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    start = SITE.index(f"def {name}(")
    rest = SITE[start:]
    match = re.search(r"(?m)^def ", rest[1:])
    return rest if match is None else rest[: match.start() + 1]


def test_there_is_one_ordering_function() -> None:
    assert hasattr(site_module, "_body_order")
    signature = inspect.signature(site_module._body_order)
    assert list(signature.parameters)[:3] == ["events", "insights", "items_by_id"]


def test_the_body_reads_the_shared_list() -> None:
    day = _function_body("render_day")
    assert "_body_order(digest.top_events, insights, items_by_id)" in day


def test_the_body_has_no_counter_of_its_own() -> None:
    """A second counter is how the body reached 106 while the rail stopped at 99."""
    day = _function_body("render_day")
    assert "counter += 1" not in day


def test_the_rail_reads_the_shared_list() -> None:
    body = _function_body("render_toc")
    assert "for number, event in ordered:" in body


def test_the_rail_has_no_counter_of_its_own() -> None:
    body = _function_body("render_toc")
    assert "shown += 1" not in body


def test_the_overview_reads_the_shared_list() -> None:
    body = _function_body("_render_overview")
    assert "ordered[:8]" in body


def test_the_overview_has_no_counter_of_its_own() -> None:
    body = _function_body("_render_overview")
    assert "shown += 1" not in body
    assert "enumerate(digest.top_events" not in body


def test_the_untranslated_block_is_numbered_separately() -> None:
    """It is a distinct list at the bottom of the page, so it counts from 1."""
    body = _function_body("_body_order")
    assert "untranslated.append((len(untranslated) + 1, event))" in body


def test_every_consumer_gets_the_same_type() -> None:
    """(number, event) pairs, so no consumer has to invent a number."""
    body = _function_body("_body_order")
    assert "shown.append((len(shown) + 1, event))" in body