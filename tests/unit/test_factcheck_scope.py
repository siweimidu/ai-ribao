"""One bad input must not cost the day.

On 2026-10-19 the digest for that date was never published. The cause was four AllenAI entries
whose feed dated them 2026-10-31 -- a placeholder, twelve days ahead. They raised 27
`future_date` violations, `check.ok` was False, and the whole issue was discarded: 220 good
events lost because of four bad ones.

These tests pin the split between violations that belong to one event and violations that
concern the digest as a whole.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aidaily.factcheck import FactCheckReport, Violation

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


def test_a_future_date_drops_that_event_only() -> None:
    report = FactCheckReport()
    report.violations.append(Violation("future_date", "发布日期在未来：2026-10-31", "e1"))
    report.violations.append(Violation("future_date", "发布日期在未来：2026-10-31", "e2"))

    assert report.offending_event_ids == {"e1", "e2"}
    assert report.blocking == []
    assert report.ok_to_publish, "two bad events must not stop the other 218"


def test_a_digest_wide_violation_still_blocks() -> None:
    """Shape errors are about the whole issue and must keep failing the run."""
    report = FactCheckReport()
    report.violations.append(Violation("bad_shape", "模型输出不是对象"))

    assert report.blocking != []
    assert not report.ok_to_publish


def test_event_scoped_kinds_are_the_ones_with_an_event_id() -> None:
    """The split must be explicit, not inferred from whether an id happens to be present."""
    for kind in (
        "event_without_url",
        "fabricated_url",
        "unknown_member",
        "future_date",
        "fabricated_date",
        "date_order",
        "event_without_source",
    ):
        assert kind in FactCheckReport.EVENT_SCOPED, kind
    for kind in ("bad_shape", "missing_bucket", "bad_bucket", "url_in_text", "no_coverage"):
        assert kind not in FactCheckReport.EVENT_SCOPED, kind
