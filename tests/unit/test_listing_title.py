"""Listing pages are scraped directly because half the vendors have no RSS.

Probed 2026-10-19 across the vendors the user named: only OpenAI, Google AI Blog, DeepMind,
Google Research and MiMo publish a feed. Anthropic, xAI, DeepSeek, Kimi, MiniMax, Zhipu,
StepFun, Manus, Hunyuan and Baidu have news pages and nothing else.

Two defects surfaced while wiring MiniMax, and both are pinned here:

1. `select_one` searches descendants only, so an `item_selector` that is itself an anchor
   matched the node and then found no link inside it -- every such source silently yielded 0.
2. A listing page repeats an article in its sidebar and again in the main list, so one URL
   arrived twice and the digest carried the story twice.

Plus the title chrome: `MiniMax M3.1 Flash NEW` and `Oct 18, 2026 Announcements Investing in
the public benefit fund` are not headlines.
"""

from __future__ import annotations

import pytest

from aidaily.fetchers.html import clean_listing_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MiniMax M3.1 Flash NEW", "MiniMax M3.1 Flash"),
        (
            "Oct 18, 2026 Announcements Investing in the public benefit fund",
            "Investing in the public benefit fund",
        ),
        ("Product · Oct 12, 2026 Introducing The X Subscription", "Introducing The X Subscription"),
        ("October 18, 2026 Expanding the Cyber Verification Program", "Expanding the Cyber Verification Program"),
        ("20\u2026", "20\u2026"),
    ],
)
def test_listing_chrome_is_stripped(raw: str, expected: str) -> None:
    assert clean_listing_title(raw) == expected


@pytest.mark.parametrize(
    "title",
    [
        "DeepSeek 发布 V4.1-Flash-1017",
        "MiniMax M3.1 Flash",
        "OpenAI 发布 GPT-6 Astra Pro",
    ],
)
def test_a_real_headline_is_left_alone(title: str) -> None:
    """The cleaner must not eat words that belong to the headline."""
    assert clean_listing_title(title) == title


def test_marketplace_sources_exist_for_the_vendors_without_rss() -> None:
    """MiniMax publishes its launches only on its own site; the source has to be there."""
    from aidaily.registry import load_registry

    ids = {s.source_id for s in load_registry()}
    assert "scrape:official-minimax" in ids
    assert "rss:official-googleai" in ids
