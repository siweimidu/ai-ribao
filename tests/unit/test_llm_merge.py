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