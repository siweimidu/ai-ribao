"""Feeds that carry a teaser get their article page fetched, so the model has something to read.

Measured 2026-10-22 on a full run: almost every source produced items whose body was under 200
characters -- `huggingface` 888/888, `deepmind` 99/100, `therundown.ai` 50/50. Those feeds
publish a headline plus one line, and the article is one request away.

The model is asked for facts, inferences and uncertainties from this material. Given a teaser it
can only restate the headline, which is why some entries read thin. With the page fetched, a
`therundown.ai` item goes from 53 characters to 7,723.

These tests pin the extraction and the opt-in: fetching every page would multiply collect time
across 130 sources and hit hosts that never asked for it.
"""

from __future__ import annotations

import pytest

from aidaily.fulltext import extract_body


def _page(*paragraphs: str) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"<html><head><style>.x{{color:red}}</style></head><body>{body}</body></html>"


LONG = "OpenAI shipped a new safety playbook that changes how models are released to the public."


def test_prose_is_extracted() -> None:
    html = _page(LONG, LONG * 3, LONG * 4)
    body = extract_body(html)
    assert "safety playbook" in body
    assert len(body) > 400


def test_short_paragraphs_are_dropped() -> None:
    """Nav labels, captions and "Read more" links are paragraphs too."""
    html = _page("Home", "News", "About", LONG, LONG * 3, LONG * 4)
    body = extract_body(html)
    assert "Home" not in body
    assert "safety playbook" in body


def test_boilerplate_is_dropped() -> None:
    html = _page(LONG, "Subscribe to our newsletter for more stories like this one every day.", LONG * 3)
    body = extract_body(html)
    assert "newsletter" not in body.lower()


def test_scripts_and_styles_do_not_leak_into_the_body() -> None:
    html = (
        "<html><script>var x = \"<p>fake paragraph inside a script tag</p>\";</script>"
        "<style>p { color: red }</style>"
        "<body>" + f"<p>{LONG}</p>" * 4 + "</body></html>"
    )
    body = extract_body(html)
    assert "fake paragraph" not in body
    assert "color: red" not in body


def test_a_page_with_no_prose_returns_nothing() -> None:
    """Returning "" lets the caller keep the teaser, which is never worse."""
    assert extract_body("<html><body><nav>Home</nav></body></html>") == ""
    assert extract_body("") == ""


def test_the_body_is_capped() -> None:
    html = _page(*([LONG] * 500))
    assert len(extract_body(html)) <= 20_000


def test_the_switch_is_opt_in() -> None:
    """`site_fulltext` must default to off: extracting every page would multiply collect time."""
    from aidaily.models import SourceSpec

    field = SourceSpec.model_fields["site_fulltext"]
    assert field.default is False
