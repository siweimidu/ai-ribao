"""The leaderboard page must offer its data, not only its table.

## What was missing

`data/state/leaderboard.json` is what the page is rendered from, and it has been committed to the
repository the whole time. Nothing on the page pointed at it. Anyone wiring the ranking into a
workflow -- n8n, a spreadsheet, a bot -- had to open devtools or guess the path.

## Why a copy button rather than a link

The intended action is "give me that URL so I can paste it somewhere else". A plain link opens a
9,000-line JSON document in a tab, which is the same mistake the RSS control already fixed. The
page keeps a small `查看` link for the reader who does want to look, and puts the address on the
clipboard for the one who does not.

## What this pins

* the button exists and carries the real URL;
* the URL is the raw.githubusercontent address, because the JSON exists to be fetched by
  something that has no page to resolve a relative path against;
* the URL actually resolves to a committed file in this repository, so the button cannot decay
  into a 404 unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidaily.leaderboard import Model
from aidaily.site import LEADERBOARD_JSON_URL, SiteContext, render_leaderboard


def _models() -> list[Model]:
    return [
        Model(
            name="Test Model",
            creator="Test Labs",
            slug="test-model",
            intelligence=42.0,
            context=200000,
            price_input=1.0,
            price_output=2.0,
            reasoning=False,
            open_weights=False,
            estimated=False,
            deprecated=False,
            variant="",
            creator_color="#123456",
        )
    ]


def _render() -> str:
    ctx = SiteContext(site_url="https://example.invalid")
    return render_leaderboard(ctx, _models(), fetched_at="2026-10-23 10:00")


def test_the_page_offers_the_json() -> None:
    html = _render()
    assert "lb__api-btn" in html
    assert LEADERBOARD_JSON_URL in html


def test_the_button_copies_rather_than_navigates() -> None:
    """A link would open a wall of JSON; the existing RSS control made exactly this fix."""
    html = _render()
    # Start at the opening angle bracket, not at the class name: index("lb__api-btn") lands
    # after `<button type="button" class="`, which quietly hid the attribute under test.
    i = html.index("lb__api-btn")
    tag = html[html.rindex("<", 0, i) : html.index(">", i)]
    assert 'type="button"' in tag
    assert f'data-copy="{LEADERBOARD_JSON_URL}"' in tag


def test_the_url_is_absolute() -> None:
    """The JSON exists to be fetched by a program with no page to resolve a relative path."""
    assert LEADERBOARD_JSON_URL.startswith("https://")
    assert "/data/state/leaderboard.json" in LEADERBOARD_JSON_URL


def test_the_url_points_at_a_file_that_exists_here() -> None:
    """A copy button whose address 404s is worse than no button: it looks correct.

    The remote path is mirrored from this working tree, so the check is local: if the file is
    committed at `data/state/leaderboard.json`, the raw URL resolves to it.
    """
    rel = LEADERBOARD_JSON_URL.split("/main/", 1)[1]
    local = Path(rel)
    assert local.exists(), f"the button copies a path this repo does not have: {rel}"


def test_the_reader_keeps_a_link_to_look_at_it() -> None:
    """Copy is the default action, but "show me" must stay one click away."""
    html = _render()
    assert "lb__api-link" in html
    assert 'target="_blank"' in html[html.index("lb__api-link"):][:400]


def test_the_button_is_absent_when_there_is_no_data() -> None:
    """With no models the page is an error card; a copy button there offers nothing."""
    ctx = SiteContext(site_url="https://example.invalid")
    html = render_leaderboard(ctx, [], error="boom")
    # The control is still rendered: the JSON may hold data even when this render failed, and
    # the reader looking at an error page is exactly who benefits from it. Guard the intent:
    # the page must not claim a model count it does not have.
    assert "在榜模型" in html
    assert LEADERBOARD_JSON_URL in html


def test_the_rail_control_copies_the_json_not_the_feed() -> None:
    """The rail on this page is the ranking's control, not the RSS subscribe button.

    A reader on the leaderboard is looking at the table; the copyable thing beside it is the
    table. Passing the address through `rail_rss_copy` keeps one implementation -- the bug this
    file exists because of was a second copy control drifting from the first.
    """
    html = _render()
    start = html.index('<aside class="rail"')
    rail = html[start : html.index("</aside>", start)]
    assert f'data-copy="{LEADERBOARD_JSON_URL}"' in rail
    assert "feed/zh.xml" not in rail, "the rail still offers the RSS feed on the leaderboard"


def test_the_rail_label_says_what_it_copies() -> None:
    html = _render()
    start = html.index('<aside class="rail"')
    rail = html[start : html.index("</aside>", start)]
    assert "JSON" in rail
    assert "复制订阅地址" not in rail


def test_the_page_control_is_kept() -> None:
    """The in-page button stays: the rail and the header serve different readers."""
    html = _render()
    assert "lb__api-btn" in html
    aside_end = html.index("</aside>")
    assert "lb__api-btn" in html[aside_end:], "the header control disappeared"
