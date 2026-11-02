"""How many outlets carried a story outranks how long its body is.

2026-11-02: 「美团龙猫发布 LongCat-2.5 原生多模态模型：1.6T 参数」 was carried by five sources
and ranked #04, behind a single-source post and a two-source item. Corroboration was weighted
below content length, so the widest story of the day lost to the wordiest one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.models import Event
from aidaily.rank import RankWeights

NOW = datetime.now(timezone.utc)


def test_corroboration_outweighs_substance() -> None:
    w = RankWeights()
    assert w.corroboration > w.content_substance
    assert w.corroboration + w.content_substance + w.engagement == 1.0


def test_weights_sum_to_one() -> None:
    w = RankWeights()
    total = w.corroboration + w.content_substance + w.engagement
    assert abs(total - 1.0) < 1e-9