"""The calendar must show the reader's today, not the build's today.

A static page carries whatever date it was built with. On 2026-10-20 the site still circled the
19th: the page had been built the previous evening and `today` was baked in. The reader saw the
wrong day marked, and the legend said "today" about a day that had already passed.

Two independent causes, both fixed:

* the value came from the build machine's timezone (UTC on a GitHub runner), eight hours behind
  Beijing -- a build after 16:00 UTC produced the previous day even before the page aged;
* the calendar read that value instead of computing the date in the browser.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from aidaily.site import _site_today

ROOT = Path(__file__).resolve().parents[2]


def test_today_is_a_beijing_date() -> None:
    """The digest dates are Beijing dates, so "today" must be one too."""
    assert _site_today() == datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def test_today_does_not_use_the_build_machine_zone() -> None:
    """A UTC build after 16:00 must not report the previous day.

    `datetime.now(timezone.utc).astimezone()` resolves against the *runner's* zone. On
    GitHub that is UTC, so between 16:00 and 24:00 UTC the date it produced was one day behind
    Beijing -- and the page then stayed wrong until the next build.
    """
    source = inspect.getsource(sys_module())
    assert "astimezone().date()" not in source, (
        "the site still derives its date from the build machine's timezone"
    )


def sys_module():
    import aidaily.site as site

    return site


def test_the_calendar_computes_today_in_the_browser() -> None:
    """A static page must not rely on a build time for "today".

    The page holds two calendars; the newer one already used `new Date()`, and the older one
    did not -- so they disagreed on the same page.
    """
    js = (ROOT / "site" / "assets" / "motion.js").read_text(encoding="utf-8")
    assert "const nowLocal = new Date();" in js
    # The old calendar must no longer read the baked value.
    assert "const today = data.today;" not in js


@pytest.mark.parametrize("page", ["index.html", "2026-10-19.html"])
def test_rendered_pages_carry_a_beijing_today(page: str) -> None:
    """Regression guard on the artefact itself, when one is present."""
    import json
    import re

    path = ROOT / "data" / "digests" / "site" / page
    if not path.exists():
        pytest.skip(f"{page} not rendered here")
    html = path.read_text(encoding="utf-8")
    match = re.search(r'id="calendar-data">(.*?)</script>', html, re.S)
    assert match, "the page no longer inlines calendar data"
    data = json.loads(match.group(1))
    # The page bakes the date it was rendered on. Asserting it equals *today* made this test
    # fail every midnight: artefacts are produced by a workflow, so between the last render and
    # the next one the two genuinely differ. What matters is that the value is a real date and
    # that the calendar lists it -- a page with a missing or malformed today is the actual bug.
    today = data.get("today") or ""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today), today
    assert today in (data.get("dates") or []), (today, data.get("dates"))
