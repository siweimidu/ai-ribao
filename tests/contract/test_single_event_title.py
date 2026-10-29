"""A title reports one event.

Measured 2026-10-29, the lead read:

    2026-10-29 AI 日报 · Gemini 4 Carbon 登顶智能榜单、主打网络安全；微软首次披露 Azure
    收入，来自 OpenAI 的收入达百亿美元

Two unrelated stories in one line, because an aggregated issue title was merged into the Gemini
event and the merge kept the longest string -- which is the container, since it names everything.
"""

from __future__ import annotations

from aidaily.site import _first_clause, _is_compound, _strip_container


def test_the_measured_lead_is_compound() -> None:
    title = (
        "2026-10-29 AI 日报 · Gemini 4 Carbon 登顶智能榜单、主打网络安全；"
        "微软首次披露 Azure 收入，来自 OpenAI 的收入达百亿美元"
    )
    assert _is_compound(title)
    assert _is_compound(_strip_container(title))


def test_the_prefix_is_removed() -> None:
    assert _strip_container("2026-10-29 AI 日报 · Gemini 4 Carbon 登顶") == "Gemini 4 Carbon 登顶"
    assert _strip_container("2026-10-28 早报 — 某模型发布") == "某模型发布"


def test_the_first_clause_is_the_leading_claim() -> None:
    title = "Gemini 4 Carbon 登顶智能榜单、主打网络安全；微软首次披露 Azure 收入"
    assert _first_clause(title) == "Gemini 4 Carbon 登顶智能榜单、主打网络安全"


def test_a_single_event_headline_is_left_alone() -> None:
    for title in (
        "Google 发布 Gemini 4 Carbon：AA Index v5.0 登顶",
        "腾讯 WorkBuddy 上线远程控制，手机可接管电脑",
        "Anthropic 推出 Smart Reports",
    ):
        assert not _is_compound(title), title


def test_an_empty_title_is_not_compound() -> None:
    assert not _is_compound("")