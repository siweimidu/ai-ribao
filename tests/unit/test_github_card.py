"""Repository cards: what can be fetched, and what cannot.

GitHub own Social Preview shows six figures. Five of them are reachable from the public API;
`Used by` is not -- `usedBy` does not exist as a GraphQL field and the REST dependents endpoint
returns 404 to ordinary tokens. The card omits it rather than inventing a number, and these tests
pin both the parsing and the omission.
"""

from __future__ import annotations

from aidaily.ghcard import THEMES, _shown_languages, card_html
from aidaily.github_meta import repo_of


def test_a_repository_url_is_recognised() -> None:
    assert repo_of("https://github.com/vllm-project/vllm") == "vllm-project/vllm"
    assert repo_of("https://github.com/openai/openai-python.git") == "openai/openai-python"


def test_a_path_inside_a_repository_is_the_same_repository() -> None:
    """`/tree/main/x` describes a place in the repo, not another repo."""
    assert repo_of("https://github.com/vllm-project/vllm/tree/main/benchmarks") == "vllm-project/vllm"
    assert repo_of("https://github.com/vllm-project/vllm/issues/123") == "vllm-project/vllm"


def test_a_github_section_is_not_a_repository() -> None:
    """`/features/copilot` is a marketing page."""
    assert repo_of("https://github.com/features/copilot") is None
    assert repo_of("https://github.com/topics/llm") is None


def test_a_non_github_url_is_not_a_repository() -> None:
    assert repo_of("https://example.com/vllm-project/vllm") is None
    assert repo_of("") is None


def test_the_language_bar_fills_its_row() -> None:
    """Dropping a 0% language must renormalise the rest.

    Measured on huggingface/transformers: the API reports Python 100% plus Dockerfile, Shell and
    Makefile at 0.0%. Keeping them produced three legend entries reading "0%" and a bar that did
    not fill.
    """
    shown = _shown_languages({"Python": 100.0, "Dockerfile": 0.0, "Shell": 0.0})
    assert [name for name, _ in shown] == ["Python"]
    assert abs(sum(pct for _, pct in shown) - 100.0) < 0.01


def test_the_language_bar_keeps_real_shares() -> None:
    shown = _shown_languages({"Python": 85.4, "Rust": 6.4, "Cuda": 4.0, "C++": 2.9, "X": 1.3})
    assert [n for n, _ in shown] == ["Python", "Rust", "Cuda", "C++", "X"]
    assert abs(sum(p for _, p in shown) - 100.0) < 0.01


def test_the_card_carries_every_fetchable_figure() -> None:
    html = card_html(
        full_name="vllm-project/vllm",
        description="An inference engine",
        stars=94589,
        forks=23694,
        contributors=3824,
        discussions=489,
        languages={"Python": 85.4, "Rust": 6.4},
        license_="Apache-2.0",
    )
    for figure in ("94.6k", "23.7k", "3.8k", "489"):
        assert figure in html, figure
    for label in ("Stars", "Forks", "Contributors", "Discussions"):
        assert label in html, label
    assert "Apache-2.0" in html


def test_an_absent_figure_is_omitted_not_shown_as_zero() -> None:
    """`Used by` is not in the API; a card must not invent it, and a missing contributor count
    must not print "0".
    """
    html = card_html(
        full_name="o/r", description="d", stars=1, forks=2,
        contributors=None, discussions=None,
    )
    assert "Contributors" not in html
    assert "Discussions" not in html
    assert "Used by" not in html


def test_the_html_card_has_no_hard_coded_colour() -> None:
    """A fixed colour would look pasted in on three of the four site themes.

    Colours live in STYLE, which is written against the var tokens; the markup itself must carry
    none, or it would survive a theme switch and stay wrong.
    """
    from aidaily.ghcard import STYLE

    html = card_html(full_name="o/r", description="d", stars=1, forks=2)
    for hexlike in ("#0065fd", "#c15f3c", "#16181c", "#fdfcfa"):
        assert hexlike not in html, hexlike

    # And the stylesheet itself must be token-driven.
    assert "var(--fg)" in STYLE
    assert "var(--surface)" in STYLE

def test_all_four_site_themes_are_defined_for_the_png_renderer() -> None:
    assert set(THEMES) == {"light", "dark", "claude-light", "claude-dark"}
    for name, palette in THEMES.items():
        for key in ("bg", "surface", "fg", "muted", "border", "accent"):
            assert key in palette, (name, key)
