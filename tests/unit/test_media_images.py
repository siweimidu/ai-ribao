"""Images: where they come from, and the rules that keep them from breaking a run.

Measured 2026-10-21 against the live sources:

    og:image present   blog.google yes, theverge.com yes, openai.com 403
    X post attachment  only through api.fxtwitter.com; the page itself has no usable card
    compression        226,458 bytes -> 23,590 at 1200px WebP, 10.4% of the original

The whole feature rests on three properties: a missing image never fails a run, a stored URL
points at the original publisher rather than an aggregator, and the filename is content-addressed
so a re-run adds nothing.
"""

from __future__ import annotations

from aidaily.media import ArticleImage, _drop_resize, find_image_url, to_webp
from aidaily.mediastore import MEDIA_REPOS, public_url, repo_for


# --- finding the image -----------------------------------------------------------


def test_og_image_wins_over_the_body_images() -> None:
    """A declared social card is the publisher own choice of what represents the story."""
    html = (
        '<meta property="og:image" content="https://x.com/card.jpg">'
        '<img src="https://x.com/body.jpg">'
    )
    found = find_image_url(html, "https://x.com/story")
    assert found is not None
    assert found.url == "https://x.com/card.jpg"
    assert found.source == "og"


def test_the_meta_tag_is_read_in_either_attribute_order() -> None:
    """Both layouts occur in the wild and neither is invalid HTML."""
    a = '<meta property="og:image" content="https://x.com/a.jpg">'
    b = '<meta content="https://x.com/b.jpg" property="og:image">'
    assert find_image_url(a, "https://x.com/s").url == "https://x.com/a.jpg"
    assert find_image_url(b, "https://x.com/s").url == "https://x.com/b.jpg"


def test_a_relative_url_is_resolved_against_the_page() -> None:
    """og:image is frequently relative; storing it raw gives a broken img."""
    html = '<meta property="og:image" content="/img/hero.png">'
    assert find_image_url(html, "https://x.com/a/story").url == "https://x.com/img/hero.png"


def test_logos_and_icons_are_not_the_story() -> None:
    html = '<img src="https://x.com/logo.png"><img src="https://x.com/story.jpg">'
    found = find_image_url(html, "https://x.com/s")
    assert found is not None and found.url.endswith("story.jpg")


def test_no_image_at_all_is_none_not_an_exception() -> None:
    assert find_image_url("<html><body>no pictures</body></html>", "https://x.com/s") is None


# --- URL normalisation -----------------------------------------------------------


def test_resize_parameters_are_stripped_without_breaking_the_url() -> None:
    """The first version left the separator behind: a.jpg?w=1&h=2 became a.jpg&h=2, a 404."""
    assert _drop_resize("https://x.com/a.jpg?width=600&fit=crop&q=80") == "https://x.com/a.jpg"
    assert _drop_resize("https://x.com/a.jpg") == "https://x.com/a.jpg"


def test_a_query_that_is_not_a_resize_parameter_is_kept() -> None:
    """X serves the full image through ?name=orig; stripping it would downgrade the picture."""
    assert _drop_resize("https://pbs.twimg.com/media/x.jpg?name=orig").endswith("?name=orig")


# --- compression -----------------------------------------------------------------


def test_compression_shrinks_a_real_image_by_an_order_of_magnitude() -> None:
    """The ratio is what makes 40 images a day fit in a repository at all."""
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (3614, 2034), (120, 90, 60)).save(buffer, "JPEG", quality=95)
    raw = buffer.getvalue()

    webp = to_webp(raw)
    assert webp is not None
    assert len(webp) < len(raw)
    with Image.open(BytesIO(webp)) as out:
        assert out.format == "WEBP"
        assert out.width == 1200


def test_bytes_that_are_not_an_image_return_none() -> None:
    assert to_webp(b"this is not an image") is None


# --- storage ---------------------------------------------------------------------


def test_the_url_is_absolute_and_names_its_repository() -> None:
    """A rollover must not break old pages, so the repository is in the URL itself."""
    repo = repo_for("2026-10-21")
    url = public_url(repo, "2026-10-21", "e1-abcd1234.webp")
    assert url.startswith("https://cdn.jsdelivr.net/gh/")
    assert repo in url
    assert url.endswith("/2026-10-21/e1-abcd1234.webp")


def test_adding_a_repository_row_rolls_over_by_date() -> None:
    """The rollover mechanism itself: a date picks the newest row at or before it."""
    first = MEDIA_REPOS[0][1]
    assert repo_for("2026-10-21") == first


def test_the_first_row_covers_the_earliest_possible_date() -> None:
    assert MEDIA_REPOS[0][0] <= "2026-01-01"