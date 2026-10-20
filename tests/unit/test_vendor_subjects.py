"""A vendor whose model names were not in the subject list could never be deduplicated.

`MiniMax M3.1 Flash` and `MiniMax-M3.1-Flash` both yielded **no subject**, so two reports of one
launch had nothing in common to compare -- the deduplicator saw two unrelated stories.

MiniMax, StepFun, Hunyuan, MiMo, Manus, Ling and Kling were all missing. Added 2026-10-19 while
tracing why the M3.1-Flash release never reached the digest.
"""

from __future__ import annotations

import pytest

from aidaily.samestory import same_message, subjects


@pytest.mark.parametrize(
    "title,expected",
    [
        ("MiniMax M3.1 Flash: Redefining Agent Performance and Cost", "minimax-m3-1-flash"),
        ("MiniMax M3.1 Flash", "minimax-m3-1-flash"),
        ("MiniMax-M3.1-Flash 即将发布", "minimax-m3-1-flash"),
        ("MiniMax H3", "minimax-h3"),
    ],
)
def test_minimax_designations_are_recognised(title: str, expected: str) -> None:
    assert expected in subjects(title)


@pytest.mark.parametrize(
    "title",
    [
        "StepFun Step-3 发布",
        "腾讯混元 Hunyuan-T1 开源",
        "MiMo-V2.5 上线",
        "Manus 2.0 发布",
        "蚂蚁百灵 Ling-3.0 开源",
        "可灵 Kling 4.0 上线",
    ],
)
def test_other_vendors_resolve_to_a_subject(title: str) -> None:
    assert subjects(title), f"{title} produced no subject"


def test_one_launch_written_three_ways_is_one_subject() -> None:
    """The whole point: same product, different punctuation, one identity."""
    variants = [
        "MiniMax M3.1 Flash",
        "MiniMax-M3.1-Flash",
        "minimax m3.1 flash",
    ]
    keys = {next(iter(subjects(v)), None) for v in variants}
    assert len(keys) == 1, keys


def test_a_release_and_its_announcement_are_one_message() -> None:
    """The formal release and the earlier "coming soon" are the same news."""
    assert same_message(
        "MiniMax M3.1 Flash: Redefining Agent Performance and Cost",
        "MiniMax-M3.1-Flash 即将发布",
    )
