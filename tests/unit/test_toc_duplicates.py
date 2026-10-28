"""One story is one row, in the body and in the table of contents alike.

## What the reader saw

"点击第 13 个，跳转到的可能是第 20 个" and "文章滑到 41，目录还显示 40".

Both came from the same cause. `top_events` for the 2026-10-27 issue held **106 rows for 97
stories**, so the page emitted two `<li id="e-...">` sharing one id. Every `href="#e-..."`
resolves to the *first* match in the document, so clicking entry 32 landed on entry 3 -- and
`getElementById` used by the scroll tracker resolved to the same wrong element, which is why the
highlight lagged while scrolling.

Two independent causes produced the duplicates:

* `rank.select_diverse` pass 1 had no duplicate check at all, and passes 2 and 3 compared with
  `candidate is c` (object identity), which cannot see two RankedEvent objects for one event;
* nothing stopped a stored digest, already carrying duplicates, from being re-rendered.
"""

from __future__ import annotations

from aidaily.models import Event
from aidaily.rank import RankWeights, select_diverse


def _event(event_id: str, title: str = "OpenAI 发布新模型") -> Event:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    return Event(
        event_id=event_id,
        primary_item_id="i-" + event_id,
        title=title,
        member_item_ids=["i-" + event_id],
        source_ids=["rss:test"],
        all_urls=["https://example.invalid/" + event_id],
        first_seen_at=now,
        last_updated_at=now,
    )


def _ranked(events):
    from aidaily.rank import RankedEvent

    return [RankedEvent(event=e, score=10.0 - i * 0.1) for i, e in enumerate(events)]


def test_select_diverse_never_returns_one_event_twice() -> None:
    """Two RankedEvent objects for one event are still one story."""
    a = _event("e-aaa")
    b = _event("e-bbb")
    # The duplicate is a *different object* with the same event_id -- the case `is` missed.
    ranked = _ranked([a, a, b])
    assert ranked[0] is not ranked[1]

    chosen = select_diverse(ranked, limit=10, sources=[], rank=RankWeights())
    ids = [r.event.event_id for r in chosen]
    assert ids.count("e-aaa") == 1, ids
    assert len(ids) == len(set(ids)), ids


def test_the_render_guard_dedupes_a_stored_digest() -> None:
    """Published JSON still carries the old duplicates; rendering must not repeat them."""
    from aidaily.site import _body_order

    dup = _event("e-dup")
    other = _event("e-other", "Anthropic 开源新模型")
    shown, untranslated = _body_order([dup, other, dup], {}, {})

    ids = [e.event_id for _, e in shown] + [e.event_id for _, e in untranslated]
    assert len(ids) == len(set(ids)), ids
    # Numbering must stay contiguous: a gap looks like a missing story.
    numbers = [n for n, _ in shown]
    assert numbers == list(range(1, len(numbers) + 1)), numbers


def test_toc_highlight_uses_span_containment() -> None:
    """The highlight must ask which item *owns* the reading line.

    The old rule was "the last target whose top is above the line", i.e. `top <= line`.
    `scrollIntoView` honours `scroll-margin-top: var(--reading-line)`, so a clicked item lands
    at exactly that offset -- the very number the rule compared against. A measured
    `getBoundingClientRect().top` of 64.4 then failed `64.4 <= 64`, the clicked entry never
    qualified, and the highlight fell back to the row above: "点第 15 条跳到第 14 条".

    Geometry simulated over eight rounding offsets: the old rule missed in four of them, the
    span rule in none. These assertions keep the span form and the slop that makes it work in
    both rounding directions.
    """
    from pathlib import Path

    js = Path("site/assets/motion.js").read_text(encoding="utf-8")
    assert "READING_SLOP" in js, "the reading line needs a slop below the scroll margin"
    assert "r.bottom > line" in js, "the pick must test span containment, not top <= line"
    assert "const READING_LINE = 88;" not in js, "a hardcoded reading line came back"


def test_the_reading_line_is_one_shared_number() -> None:
    """Click offset and highlight threshold must not be two independent literals.

    They were: `scroll-margin-top: calc(var(--unit) * 6)` = 24px in CSS while the JS compared
    against a literal 88. Two unrelated numbers meant the two halves of one interaction
    disagreed, which is why the highlight lagged a full row while scrolling.
    """
    from pathlib import Path

    css = Path("site/assets/components.css").read_text(encoding="utf-8")
    tokens = Path("site/assets/tokens.css").read_text(encoding="utf-8")
    js = Path("site/assets/motion.js").read_text(encoding="utf-8")

    assert "--reading-line:" in tokens, "the shared line must be declared once, in tokens.css"
    assert "scroll-margin-top: var(--reading-line)" in css
    assert '"--reading-line"' in js, "the script must read the same custom property"