"""Catalogue rows are not stories, whoever serves them.

Measured 2026-10-25, after `api:aibase-com` was exempted from filtering: 28 of its 40 items
were navigation chrome rather than news --

    #2 Gemini & Gemini Advanced gemini.google.com
    #3 Claude 2 claude.ai
    AI Tools Directory
    Full Ranking

-- and two of them ranked into the top ten of the issue. `#2 Gemini & Gemini Advanced` tells a
reader nothing that happened.

That source is no longer exempt, but the shape is not unique to it: any extractor pointed at a
listing page produces it. This is the content-level guard, so the defect cannot return through
a different feed.
"""

from __future__ import annotations

from aidaily.catalogue import is_catalogue_row


def test_a_ranked_link_is_a_catalogue_row() -> None:
    """The two entries that reached the top ten."""
    assert is_catalogue_row("#2 Gemini & Gemini Advanced gemini.google.com")
    assert is_catalogue_row("#3 Claude 2 claude.ai")


def test_a_subdomain_does_not_defeat_the_match() -> None:
    """`gemini.google.com` has two dots; a single-label pattern missed it."""
    assert is_catalogue_row("#9 Some Tool app.example.co.uk")


def test_listing_page_headings_are_caught() -> None:
    for title in ("AI Tools Directory", "Full Ranking", "AI Brand Monitoring"):
        assert is_catalogue_row(title), title


def test_a_real_headline_is_untouched() -> None:
    """The guard must not eat news that happens to mention a product."""
    for title in (
        "月之暗面 Kimi K3.1 Pro 上线 OpenRouter，1M 上下文多模态开源权重模型",
        "Anthropic 用 Claude 缩减开源代码攻击面：25 个项目发现 493 个问题",
        "NVIDIA 发布 Nemotron 3.5 Super VL",
        "OpenAI 完成 300 亿美元融资，估值 1.25 万亿",
        "Gemini 4 发布",
    ):
        assert not is_catalogue_row(title), title


def test_an_empty_title_is_dropped() -> None:
    assert is_catalogue_row("")
    assert is_catalogue_row("   ")


def test_a_leading_hash_without_a_domain_is_a_headline() -> None:
    """`#1` alone is not the signal; the bare domain at the end is."""
    assert not is_catalogue_row("#1 OpenAI 发布新模型")