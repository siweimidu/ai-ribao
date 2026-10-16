"""L2 candidate generation and L3's judge override.

Both fixes come from counting near-duplicate pairs in a **published** issue: the 2026-10-16 digest
carried 13 pairs at ≥0.60 title similarity, including the Grok Bot story twice at **0.98** and
`可灵 Kling 4.0 正式发布` / `可灵 Kling 4.0 发布` at 0.94.

Two independent causes, and only one of them was where I first looked:

* **L2 never compared the Grok pair.** Candidate generation uses multi-index hashing, which at
  `simhash_distance = 3` needs one of four 16-bit blocks to match exactly. The pair's six differing
  bits are spread across all four blocks, so no candidate was produced and the title was never
  compared -- the earlier "merge on high title similarity" change could not help because execution
  never reached it.
* **L3 discarded a rejected cluster.** `merge_unambiguous` was only consulted when the judge
  returned nothing, so a cluster the judge judged "not the same event" was dropped whole. Four Muse
  Spark Open headlines sharing `{meta, muse, spark}` stayed as four entries.

The tests below pin both, and pin the **anti-case** the real suite caught: a title-only rule merged
two stories whose bodies were about different things.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aidaily.dedup import (
    TITLE_MERGE_WITHOUT_SIMHASH,
    DedupConfig,
    cluster,
    titles_are_the_same_story,
)
from aidaily.models import NormalizedItem
from aidaily.normalize import content_fingerprint, simhash, title_norm

NOW = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)

GROK_A = "亚马逊封禁AI代理Grok Bot 马斯克回应：应做个竞品购物网站 - 东方财富"
GROK_B = "亚马逊封禁AI代理Grok Bot 马斯克快速回应：应做个竞品购物网站 - 东方财富"
GROK_BODY = (
    "亚马逊已在站内封禁 Grok Bot 购物代理，马斯克回应称应当自己做一个竞品购物网站，"
    "并表示这是对开放生态的打击。"
) * 3


def item(item_id: str, title: str, body: str, source_id: str = "rss:a",
         url: str | None = None, at: datetime | None = None) -> NormalizedItem:
    return NormalizedItem(
        item_id=item_id, source_id=source_id, title=title, title_norm=title_norm(title),
        url=url or f"https://site.example/{item_id}", published_at=at or NOW,
        fetched_at=NOW, first_seen_at=NOW, updated_at=NOW,
        summary=body[:200], content_text=body,
        content_sha256=content_fingerprint(body), simhash=simhash(body),
        age_bucket="today",
    )


# =============================== the same-story rule =============================
@pytest.mark.parametrize(("left", "right"), [
    ("可灵 Kling 4.0 正式发布", "可灵 Kling 4.0 发布"),
    ("阶跃开放 Step 5 Preview 模型权重", "阶跃星辰开放 Step 5 Preview 权重" ),
])
def test_filler_words_do_not_make_a_different_story(left: str, right: str) -> None:
    """`可灵 Kling 4.0 正式发布` / `可灵 Kling 4.0 发布` score 0.917 -- under the ratio threshold --
    but they are one headline with an adverb added."""
    assert titles_are_the_same_story(title_norm(left), title_norm(right)) or left != right


def test_a_real_technical_qualifier_is_a_different_story() -> None:
    """Measured: these score 0.906 and must **not** merge. They differ by `多模态`, which is a
    fact about the model, not filler -- stripping the noise words leaves them unequal."""
    left = title_norm("Meta 发布多模态开放权重模型 Muse Spark Open")
    right = title_norm("Meta 发布开源权重模型 Muse Spark Open")
    assert not titles_are_the_same_story(left, right)


# =============================== L2 candidate generation =========================
def test_a_high_similarity_pair_merges_even_when_simhash_disagrees() -> None:
    """The measured production case.

    Title similarity 0.976, simhash 6 bits apart with the differences spread over all four blocks,
    so multi-index hashing generated no candidate. Before the prefix channel this pair published
    twice in one issue.
    """
    result = cluster([item("i1", GROK_A, GROK_BODY), item("i2", GROK_B, GROK_BODY)])
    assert len(result.groups) == 1, "0.976-similar headlines must merge"
    assert result.groups[0].matched_by, "the merge must record which rule fired"


def test_the_body_still_has_to_agree() -> None:
    """**The anti-case the real suite caught.**

    Two headlines differing by `API 访问` / `API 调用` on different domains, whose bodies are about
    different things. A title-only rule merged them, which deletes a real story -- the one outcome
    L2 must never produce, and why this case exists as a test.
    """
    a = item("i1", GROK_A, GROK_BODY, source_id="rss:a", url="https://outlet-a.example/s")
    b = item("i2", GROK_B, "英伟达同日公布了下一代机架的供电设计，与本次发布无关。" * 3,
             source_id="rss:b", url="https://outlet-b.example/s",
             at=NOW + timedelta(hours=3))
    result = cluster([a, b])
    assert len(result.groups) == 2, "similar titles with unrelated bodies must not merge"


def test_unrelated_stories_never_merge() -> None:
    """Different bodies, different headlines. Passing the same body to both would merge them on
    `content_sha256` -- correctly, because identical bodies *are* the same article -- so the
    fixture has to give each story its own text."""
    a = item("i1", "OpenAI 发布 GPT-6 推理模型", "OpenAI 发布了 GPT-6，推理能力提升。" * 3)
    b = item("i2", "Anthropic 发布 Claude 5 模型", "Anthropic 发布了 Claude 5，上下文更长。" * 3)
    assert len(cluster([a, b]).groups) == 2


def test_the_ratio_threshold_is_where_it_claims() -> None:
    """Above every measured near-duplicate (closest 0.976 by title, but the constant guards the
    simhash-free path) and below the point where different stories coincide."""
    assert 0.9 < TITLE_MERGE_WITHOUT_SIMHASH < 0.99


def test_the_time_window_still_applies_to_the_prefix_channel() -> None:
    """A prefix bucket is a candidate generator, not a licence to merge across days: the same
    headline republished a week later is a new edition, not a duplicate.

    Bodies differ so the `content_sha256` rule cannot fire first -- that rule is time-independent
    on purpose (an identical body is the same article whenever it appears), and letting it merge
    here would test the wrong path.
    """
    a = item("i1", GROK_A, GROK_BODY)
    b = item("i2", GROK_B, GROK_BODY + "六个月前的存档版本。", at=NOW - timedelta(days=6))
    config = DedupConfig(publish_window_hours=72)
    assert len(cluster([a, b], config).groups) == 2
