"""Every row on the sources page is a doorway to the source itself.

`sources.html` lists 138 registered sources. The URL was previously plain text in 10px muted
grey, so finding a feed meant selecting and copying it. The row is now the link.

Two details matter and both are asserted here: it opens in a **new tab** (the reader is browsing
a digest, and losing their place to check a feed is a bad trade), and a source with no http URL
stays a plain row rather than rendering a dead link.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import Digest
from aidaily.site import SiteContext, render_sources


def _digest() -> Digest:
    return Digest(
        date="2026-10-19",
        kind="brief",
        generated_at=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc),
        window_start=datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc),
        source_coverage={},
        counts={"events": 1},
    )


def _render(sources) -> str:
    ctx = SiteContext(
        site_url="https://example.com",
        archive=[("2026-10-19", 1)],
        generated_at=None,
    )
    return render_sources(ctx, sources, _digest())


def _source(url: str, name: str = "Example") -> dict:
    return {
        "source_id": "rss:example",
        "name": name,
        "url": url,
        "category": "lab-official",
        "language": "en",
        "source_type": "rss",
        "enabled": True,
        "priority": 1,
    }


def test_a_source_row_is_a_link() -> None:
    html = _render([_source("https://example.com/feed.xml")])
    assert '<a class="source-row" href="https://example.com/feed.xml"' in html


def test_it_opens_in_a_new_tab() -> None:
    """The reader asked for this: visiting a source must not replace the digest.

    `rel="noopener"` travels with it -- a new tab without it hands the linked page a
    `window.opener` handle on this one.
    """
    html = _render([_source("https://example.com/feed.xml")])
    assert 'target="_blank"' in html
    assert "noopener" in html


def test_a_source_without_an_http_url_is_not_a_link() -> None:
    """An `external` push source has no page to visit; a dead link is worse than a plain row."""
    html = _render([_source("push:internal", name="Internal push")])
    assert '<div class="source-row">' in html
    assert '<a class="source-row"' not in html


def test_the_url_is_still_visible_as_text() -> None:
    """The feed address is useful to copy even when the row is clickable."""
    html = _render([_source("https://example.com/feed.xml")])
    assert '<div class="source-row__url">https://example.com/feed.xml</div>' in html
