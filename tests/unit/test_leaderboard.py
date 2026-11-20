"""The model leaderboard: parsing the source payload and rendering it honestly.

The data comes from artificialanalysis.ai, a Next.js app that streams its state as
`self.__next_f.push([1, "..."])` chunks. The leaderboard page carries all 272 models in one
`initialModels` array inside that payload.

These tests use recorded fixtures rather than the network: the parser is what can break, and a
live fetch would make the suite depend on someone else uptime.

The fixtures come in two shapes on purpose. Upstream reshaped its rows on 2026-11-15 (the slug
moved into `release`, the benchmarks into a `scores` object), and the parser dropped every row for
a week without a word. Both shapes are pinned here so the next reshape fails a test instead of
freezing the page.
"""

from __future__ import annotations

from aidaily import leaderboard
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


# ---------------------------------------------------------------------------------------------
# The 2026-11-15 row shape: `release.slug` and a `scores` object.
# ---------------------------------------------------------------------------------------------

# Copied from the live payload, trimmed to the fields the page reads.
_RELEASE_ROW = {
    "id": "042e8a37-fcd0-40f4-8f41-99215fb68eda",
    "release": {"slug": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
    "name": "Claude Sonnet 5.5 (Medium, Default Fallback)",
    "suffix": "Medium, Default Fallback",
    "deprecated": False,
    "isReasoning": True,
    "isOpenWeights": False,
    "paramClass": None,
    "modelCreatorName": "Anthropic",
    "modelCreatorColor": "#cc785c",
    "contextWindowTokens": 1000000,
    "intelligenceIndex": 30.8195522148431,
    "scores": {
        "tau2-bench": 0.991,
        "gpqa-diamond": 0.829,
        "humanitys-last-exam": 0.398,
        "artificial-analysis-long-context-reasoning": 0.763,
        "omniscience-accuracy": 0.457,
        "ifbench": 0.42,
        "scicode": 0.528,
        "mmmu-pro": 0.61,
        "terminalbench-hard": 0.287,
    },
    "price1mInputTokens": 2,
    "price1mOutputTokens": 10,
}


def test_the_current_release_shape_parses() -> None:
    """The slug lives in `release` now; reading only the top level dropped all 287 rows."""
    model = _to_model(dict(_RELEASE_ROW))
    assert model is not None
    assert model.slug == "claude-sonnet-5-5"
    assert model.creator == "Anthropic"
    assert model.intelligence == 30.8195522148431
    assert model.context == 1000000
    assert model.price_input == 2.0


def test_the_current_release_shape_keeps_every_benchmark_column() -> None:
    """kebab-case inside `scores` maps back onto the labels the table renders."""
    model = _to_model(dict(_RELEASE_ROW))
    assert model is not None
    assert model.benchmarks == {
        "tau2": 0.991,
        "gpqa": 0.829,
        "hle": 0.398,
        "lcr": 0.763,
        "omniscience": 0.457,
        "ifbench": 0.42,
        "scicode": 0.528,
        "mmmu": 0.61,
        "terminalbench": 0.287,
    }


def test_the_variant_still_leaves_the_name() -> None:
    """`release.name` is the clean one, but `suffix` and the parenthetical agree with it."""
    model = _to_model(dict(_RELEASE_ROW))
    assert model is not None
    assert model.name == "Claude Sonnet 5.5"
    assert model.variant == "Medium, Default Fallback"


def test_a_missing_estimated_flag_does_not_claim_an_estimate() -> None:
    """The flag is gone upstream; absent must read as "unknown", not as "is estimated"."""
    model = _to_model(dict(_RELEASE_ROW))
    assert model is not None
    assert model.estimated is False


def test_a_true_flag_is_not_read_as_a_score() -> None:
    """`bool` is an `int` in Python: a flag must never become a benchmark value of 1.0."""
    model = _to_model({"release": {"slug": "s"}, "name": "S", "scores": {"tau2-bench": True}})
    assert model is not None
    assert "tau2" not in model.benchmarks


# ---------------------------------------------------------------------------------------------
# Silence was the bug: a payload nobody can parse must say so.
# ---------------------------------------------------------------------------------------------


def test_rows_that_no_longer_parse_are_reported(monkeypatch, capsys) -> None:
    """Zero models out of a populated payload is a shape change, not "nothing to do"."""
    monkeypatch.setattr(
        leaderboard, "_flight_payload", lambda url, timeout=50.0: 'x,"initialModels":[{"foo":1}],"y":2'
    )
    assert leaderboard.fetch_models() == []
    err = capsys.readouterr().err
    assert "全部被丢弃" in err
    assert "解析器需要更新" in err


def test_a_missing_array_is_reported(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        leaderboard, "_flight_payload", lambda url, timeout=50.0: "1:[\"$Sreact.fragment\"]"
    )
    assert leaderboard.fetch_models() == []
    assert "initialModels" in capsys.readouterr().err


def test_the_page_date_is_a_beijing_date() -> None:
    """20:00 UTC is already tomorrow in Beijing; the page must not look a day behind."""
    assert leaderboard._page_date("2026-11-20T20:00:21.827733+00:00") == "2026-11-21"
    assert leaderboard._page_date("2026-11-20T18:00:21+00:00") == "2026-11-21"
    assert leaderboard._page_date("2026-11-20T03:59:00+00:00") == "2026-11-20"

