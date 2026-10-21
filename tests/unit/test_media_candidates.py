"""Only `og:image` may become a story picture.

Every looser rule produced a wrong picture on a real issue:

  - any `<img>` anywhere -> two AWS brand decorations under five unrelated articles
  - `<img>` inside `<article>` -> a stock photo of a bin and one of a hard-disk platter beside a
    story about an enterprise AI agent
  - `twitter:image` -> a grey blur on a Mistral announcement

`og:image` is the one declaration a publisher writes *about this page*, for the express purpose
of representing it. The cost is accepted: a story whose publisher ships no `og:image` shows no
picture. An empty slot is honest; a wrong picture is a lie about the story.
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


def test_a_bare_img_is_not_a_candidate() -> None:
    """The AWS decorations arrived this way."""
    html = _html("", '<div><img src="https://example.com/cubes.jpg"></div>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/cubes.jpg" not in urls


def test_an_img_inside_article_is_not_a_candidate() -> None:
    """A ZDNet story carried a bin and a hard-disk platter this way."""
    html = _html("", '<article><img src="https://example.com/diagram.png"></article>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/diagram.png" not in urls


def test_an_img_inside_a_figure_is_not_a_candidate() -> None:
    html = _html("", '<figure><img src="https://example.com/fig.png"></figure>')
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/fig.png" not in urls


def test_twitter_image_is_not_a_candidate() -> None:
    """Mistral announced Voxtral 3 with a grey blur here."""
    html = _html('<meta name="twitter:image" content="https://example.com/blur.png">', "")
    urls = [c.url for c in find_image_candidates(html, PAGE)]
    assert "https://example.com/blur.png" not in urls


def test_an_author_portrait_is_rejected() -> None:
    html = _html('<meta property="og:image" content="https://example.com/author/jane.jpg">', "")
    assert not find_image_candidates(html, PAGE)


def test_junk_images_are_still_rejected() -> None:
    html = _html('<meta property="og:image" content="https://example.com/og/logo.png">', "")
    assert not find_image_candidates(html, PAGE)


def test_a_page_with_no_og_image_yields_nothing() -> None:
    """An empty list is the honest answer; the item renders without a picture."""
    html = _html("", '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">')
    assert find_image_candidates(html, PAGE) == []