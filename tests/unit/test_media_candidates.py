"""Only an image the publisher tied to *this* page may become a story picture.

The 2026-10-21 issue carried two AWS brand decorations (a wireframe-cube motif and a
gradient-orb banner) under five unrelated articles, plus an author portrait and a site banner
elsewhere. Every one was a real, large photograph that passed the size checks. None belonged to
the article it sat beside.

Size cannot establish provenance. The markup can, so the rule is now: og:image, twitter:image,
or an image inside <article> / <figure> / <picture>.
"""

from __future__ import annotations

from aidaily.media import find_image_candidates

PAGE = "https://example.com/post"


def _html(head: str, body: str) -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


def test_og_image_is_a_candidate() -> None:
    html = _html('<meta property="og:image" content="https://example.com/hero.jpg">', "")
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/hero.jpg" in urls


def test_a_bare_img_outside_the_article_is_not_a_candidate() -> None:
    """This is the decoration that appeared under five unrelated stories."""
    html = _html("", '<div class="site-footer"><img src="https://example.com/cubes.jpg"></div>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/cubes.jpg" not in urls


def test_an_image_inside_the_article_is_a_candidate() -> None:
    html = _html("", '<article><img src="https://example.com/diagram.png"></article>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/diagram.png" in urls


def test_an_image_inside_a_figure_is_a_candidate() -> None:
    html = _html("", '<figure><img src="https://example.com/fig.png"></figure>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/fig.png" in urls


def test_junk_images_are_still_rejected() -> None:
    html = _html('<meta property="og:image" content="https://example.com/og/logo.png">', "")
    assert not find_image_candidates(html, PAGE)


def test_a_page_with_no_qualifying_image_yields_nothing() -> None:
    """An empty list is the honest answer; the item renders without a picture."""
    html = _html("", '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">')
    assert find_image_candidates(html, PAGE) == []