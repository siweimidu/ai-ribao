"""The four-file profile: scope, scoring, output, and wiring.

There was one file before -- `config/profile.md`, a single scoring rubric. Reading Horizon's
showed why the split matters:

* `match.md` answers "does this belong to the section at all?"
* `analysis.md` answers "how important is it?"
* `enrichment.md` answers "how is it written, and when should a block be left empty?"
* `profile.json` wires them: which prompts, which blocks, what is primary.

Conflating the first two is the specific mistake. A model asked to rate *and* judge membership
answers both with one number, and uses "not important" to reject "not in scope" -- which need
opposite handling. That is how an Apple smart speaker got rated merely-unimportant instead of
out of scope, and published third.
"""

from __future__ import annotations

import json

from aidaily.profiles import (
    DEFAULT_PROFILE_ID,
    available_profiles,
    load_profile,
)
from aidaily.rubric import load_profile as load_rubric_text

ROOT_PROFILE_DIR = None


def test_the_shipped_profile_loads() -> None:
    profile = load_profile()
    assert profile is not None, "config/profiles/ai-daily 必须存在"
    assert profile.id == DEFAULT_PROFILE_ID
    assert profile.name == "AI 日报"


def test_all_four_documents_are_present_and_non_empty() -> None:
    """Four files, four jobs. A missing one silently degrades the prompt to a shorter one."""
    profile = load_profile()
    assert profile is not None
    assert "属于本栏目" in profile.match, "match.md 必须说明什么属于本栏目"
    assert "不属于" in profile.match, "match.md 必须说明什么不属于 —— 这是它存在的理由"
    assert "评分标准" in profile.analysis
    assert "写作要求" in profile.enrichment
    assert profile.source is not None


def test_match_states_scope_and_analysis_states_score() -> None:
    """The separation, asserted directly.

    `match.md` must not contain the score bands (that is `analysis.md`'s job), because a
    scope document that also scores invites the model to answer membership with a number.
    """
    profile = load_profile()
    assert profile is not None
    assert "突破性" not in profile.match, "band 名称不该出现在范围判定里"
    assert "突破性" in profile.analysis


def test_match_carries_the_measured_false_positives() -> None:
    """Examples, not adjectives.

    `match.md` lists the real items that reached the top twenty of a measured run. Without
    them "is it about AI" is an adjective the model can read generously; with them it is a
    comparison against cases that were actually wrong.
    """
    profile = load_profile()
    assert profile is not None
    for example in ("Apple 发布 7 英寸智能音箱", "Ray-Ban", "Wi-Fi"):
        assert example in profile.match, f"match.md 缺少实测反例：{example}"


def test_analysis_names_the_three_prohibitions() -> None:
    """Each one encodes a failure this project actually produced."""
    profile = load_profile()
    assert profile is not None
    assert "不要把热度等同于重要性" in profile.analysis
    assert "不要奖励夸张的标题" in profile.analysis
    assert "不要因为「提到 AI」就给分" in profile.analysis


def test_the_four_blocks_are_the_epistemic_buckets() -> None:
    """The blocks are what the pipeline already produces, and two of them are required.

    `uncertainties` being *required* is deliberate: an empty uncertainties block and a "no
    uncertainties" claim look identical on the page, and the latter is almost never true.
    """
    profile = load_profile()
    assert profile is not None
    assert [b.id for b in profile.blocks] == [
        "facts", "inferences", "opinions", "uncertainties"
    ]
    required = {b.id for b in profile.required_blocks}
    assert required == {"facts", "uncertainties"}
    assert profile.primary_block is not None
    assert profile.primary_block.id == "facts"


def test_enrichment_says_when_not_to_emit_a_block() -> None:
    """Horizon states this plainly and it is the part this project was missing.

    A prompt that says "write four sections" gets four sections, including the ones with
    nothing in them. The profile has to say that leaving one empty is correct.
    """
    profile = load_profile()
    assert profile is not None
    assert "何时不输出" in profile.enrichment
    assert "留空" in profile.enrichment


def test_citations_forbid_model_written_urls() -> None:
    """The anti-hallucination contract, asserted where it is declared."""
    profile = load_profile()
    assert profile is not None
    assert profile.citations.get("allow_model_urls") is False
    assert "不要输出任何链接" in profile.enrichment


def test_the_rubric_uses_scope_before_scoring() -> None:
    """Order matters, and it is the whole reason for splitting the files."""
    text, source, section = load_rubric_text()
    assert "ai-daily" in source
    assert "范围判定" in text
    assert "评分标准" in text
    assert text.index("范围判定") < text.index("# 评分标准")


def test_a_missing_profile_returns_none_rather_than_raising(tmp_path) -> None:
    """A checkout without `config/profiles/` must still run; the caller falls back."""
    assert load_profile("does-not-exist", root=tmp_path) is None
    assert available_profiles(root=tmp_path) == []


def test_a_malformed_manifest_returns_none(tmp_path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "profile.json").write_text("{not json", encoding="utf-8")
    assert load_profile("broken", root=tmp_path) is None


def test_partial_manifest_still_loads(tmp_path) -> None:
    """Only `id` is required; everything else has a default, so a minimal profile works."""
    directory = tmp_path / "minimal"
    directory.mkdir()
    (directory / "profile.json").write_text(json.dumps({"id": "minimal"}), encoding="utf-8")
    profile = load_profile("minimal", root=tmp_path)
    assert profile is not None
    assert profile.id == "minimal"
    assert profile.blocks == []
    assert profile.primary_block is None
