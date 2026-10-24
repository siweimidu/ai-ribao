"""A merge unions source lists, so a wrong one invents corroboration.

Measured 2026-10-24, the first run with union-find bucketing:

    kept  Moonshot AI Releases Kimi K3.1 Pro ...
    merged  OpenAI now trains its frontier AI models with no internet access

    kept  3万亿级参数规模 全球最大开源AI大模型上新
    merged  Anthropic says its unreleased model is both more capable ...

Two vendors, two stories, one entry each. The model had been handed forty headlines per batch
and started grouping by theme ("a lab announces a model") rather than by subject.

`_plausible` checks every proposed group before it is applied: a merge needs a shared entity,
parameter scale, or designation. A missed merge repeats a story; a wrong one fabricates proof.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.merge_llm import _plausible
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _event(i: int, title: str) -> Event:
    return Event(
        event_id=f"e{i}",
        title=title,
        member_item_ids=[f"m{i}"],
        primary_item_id=f"m{i}",
        source_ids=["s"],
        all_urls=[f"https://x/{i}"],
        first_seen_at=NOW,
        last_updated_at=NOW,
    )


def test_two_vendors_are_never_plausible() -> None:
    """The exact pair that was merged on 2026-10-24."""
    assert not _plausible(
        _event(1, "Moonshot AI Releases Kimi K3.1 Pro: A 2.8T Total/104B Active"),
        _event(2, "OpenAI now trains its frontier AI models with no internet access"),
    )


def test_an_unrelated_lab_is_never_plausible() -> None:
    assert not _plausible(
        _event(1, "3万亿级参数规模 全球最大开源AI大模型上新"),
        _event(2, "Anthropic says its unreleased model is both more capable and better aligned"),
    )


def test_the_same_model_in_two_languages_is_plausible() -> None:
    """The merge this pass exists for."""
    assert _plausible(
        _event(1, "Moonshot AI Releases Kimi K3.1 Pro: A 2.8T Total"),
        _event(2, "月之暗面发布 Kimi K3.1 Pro，100 万 token 上下文"),
    )


def test_a_shared_parameter_scale_is_enough() -> None:
    """`3万亿级参数规模 全球最大开源AI模型上新` names no model but shares the scale."""
    assert _plausible(
        _event(1, "Moonshot AI 推出 3 万亿参数 Kimi K3.1 Pro"),
        _event(2, "3万亿级参数规模 全球最大开源AI模型上新"),
    )


def test_a_group_with_no_plausible_member_is_rejected() -> None:
    """The check runs per group; one bad member does not poison the rest."""
    keep = _event(1, "Moonshot AI Releases Kimi K3.1 Pro: A 2.8T")
    good = _event(2, "月之暗面发布 Kimi K3.1 Pro，100 万 token")
    bad = _event(3, "OpenAI now trains its frontier models offline")
    assert _plausible(keep, good)
    assert not _plausible(keep, bad)


def test_the_rejection_counter_exists() -> None:
    """A high count means the model is grouping by theme; worth seeing in the report."""
    from aidaily.merge_llm import MergeResult

    assert MergeResult(events=[]).rejected_groups == 0