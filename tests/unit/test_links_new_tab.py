"""Outbound links open in a new tab.

Every link on the site carries `target="_blank"`, so clicking a source opens it beside the
digest instead of replacing it. That is the requested behaviour: the reader is mid-issue, and a
Same-tab navigation throws away their place -- the back button does not restore scroll position
or the open section.

`rel="noopener noreferrer"` travels with it. A new tab without `noopener` hands the linked page
a `window.opener` reference, which is the classic reverse-tabnabbing hole; the two attributes are
one decision, not two.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE_PY = ROOT / "src" / "aidaily" / "site.py"
MOTION_JS = ROOT / "site" / "assets" / "motion.js"


def test_templates_open_links_in_a_new_tab() -> None:
    source = SITE_PY.read_text(encoding="utf-8")
    anchors = source.count('rel="noopener noreferrer"')
    blanks = source.count('target="_blank"')
    assert anchors > 0
    assert blanks == anchors, "an outbound link lost its target"


def test_the_client_script_opens_links_in_a_new_tab() -> None:
    js = MOTION_JS.read_text(encoding="utf-8")
    assert "_blank" in js


def test_noopener_travels_with_the_new_tab() -> None:
    """A new tab without `noopener` gives the linked page a handle on this one."""
    for path in (SITE_PY, MOTION_JS):
        text = path.read_text(encoding="utf-8")
        for chunk in text.split('target="_blank"')[:-1]:
            tail = text[text.index(chunk) + len(chunk):][:40]
            assert "noopener" in tail, f"{path.name}: target without noopener"


@pytest.mark.parametrize("page", ["2026-10-19.html", "2026-10-20.html", "index.html"])
def test_rendered_pages_open_links_in_a_new_tab(page: str) -> None:
    path = ROOT / "data" / "digests" / "site" / page
    if not path.exists():
        pytest.skip(f"{page} not rendered here")
    html = path.read_text(encoding="utf-8")
    assert 'target="_blank"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
