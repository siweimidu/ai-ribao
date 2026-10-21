"""Choosing a picture: why the first image on a page is usually the wrong one.

Measured across live pages on 2026-10-21:

    cloud.google.com   og:image = AI_infrastructure_default.max-300x300.jpg
                       -- a 300px topic tile, byte-identical for every post in that category
    aws.amazon.com     twenty marketing banners before the article picture
    aihot.news         og:image = /og/items/<id>.png -- its own branded card with a score badge

So the URL cannot decide. The pixels have to, and the aggregator own card has to be refused.
"""

from __future__ import annotations

import pytest

from aidaily.media import (
    _JUNK_IMAGE,
    find_image_candidates,
    placeholder,
    score_image,
)


# --- scoring ---------------------------------------------------------------------


def test_a_wide_hero_image_scores_well() -> None:
    assert score_image(b"", width=1200, height=630) > 0
    assert score_image(b"", width=1600, height=900) > score_image(b"", width=700, height=400)


def test_a_square_tile_is_rejected() -> None:
    """A category tile is square and repeats across unrelated posts."""
    assert score_image(b"", width=1200, height=1200) < 0


def test_a_thumbnail_is_rejected_by_size() -> None:
    """300x300 upscaled to 1200 is visibly soft; better to draw a placeholder."""
    assert score_image(b"", width=300, height=300) < 0
    assert score_image(b"", width=512, height=512) < 0


def test_a_portrait_poster_is_rejected() -> None:
    """Taller than 3:2 looks wrong in a landscape card."""
    assert score_image(b"", width=800, height=1200) < 0


def test_a_small_but_landscape_image_is_kept_and_penalised() -> None:
    """640x360 is usable as a last resort; it just should not win against a 1200."""
    small = score_image(b"", width=640, height=360)
    large = score_image(b"", width=1200, height=630)
    assert small > 0
    assert small < large


# --- excluding aggregator cards ---------------------------------------------------


def test_an_aggregator_generated_card_is_refused() -> None:
    """The aihot card carries that site own logo and score badge."""
    assert _JUNK_IMAGE.search("https://aihot.news/og/items/e9h2rnoj3dh3lsjofvpcsbbe4.png")
    assert _JUNK_IMAGE.search("https://example.com/social-preview.png")


def test_an_ordinary_article_image_is_not_refused() -> None:
    for url in (
        "https://platform.theverge.com/wp-content/uploads/sites/2/story.jpg",
        "https://pbs.twimg.com/media/HVFW82pXEAATBsd.jpg",
        "https://storage.googleapis.com/gweb-cloudblog-publish/images/Blog_Headers.png",
    ):
        assert not _JUNK_IMAGE.search(url), url


# --- candidates ------------------------------------------------------------------


def test_the_social_card_comes_first_but_the_body_images_are_kept() -> None:
    """Size is unknown until download, so provenance orders the list and scoring decides."""
    html = (
        '<meta property="og:image" content="https://x.com/card.jpg">'
        '<img src="https://x.com/body1.jpg">'
        '<img src="https://x.com/body2.jpg">'
    )
    got = find_image_candidates(html, "https://x.com/story")
    assert [c.source for c in got] == ["og", "img", "img"]


def test_duplicate_urls_appear_once() -> None:
    html = (
        '<meta property="og:image" content="https://x.com/a.jpg">'
        '<img src="https://x.com/a.jpg">'
    )
    got = find_image_candidates(html, "https://x.com/s")
    assert len(got) == 1


# --- the placeholder -------------------------------------------------------------


def test_a_placeholder_is_a_real_landscape_webp() -> None:
    """Every entry carries a picture; a hole in the layout reads as broken."""
    pytest.importorskip("PIL")
    from io import BytesIO

    from PIL import Image

    data = placeholder("e30308f39fee971")
    assert data is not None
    with Image.open(BytesIO(data)) as image:
        assert image.format == "WEBP"
        assert image.width == 1200 and image.height == 630


def test_the_same_story_always_gets_the_same_placeholder() -> None:
    """A re-run must not change the picture a published page already shows."""
    pytest.importorskip("PIL")
    assert placeholder("event-a") == placeholder("event-a")
    assert placeholder("event-a") != placeholder("event-b")
