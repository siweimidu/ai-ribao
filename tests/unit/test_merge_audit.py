"""The pre-publication merge audit.

Measured 2026-10-23: one published entry was headlined "企业 AI 越用越复杂，如何用一个 Gateway
管好模型、Agent 和成本？" and listed twelve InfoQ links, while its facts named Qwen kernel work,
a DeepSeek funding round and a Huawei assistant review. The link the reader clicked was one of
the twelve, so it went to an article the entry never described.

The dedup keys are what broke. This check looks at the outcome instead -- the headlines that
ended up in one event -- so it catches the next shape of the same failure, not just that one.
"""

from __future__ import annotations

from aidaily.mergeaudit import FOREIGN_SHARE_ALERT, HEADLINE_ALERT, inspect, report


class _Event:
    def __init__(self, event_id: str, title: str) -> None:
        self.event_id = event_id
        self.title = title


class _Digest:
    def __init__(self, events: list[_Event]) -> None:
        self.top_events = events


BROKEN = "企业 AI 越用越复杂，如何用一个 Gateway 管好模型、Agent 和成本？"
FOREIGN = [
    "Qwen 线性注意力优化实践",
    "DeepSeek 完成千亿融资，结盟完美世界、中芯聚源",
    "上下文语言模型：通过自主管理上下文提升性能",
    "实测小艺 Work：从全媒体运营到深度研究的完整体验",
    "智源众智 FlagOS 2.2 让前沿模型与多元算力协同演进",
    "PostgreSQL 19 发不出来？AI找茬太快",
    "AI 赋能开发，Spotify 月代码变更量翻倍",
    "GitLab 19.4 发布，新增目标驱动型智能体",
]


def test_the_real_broken_entry_is_flagged() -> None:
    digest = _Digest([_Event("e1", BROKEN)])
    found = inspect(digest, {"e1": FOREIGN})
    assert len(found) == 1
    assert found[0].foreign >= 7


def test_a_normal_multi_outlet_story_is_not_flagged() -> None:
    """Four outlets reporting one launch share the launch entities; that is normal."""
    digest = _Digest([_Event("e2", "OpenAI 发布 GPT-6 Astra")])
    headlines = [
        "OpenAI 发布 GPT-6 Astra",
        "OpenAI GPT-6 Astra 正式上线",
        "OpenAI 的 GPT-6 Astra 来了",
    ]
    assert inspect(digest, {"e2": headlines}) == []


def test_a_single_member_is_never_flagged() -> None:
    """One article is one story by definition."""
    digest = _Digest([_Event("e3", BROKEN)])
    assert inspect(digest, {"e3": [BROKEN]}) == []


def test_many_headlines_alone_trigger_a_reason() -> None:
    """Even with shared entities, twelve headlines inside one entry is worth a look."""
    digest = _Digest([_Event("e4", "DeepSeek 发布 V5")])
    headlines = [f"DeepSeek 发布 V5 第{i}篇报道" for i in range(HEADLINE_ALERT + 1)]
    found = inspect(digest, {"e4": headlines})
    assert found and any("不同标题" in r for r in found[0].reasons)


def test_the_report_is_always_present_even_when_empty() -> None:
    """A missing key reads as "not checked"; the guard must always say it ran."""
    doc = report([])
    assert doc["checked"] is True
    assert doc["suspicious_events"] == 0


def test_the_report_keeps_examples_for_the_archive() -> None:
    digest = _Digest([_Event("e1", BROKEN)])
    doc = report(inspect(digest, {"e1": FOREIGN}))
    assert doc["examples"]
    assert doc["examples"][0]["members"] >= 7


def test_a_missing_title_list_does_not_crash() -> None:
    digest = _Digest([_Event("e9", "任意标题")])
    assert inspect(digest, {}) == []


def test_the_foreign_share_threshold_is_below_one() -> None:
    """Requiring every member to be foreign would miss a partial merge."""
    assert FOREIGN_SHARE_ALERT <= 0.6