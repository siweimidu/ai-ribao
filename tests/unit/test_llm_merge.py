"""The same story in different words must become ONE entry with multi-source corroboration.

Measured 2026-10-24: three entries were one launch --

  01  Moonshot AI 推出 3 万亿参数 Kim K3.1 Pro
  02  Kimi 3.1 Pro 推出 Fable-5.1 开放权重与高速 API
  06  全球最大 3 万亿参数开源AI模型上线

Deterministic signals all missed it: title similarity 0.18-0.31 against an 0.85 threshold,
`same_message` False on every pair, and only one title named a model. The third calls it
"the world largest open model" and never says Kimi -- no rule over the text can know.

Merging is also what the reader asked for: repetition is not corroboration. Three entries
claiming one thing is repetition; one entry carried by three sources is corroboration.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from aidaily.merge_llm import BATCH, MergeResult, _listing, _merge_into, merge_duplicates
from aidaily.models import Event

NOW = datetime.now(timezone.utc)


def _event(eid: str, title: str, *, sources=("a",), urls=("https://x/1",)) -> Event:
    return Event(
        event_id=eid,
        title=title,
        member_item_ids=[f"m-{eid}"],
        primary_item_id=f"m-{eid}",
        source_ids=list(sources),
        all_urls=list(urls),
        first_seen_at=NOW,
        last_updated_at=NOW,
        published_range=(NOW, NOW),
    )


def test_merging_unions_sources_and_urls() -> None:
    """That union is the point: it turns repetition into corroboration."""
    keep = _event("e1", "Moonshot AI 推出 Kim K3.1 Pro", sources=("s1",), urls=("https://a",))
    other = _event("e2", "Kimi 3.1 Pro 推出开放权重", sources=("s2",), urls=("https://b",))
    _merge_into(keep, [other])
    assert set(keep.source_ids) == {"s1", "s2"}
    assert set(keep.all_urls) == {"https://a", "https://b"}
    assert len(keep.member_item_ids) == 2


def test_the_corroboration_count_reflects_the_union() -> None:
    keep = _event("e1", "A", sources=("s1",))
    _merge_into(keep, [_event("e2", "B", sources=("s2",)), _event("e3", "C", sources=("s3",))])
    assert keep.independent_source_count == 3


def test_two_feeds_from_one_outlet_count_once() -> None:
    """`independent_source_count` is about outlets, not feed URLs."""
    keep = _event("e1", "A", sources=("hnrss",))
    _merge_into(keep, [_event("e2", "B", sources=("hnrss",))])
    assert keep.independent_source_count == 1


def test_the_absorbed_titles_are_recorded() -> None:
    keep = _event("e1", "标题一")
    _merge_into(keep, [_event("e2", "标题二")])
    assert "标题二" in keep.unique_facts["merged_titles"]


def test_no_model_means_no_merge_and_no_crash() -> None:
    """The pass is optional by design."""
    events = [_event("e1", "A"), _event("e2", "B")]
    import asyncio

    result = asyncio.run(merge_duplicates(events, None))
    assert result.failed
    assert len(result.events) == 2
    assert "未运行" in result.label


def test_a_single_event_is_returned_unchanged() -> None:
    import asyncio

    result = asyncio.run(merge_duplicates([_event("e1", "A")], object()))
    assert len(result.events) == 1 and not result.merged_groups


def test_the_listing_carries_every_id() -> None:
    text = _listing([_event("e1", "A"), _event("e2", "B")])
    assert "id=e1" in text and "id=e2" in text


def test_the_batch_is_small_enough_to_answer_in_one_call() -> None:
    assert 10 <= BATCH <= 60


def test_the_pass_runs_before_scoring() -> None:
    """Grading three copies of one story wastes calls and distorts the ranking."""
    from aidaily import __main__ as entry

    source = inspect.getsource(entry)
    assert source.index("merge_duplicates") < source.index("score_events(")


def test_batches_run_concurrently() -> None:
    """Ten batches at 0.5s each must not take five seconds."""
    import asyncio
    import time

    from aidaily.merge_llm import merge_duplicates

    class Slow:
        async def complete_json(self, messages, **kw):
            await asyncio.sleep(0.4)
            return {"groups": []}

    events = [_event(f"e{i}", f"标题 {i}") for i in range(10)]

    async def run():
        start = time.monotonic()
        result = await merge_duplicates(events, Slow(), batch=2, timeout_s=10, concurrency=5)
        return result, time.monotonic() - start

    result, elapsed = asyncio.run(run())
    assert result.calls == 5
    assert elapsed < 1.8, f"{elapsed:.2f}s for five 0.4s batches is sequential"


def test_a_slow_provider_costs_the_merge_not_the_issue() -> None:
    """Measured 2026-10-24: the first run spent over an hour here."""
    import asyncio
    import time

    from aidaily.merge_llm import merge_duplicates

    class Hanging:
        async def complete_json(self, messages, **kw):
            await asyncio.sleep(60)

    events = [_event(f"e{i}", f"标题 {i}") for i in range(6)]

    async def run():
        start = time.monotonic()
        result = await merge_duplicates(events, Hanging(), batch=2, timeout_s=1.0)
        return result, time.monotonic() - start

    result, elapsed = asyncio.run(run())
    assert elapsed < 5.0, f"{elapsed:.2f}s exceeds the deadline"
    assert result.failed
    assert len(result.events) == len(events), "a timeout must not drop events"


def test_the_deadline_is_shorter_than_a_publish_step() -> None:
    """The whole pass must fit comfortably inside the job timeout."""
    from aidaily.merge_llm import MERGE_TIMEOUT_SECONDS

    assert 30 <= MERGE_TIMEOUT_SECONDS <= 600


def test_concurrency_is_bounded() -> None:
    """The relay pool rotates keys per call; a wide fan-out would burn them all at once."""
    from aidaily.merge_llm import MERGE_CONCURRENCY

    assert 1 <= MERGE_CONCURRENCY <= 8


def test_merging_updates_the_evidence_level() -> None:
    """The count and the label must move together.

    Measured 2026-10-24: one event carried `single_source` after a merge grew its sources to
    two, and `factcheck` blocked the whole issue three times
    (`publish failed with exit code 2 after 3 attempts`).
    """
    keep = _event("e1", "A", sources=("s1",))
    assert keep.evidence_level == "single_source"
    _merge_into(keep, [_event("e2", "B", sources=("s2",))])
    assert keep.independent_source_count == 2
    assert keep.evidence_level == "multi_source"


def test_merging_two_feeds_from_one_outlet_stays_single() -> None:
    """The label follows the outlet count, not the feed count."""
    keep = _event("e1", "A", sources=("hnrss",))
    _merge_into(keep, [_event("e2", "B", sources=("hnrss",))])
    assert keep.independent_source_count == 1
    assert keep.evidence_level == "single_source"


def test_the_label_matches_the_count_after_a_merge_of_merges() -> None:
    keep = _event("e1", "A", sources=("s1",))
    _merge_into(keep, [_event("e2", "B", sources=("s2",))])
    _merge_into(keep, [_event("e3", "C", sources=("s3",))])
    assert keep.independent_source_count == 3
    assert keep.evidence_level == "multi_source"


def test_a_merged_event_passes_the_factcheck_invariant() -> None:
    """The rule the outage broke, asserted directly."""
    keep = _event("e1", "A", sources=("s1",))
    _merge_into(keep, [_event("e2", "B", sources=("s2",))])
    # `factcheck` rejects exactly this combination.
    assert not (keep.evidence_level == "single_source" and keep.independent_source_count > 1)


def test_the_scale_is_the_bucket_key_when_present() -> None:
    """A parameter count identifies a model more reliably than an entity string.

    Measured 2026-10-24: three headlines all saying 3万亿 still split across batches because
    each had a different first entity (kimi / moonshot / 开源) and the scale was only consulted
    when no entity was found.
    """
    from aidaily.merge_llm import _bucket

    events = [
        _event("e1", "Moonshot AI launches Kimi K3.1 Pro with 2.8T parameters"),
        _event("e2", "Kimi迭代3万亿参数大模型 首次推出Pro版本模型"),
        _event("e3", "3万亿级参数规模 全球最大开源AI模型上新"),
        _event("e4", "OpenAI CEO 最强内部模型暂难开源"),
    ]
    buckets = _bucket(events, 10)
    together = [b for b in buckets if len([e for e in b if "3" in e.title or "2.8" in e.title]) >= 3]
    assert together, "the three scale-3T headlines must share a batch"


def test_a_funding_amount_is_not_a_parameter_scale() -> None:
    """`300 亿美元融资` is money, not a model size."""
    from aidaily.merge_llm import _scale_key

    assert _scale_key("OpenAI 完成 300 亿美元融资") == ""
    assert _scale_key("Claude 5.5 发布") == ""


def test_the_same_scale_written_three_ways_normalises() -> None:
    from aidaily.merge_llm import _scale_key

    assert _scale_key("3万亿参数") == _scale_key("2.8T parameters") == _scale_key("2800B")


def test_a_small_model_is_not_bucketed_by_a_rounding_artefact() -> None:
    """70B rounds to 0T, which must not collide with a real multi-trillion model."""
    from aidaily.merge_llm import _scale_key

    assert _scale_key("某开源模型 70B 发布") == ""