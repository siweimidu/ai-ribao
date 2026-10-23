"""The model leaderboard: parsing the source payload and rendering it honestly.

The data comes from artificialanalysis.ai, a Next.js app that streams its state as
`self.__next_f.push([1, "..."])` chunks. The leaderboard page carries all 272 models in one
`initialModels` array inside that payload.

These tests use recorded fixtures rather than the network: the parser is what can break, and a
live fetch would make the suite depend on someone else uptime.
"""

from __future__ import annotations

from aidaily.leaderboard import Model, _array_after, _to_model


def test_an_array_is_found_by_brace_matching() -> None:
    """A regex cannot do this: the array nests and contains brackets inside strings."""
    text = 'x,"initialModels":[{"a":[1,2],"b":"has ] bracket"},{"c":3}],"other":1'
    found = _array_after(text, '"initialModels":')
    assert found is not None
    assert found.startswith("[") and found.endswith("]")
    assert '"c":3' in found


def test_a_missing_marker_returns_none() -> None:
    assert _array_after("nothing here", '"initialModels":') is None


def test_a_bracket_inside_a_string_does_not_end_the_array() -> None:
    text = '[{"t":"a ] b"},{"t":"c"}]'
    found = _array_after("k:" + text, "k:")
    assert found == text


def test_a_model_is_parsed_with_its_benchmarks() -> None:
    raw = {
        "slug": "jt-35b-flash",
        "name": "JT-35B-Flash",
        "modelCreatorName": "China Mobile",
        "intelligenceIndex": 18.66,
        "intelligenceIndexIsEstimated": True,
        "contextWindowTokens": 256000,
        "price1mInputTokens": 0.5,
        "price1mOutputTokens": 1.5,
        "isReasoning": False,
        "isOpenWeights": False,
        "tau2": 0.991,
        "gpqa": 0.829,
    }
    model = _to_model(raw)
    assert model is not None
    assert model.slug == "jt-35b-flash"
    assert model.creator == "China Mobile"
    assert model.intelligence == 18.66
    assert model.context == 256000
    assert model.benchmarks["tau2"] == 0.991


def test_a_missing_benchmark_stays_missing() -> None:
    """Null must not become 0: "not measured" and "scored zero" are different facts."""
    model = _to_model({"slug": "x", "name": "X", "hle": None})
    assert model is not None
    assert "hle" not in model.benchmarks


def test_a_model_without_a_slug_is_dropped() -> None:
    assert _to_model({"name": "No slug"}) is None
    assert _to_model({"slug": "s"}) is None


def test_the_reasoning_variant_moves_out_of_the_name() -> None:
    """`Claude Opus 5.5 (Max, Default Fallback)` wraps to three lines in a table cell."""
    model = _to_model({"slug": "s", "name": "Claude Opus 5.5 (Max, Default Fallback)"})
    assert model is not None
    assert model.name == "Claude Opus 5.5"
    assert model.variant == "Max, Default Fallback"


def test_a_name_without_a_parenthetical_is_untouched() -> None:
    model = _to_model({"slug": "s", "name": "Muse Wonder Full"})
    assert model is not None
    assert model.name == "Muse Wonder Full"
    assert model.variant == ""


def test_the_model_url_points_at_its_own_page() -> None:
    model = Model(slug="jt-35b-flash", name="JT", creator="x")
    assert model.href == "https://artificialanalysis.ai/models/jt-35b-flash"