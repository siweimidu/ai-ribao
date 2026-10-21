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


def test_a_square_image_is_not_rejected_by_shape() -> None:
    """Aspect ratio is not a filter.

    The reference layout gives each picture its own proportions -- measured on one entry of its
    2026-10-21 issue: 1080x720, 1080x227, 1080x1017, 1080x351. A square diagram is legitimate.
    What gets rejected is *small*: a 1200x1200 picture is fine, a 192x192 icon is not.
    """
    assert score_image(b"", width=1200, height=1200) > 0
    assert score_image(b"", width=192, height=192) < 0


def test_a_tall_image_is_kept() -> None:
    """A tall diagram is one of the four pictures in that same entry (1080x1017)."""
    assert score_image(b"", width=1080, height=1017) > 0


def test_a_long_banner_is_penalised_but_still_usable() -> None:
    """4.76:1 is a real case; it scores lower than a hero but is not thrown away."""
    banner = score_image(b"", width=1080, height=227)
    hero = score_image(b"", width=1080, height=720)
    assert banner > 0
    assert banner < hero


def test_a_small_image_is_penalised_rather_than_rejected_outright() -> None:
    """640x360 upscaled looks soft; it should still beat no picture at all.

    Below 400px wide there is nothing to work with, so that is a hard floor.
    """
    small = score_image(b"", width=640, height=360)
    large = score_image(b"", width=1200, height=630)
    assert small > 0
    assert small < large
    assert score_image(b"", width=300, height=300) < 0


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
