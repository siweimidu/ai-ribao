"""Cross-source keyword frequency, borrowed from TrendRadar.

The idea: rank by how widely a subject is discussed across *different* stories, not only by how
many publishers carried one story. `heat._corroboration` already measures the latter.

Measured on the 2026-10-21 issue, two failure modes had to be excluded before the signal was
usable:

  · company names -- "openai" appeared in 14 of 109 headlines, so every OpenAI story scored a
    perfect 1.000 and the ranking stopped discriminating
  · generic vocabulary -- "ai" appeared in 18 of 109, with the same effect

Both are now filtered, and only a term used by at least two distinct headlines carries signal.
"""

from __future__ import annotations

from aidaily.frequency import cross_source_score, frequency_index, keywords_of


def test_a_model_name_is_a_term() -> None:
    assert "gemini" in keywords_of("Google finally releases Gemini 4 Argon")


def test_a_company_name_is_not_a_term() -> None:
    """Otherwise every story from one company scores the maximum."""
    assert "openai" not in keywords_of("OpenAI hires a new CFO")
    assert "anthropic" not in keywords_of("Anthropic publishes a paper")


def test_generic_vocabulary_is_not_a_term() -> None:
    assert "ai" not in keywords_of("AI is changing everything")
    assert "model" not in keywords_of("A new model ships")
    assert "agent" not in keywords_of("Building an agent")


def test_a_trailing_attribution_is_stripped() -> None:
    """Syndicated copies differ only in " - Outlet", and that made them look distinct."""
    assert keywords_of("Gemini 4 launches - 中国江苏网") == keywords_of("Gemini 4 launches")


def test_a_term_used_once_carries_no_signal() -> None:
    """Returning a small non-zero here would let every unique headline score."""
    index = frequency_index(["Gemini 4 launches"])
    score, terms = cross_source_score("Gemini 4 launches", index)
    assert score == 0.0
    assert terms == []


def test_a_term_used_by_several_stories_scores() -> None:
    """Four genuinely different stories that happen to share a subject.

    They must NOT be collapsed -- different launches, different pricing, different benchmarks --
    but the shared subject is exactly the signal this module exists to measure.
    """
    index = frequency_index([
        "Gemini 4 launches today",
        "Anthropic cuts Claude pricing",
        "Gemini 4 wins every benchmark",
        "Meta open sources Llama 5",
        "Gemini 4 API limits published",
    ])
    score, terms = cross_source_score("Gemini 4 launches today", index)
    assert score > 0.0
    assert terms == ["gemini"]


def test_the_score_is_bounded() -> None:
    index = frequency_index([f"Gemini 4 story {n}" for n in range(40)])
    score, _ = cross_source_score("Gemini 4 launches", index)
    assert 0.0 <= score <= 1.0


def test_near_identical_headlines_count_once() -> None:
    """Seven headlines about one conference from a single search source must not score seven.

    Measured: 物理AI与世界模型大会 arrived as seven unclustered headlines from one Google News
    query, and every one of them took the maximum bonus.
    """
    titles = [
        "物理AI与世界模型大会 多领域分会场活动举行",
        "物理AI与世界模型大会 看机器人如何赋能多元场景",
        "物理AI与世界模型大会 科创人士看好南京",
    ]
    index = frequency_index(titles)
    # At most one of the three may have contributed, so no term can exceed 1.
    assert max(index.values()) <= 1