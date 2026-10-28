"""Ordinary prose must not read as AI vocabulary.

## What shipped that should not have

On 2026-10-28 four stories with no AI subject reached the digest:

* `Trump praises Canadian separatists amid delicate trade talks` (Axios)
* `DOJ fails to indict Cassidy Hutchinson, a key Jan. 6 witness` (Axios)
* `Africa Finance Corporation names Lobito Corridor builders` (Semafor)
* `Robinson: Raspberry Pi 5 on Fedora` (LWN)

All four scored `focus_multiplier = 1.0`, the maximum. So did 35 others: **39 of 82**
published items were at a perfect score.

## Two independent bugs produced that

1. `_CORE` listed product names as a bare alternation. `cline` matched `declined`, `rag`
   matched `average` / `coverage` / `storage`, `dify` matched `modify`. Every news article
   contains "average" or "coverage", so the vocabulary matched almost anything.
2. The body fallback ran `_headline_focus` -- a *ratio* designed for one-line headlines --
   over 1200 characters of prose, where a single stray hit scores 1.0 because a news body
   matches little of the off-topic list. The Trump story got its 1.0 from "declined".

These tests pin the vocabulary first, then the fallback.
"""

from __future__ import annotations

import pytest

from aidaily.focus import _BODY_LIFT_CAP, _CORE, _LABS, _headline_focus


@pytest.mark.parametrize(
    "word",
    [
        "average", "coverage", "storage", "fragile", "courage", "paragraph",
        "encourage", "fragrance", "declined", "inclined", "modify", "bargain",
        "target", "trigger",
    ],
)
def test_ordinary_english_words_are_not_ai_vocabulary(word: str) -> None:
    """`rag` inside `average` is the biggest false-positive source in this module."""
    assert not _CORE.search(word), f"{word!r} matched {_CORE.findall(word)}"


@pytest.mark.parametrize(
    "term",
    ["RAG", "Cline", "pytorch", "fine-tuned", "multimodal", "context window", "tool use"],
)
def test_real_ai_terms_still_match(term: str) -> None:
    """Tightening boundaries must not delete the vocabulary it protects."""
    assert _CORE.search(term), f"{term!r} no longer matches"


@pytest.mark.parametrize(
    "title",
    [
        "Trump praises Canadian separatists amid delicate trade talks",
        "DOJ fails to indict Cassidy Hutchinson, a key Jan. 6 witness",
        "Africa Finance Corporation names Lobito Corridor builders",
        "Robinson: Raspberry Pi 5 on Fedora",
    ],
)
def test_the_four_published_non_ai_stories_score_as_unrelated(title: str) -> None:
    """These titles reached an AI digest. Each must sit at the no-signal floor."""
    assert _headline_focus(title) < 0.25


def test_a_genuine_ai_headline_is_unaffected() -> None:
    assert _headline_focus("OpenAI 发布 GPT-6 模型") > 0.7
    assert _headline_focus("Anthropic ships a new multimodal model") > 0.7


def test_the_body_lift_is_capped_below_certainty() -> None:
    """A body may rescue a headline; it may not certify it.

    The cap has to clear the 0.50 relevance floor, otherwise the date-titled digest feeds
    this fallback exists for would stop publishing entirely.
    """
    from aidaily.pipeline import MIN_AI_RELEVANCE

    assert _BODY_LIFT_CAP > MIN_AI_RELEVANCE
    assert _BODY_LIFT_CAP < 0.9


def test_one_passing_mention_is_not_structural_evidence() -> None:
    """The rule the fallback applies: a lab, or several terms -- not one passing hit."""
    passing = (
        "Trump praised Canadian separatists on Tuesday as his administration pressed "
        "ahead with delicate trade talks, officials said. An adviser mentioned AI once."
    )
    assert not _LABS.findall(passing)
    assert len(_CORE.findall(passing)) < 3


def test_a_date_titled_digest_body_is_structural_evidence() -> None:
    """The case the fallback exists for: an issue titled by date, body full of models."""
    body = (
        "OpenAI released a new multimodal model today. Anthropic shipped an update to "
        "its inference stack, and DeepSeek open-weighted a 200B model. Hugging Face "
        "benchmarks show multimodal inference costs falling."
    )
    assert _LABS.findall(body)
    assert len(_CORE.findall(body)) >= 3