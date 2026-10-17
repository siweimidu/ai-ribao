"""A model release outranks a promotion, however widely the promotion is shared.

## The ruling

模型发布一定要排前面。「促销/限免/优惠」这类商业活动降权——这类热度再高也不能盖过头部 AI
公司的模型发布。

## What this pins

Two independent mechanisms, because either alone left a hole:

1. `significance` caps a commercial post at 1.0 and denies it the `widely_reported` floor. Before
   this, eight sources on a free-trial announcement scored 1.6 while the launch it advertised
   scored 3.2 -- correct -- but 1.6 was still enough to reach the top once heat was computed.
2. `HeatWeights.magnitude` (0.40) is now larger than `corroboration` (0.18). At 0.25 vs 0.28 the
   single heaviest term was reach, so no amount of importance could not be outvoted by enough
   outlets. Measured on 2026-10-17: a WorkBuddy free-trial post led the digest over DeepSeek
   V4.1 Flash until both mechanisms were in place.
"""

from __future__ import annotations

import pytest

from aidaily.heat import HeatWeights
from aidaily.significance import significance

PROMO = [
    "WorkBuddy Intl 更新支持 DeepSeek-V4.1-Flash-1017，10 月 31 日前免费",
    "OpenCode 限免 DeepSeek V4.1 Flash",
    "Kimi 免费试用新会员",
    "某平台推出 5 折优惠券",
    "DeepSeek 限时特惠",
]

RELEASES = [
    "DeepSeek 发布 DeepSeek-V4.1-Flash-1017，性能更强且输出更省 token",
    "OpenAI 发布 GPT-6 Astra Pro",
    "Google 发布 Gemini 4 Argon",
    "DeepSeek 开放自研搜索 API",
]


@pytest.mark.parametrize("title", PROMO)
def test_a_promotion_is_capped_at_one(title: str) -> None:
    score, _ = significance(title, independent_sources=8)
    assert score == 1.0, f"{title} scored {score}"


@pytest.mark.parametrize("title", PROMO)
def test_reach_cannot_promote_a_promotion(title: str) -> None:
    one, _ = significance(title, independent_sources=1)
    many, comps = significance(title, independent_sources=12)
    assert many == one, "広泛转载改变了商业活动的分数"
    assert "widely_reported" not in comps


@pytest.mark.parametrize("title", RELEASES)
def test_a_model_release_is_still_promoted(title: str) -> None:
    score, _ = significance(title, independent_sources=1)
    assert score >= 2.8, f"{title} only scored {score}"


@pytest.mark.parametrize("title", PROMO)
def test_every_promotion_scores_below_every_release(title: str) -> None:
    """The ordering the user asked for, asserted directly."""
    promo_score, _ = significance(title, independent_sources=12)
    for release in RELEASES:
        release_score, _ = significance(release, independent_sources=1)
        assert promo_score < release_score, (
            f"促销 {promo_score} 不低于发布 {release_score}: {title} / {release}"
        )


def test_magnitude_outweighs_corroboration() -> None:
    """Importance must be able to beat reach, or the ratio above cannot hold in the total."""
    w = HeatWeights()
    assert w.magnitude > w.corroboration


def test_weights_still_sum_to_one() -> None:
    w = HeatWeights()
    total = (w.corroboration + w.magnitude + w.engagement + w.reach
             + w.substance + w.velocity + w.freshness)
    assert abs(total - 1.0) < 1e-9, f"weights sum to {total}"


def test_an_ordinary_ai_story_is_unaffected() -> None:
    """The demotion must not swallow genuine non-commercial coverage."""
    score, _ = significance("DeepSeek 总结全年技术进展", independent_sources=4)
    assert score >= 1.0
