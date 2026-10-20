"""The table of contents moves with the page, not in a box of its own.

The TOC used to be `position: sticky` with `max-height: 100vh; overflow-y: auto`. On a long
issue that put 44 entries into a 900px frame: the sidebar had its own scrollbar, so the reader
scrolled the article and the outline independently, and the visible slice of the outline never
matched the section being read.

Both halves are asserted here, because fixing one broke the other once already:

* no inner scrollbar (height is unbounded, `overflow-y: visible`);
* not pinned to the viewport (`position: relative`, so the whole box moves with the document);
* and the resize grip still anchors to the TOC rather than to the page box, which needs a
  positioned ancestor -- switching `sticky` to `static` put the grip at x=0 while the TOC
  started at x=1396.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "site" / "assets" / "components.css"


def _toc_override() -> str:
    """The last `min-width: 1400px` block that targets `.toc`, with comments stripped.

    Comments are removed before asserting: the rule explains *why* it is not `sticky` and *why*
    it is not `static`, so the words appear in the block as prose and would match a naive
    substring check.
    """
    text = CSS.read_text(encoding="utf-8")
    blocks = [
        m.group(0)
        for m in re.finditer(r"@media \(min-width: 1400px\) \{[\s\S]*?\n\}", text)
        if ".toc {" in m.group(0)
    ]
    assert blocks, "no min-width:1400px rule for .toc"
    return re.sub(r"/\*[\s\S]*?\*/", " ", blocks[-1])


def test_the_toc_keeps_an_inner_scroll() -> None:
    """44 entries do not fit in one screen, so the box scrolls -- and pages itself."""
    rule = _toc_override()
    assert "overflow-y: auto" in rule
    assert "max-height" in rule
    assert "overscroll-behavior: contain" in rule, (
        "without `contain`, the inner scroll chains into the page: one wheel gesture would",
        "move both the article and the outline",
    )


def test_the_toc_is_pinned_to_the_viewport() -> None:
    """The outline stays on screen; the paging inside it is what follows the article."""
    rule = _toc_override()
    assert "position: sticky" in rule
    assert "top:" in rule


def test_the_resize_grip_keeps_a_positioned_ancestor() -> None:
    """The grip is absolutely positioned; `static` would drop it at the page origin."""
    rule = _toc_override()
    assert "position: static" not in rule, (
        "static leaves the absolute grip without a containing block; measured at left=0"
    )
