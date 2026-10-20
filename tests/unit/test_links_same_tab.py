"""Outbound links open in the current tab.

Every link on the site used `target="_blank"`, so each click opened a new tab. On a phone that
leaves a trail of tabs, and the back button stops being a way back to the digest -- which is the
one thing a reader scrolling a long issue actually wants.

`rel="noopener noreferrer"` is deliberately kept: it stops the linked page from getting a handle
on this one, which matters whether or not a new tab opens. Removing that alongside `target`
would trade one annoyance for an opening.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE_PY = ROOT / "src" / "aidaily" / "site.py"
MOTION_JS = ROOT / "site" / "assets" / "motion.js"


def test_the_templates_emit_no_blank_target() -> None:
    source = SITE_PY.read_text(encoding="utf-8")
    assert 'target="_blank"' not in source


def test_the_client_script_sets_no_blank_target() -> None:
    js = MOTION_JS.read_text(encoding="utf-8")
    assert "_blank" not in js


def test_links_keep_noopener() -> None:
    """Dropping `target` must not drop the protection that came with it."""
    source = SITE_PY.read_text(encoding="utf-8")
    assert 'rel="noopener noreferrer"' in source


@pytest.mark.parametrize("page", ["2026-10-19.html", "2026-10-20.html", "index.html"])
def test_rendered_pages_have_no_new_tab_links(page: str) -> None:
    path = ROOT / "data" / "digests" / "site" / page
    if not path.exists():
        pytest.skip(f"{page} not rendered here")
    html = path.read_text(encoding="utf-8")
    assert "target=" not in html, "a link still asks the browser for a new tab"
