"""CJK entity extraction: cut at function words, not at fixed widths.

Measured on the 2026-10-21 issue: six reports of 物理AI与世界模型大会 were sliced into fragments
like 与世 / 界模 / 型大 by fixed-width bigrams. They shared only those fragments, so
`merge_unambiguous` saw shared_entities = [模型, 生成] -- generic words -- and the six stayed as
six separate events, each ranking as if it were its own story.

The fix splits a CJK run at function words so the noun phrase survives whole.
"""

from __future__ import annotations

from aidaily.entities import _cjk_segments, extract_entities


def test_a_noun_phrase_survives_whole() -> None:
    """The conference name is the entity; 与世 is noise."""
    segments = _cjk_segments("物理AI与世界模型大会")
    assert "世界模型大会" in segments
    assert "与世" not in segments
    assert "界模" not in segments


def test_reports_of_one_conference_share_entities() -> None:
    """This is the property that lets them cluster into one event."""
    a = extract_entities("2026物理AI与世界模型大会|多领域分会场活动举行")
    b = extract_entities("2026物理AI与世界模型大会|看机器人如何赋能多元场景")
    shared = a & b
    assert "世界模型大会" in shared
    assert len(shared) >= 2


def test_an_unrelated_story_shares_little() -> None:
    """The fix must not merge everything Chinese into one blob."""
    a = extract_entities("2026物理AI与世界模型大会|多领域分会场活动举行")
    b = extract_entities("黄仁勋GTC柏林演讲：AI工厂部署最快缩至14天")
    assert len(a & b) <= 1


def test_a_single_character_fragment_is_dropped() -> None:
    """One character matches too much to be an entity."""
    for segment in _cjk_segments("的了在"):
        assert len(segment) >= 2


def test_a_long_run_still_yields_something() -> None:
    """No boundary word: fall back to bigrams rather than losing the term."""
    segments = _cjk_segments("前沿科技成果集中亮相南京城")
    assert segments
    assert all(len(s) >= 2 for s in segments)