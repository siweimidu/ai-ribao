"""A launch is not a repeat of its own preview.

Measured 2026-10-24: Kimi K3.1 Pro shipped and the issue did not lead with it -- it did not
contain it at all. Four Kimi items were collected and all four were removed by cross-day dedup:

    10-18  DeepSeek之后又一家国产AI出大招：2.8万亿参数 Kimi K3.1已现身
    10-21  中国模型沉寂一月后：GLM-Omni、Kimi K3.1 与 Qwen 4 动向
    10-24  月之暗面发布 Kimi K3.1 Pro，100 万 token 上下文

The first two are a spotting and a rumour roundup. The third is the release. To a reader those
are different events -- one says a thing exists, the other says it is available -- so a launch
headline must not be deduplicated against a preview inside the window.
"""

from __future__ import annotations

from aidaily.history import _is_ship_not_preview


def test_a_launch_over_a_spotted_preview_is_not_a_repeat() -> None:
    """The exact pair that removed the day biggest story."""
    assert _is_ship_not_preview(
        "月之暗面发布 Kimi K3.1 Pro，100 万 token 上下文",
        ["DeepSeek之后又一家国产AI出大招：2.8万亿参数 Kimi K3.1已现身"],
    )


def test_a_launch_over_a_rumour_roundup_is_not_a_repeat() -> None:
    assert _is_ship_not_preview(
        "Moonshot AI Releases Kimi K3.1 Pro: A 2.8T Total/104B Active",
        ["中国模型沉寂一月后：GLM-Omni、Kimi K3.1 与 Qwen 4 动向"],
    )


def test_two_launch_headlines_are_still_a_repeat() -> None:
    """Four outlets covering one launch on four days must still collapse."""
    assert not _is_ship_not_preview(
        "月之暗面发布 Kimi K3.1 Pro",
        ["Moonshot AI Releases Kimi K3.1 Pro: A 2.8T"],
    )


def test_a_headline_without_a_launch_verb_is_never_exempted() -> None:
    """Only a release gets the exemption; commentary does not."""
    assert not _is_ship_not_preview(
        "Anthropic 表示其未发布模型更强",
        ["某厂商发布新模型"],
    )


def test_an_empty_stored_title_does_not_crash() -> None:
    assert not _is_ship_not_preview("发布新模型", [])
    assert not _is_ship_not_preview("发布新模型", [""])


def test_both_paths_of_find_repeat_consult_the_rule() -> None:
    """The keyed fast path and the fuzzy fallback must apply the same exemption."""
    import inspect

    source = inspect.getsource(__import__("aidaily.history", fromlist=["x"]).PublishedHistory.find_repeat)
    assert source.count("_is_ship_not_preview") == 2, "both paths must consult it"