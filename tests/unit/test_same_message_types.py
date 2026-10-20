"""One story must not be published twice because two publishers spelled it differently.

Measured on the 2026-10-20 digest: of fifty-four events, forty-two were single-source, and at
least two pairs were plainly the same news that had failed to merge --

    DeepSeek参与塑造Huawei人工智能芯片设计   (SiliconANGLE)
    DeepSeek参与塑造华为人工智能芯片设计     (a Chinese publisher)

They share an actor, no event type, and 0.90 content overlap. Two separate gaps kept them
apart:

1. `same_message` returned False whenever the event-type sets did not intersect -- including
   when **both were empty**. Requiring a shared type is not the same as forbidding a
   contradiction, and it turned a correct pair into a false negative.
2. Clustering only joined items sharing two entities, so a headline naming one entity could
   never reach its own translation.
"""
from __future__ import annotations

import pytest

from aidaily.samestory import _content_overlap, event_types, same_message


@pytest.mark.parametrize(
    "left,right",
    [
        ("DeepSeek参与塑造Huawei人工智能芯片设计", "DeepSeek参与塑造华为人工智能芯片设计"),
        ("Gemini 4 发布", "Gemini 4 Argon 向全球订阅者开放"),
    ],
)
def test_a_published_duplicate_is_one_message(left: str, right: str) -> None:
    """Both pairs appeared as separate events in the 2026-10-20 digest."""
    assert same_message(left, right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("Microsoft 推出针对失控 AI 代理的新安全控制", "Microsoft称人工智能代理类似内部威胁"),
        ("Perplexity 发布并开源两款决策模型", "Perplexity 开源 SPACE 沙箱平台"),
        ("DeepSeek 发布 V4.1-Flash", "DeepSeek恢复服务并补偿API用户"),
    ],
)
def test_different_news_stays_apart(left: str, right: str) -> None:
    """The loosening must not collapse unrelated stories about one vendor."""
    assert not same_message(left, right)


def test_an_empty_event_type_pair_still_compares_wording() -> None:
    """The exact regression: both sides type-less returned False before comparing words.

    `DeepSeek参与塑造Huawei人工智能芯片设计` names no event type, so the intersection was
    empty and the function returned False without ever looking at the words -- even though
    the words overlap 0.90.
    """
    left = "DeepSeek参与塑造Huawei人工智能芯片设计"
    right = "DeepSeek参与塑造华为人工智能芯片设计"
    assert not event_types(left) and not event_types(right)
    assert same_message(left, right)
