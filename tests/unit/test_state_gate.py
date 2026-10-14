"""Idempotency gate.

The gate exists because GitHub Actions fires the schedule several times each morning and
may delay or drop any of them: the first trigger that reaches "published" wins and every
later one must become a cheap no-op.

The case these tests cover is the one that shipped. The ledger records "published" per
*date*, but a later trigger on the same day builds a **different** digest — new items
arrived, and 219 events became 223. The gate said "already published, skip delivery", so
the site kept the 219-event page while its own archived JSON said 223. The published page
contradicted its own data and nothing noticed.
"""

from __future__ import annotations

import json

from aidaily.state import (
    EXIT_ALREADY_PUBLISHED,
    RunRecord,
    append_record,
    gate,
    read_ledger,
)


def published(tmp_path, date: str, digest_id: str, **channels: str):
    path = tmp_path / "runs.jsonl"
    append_record(
        RunRecord(
            date=date, status="published", at="2026-10-14T02:40:40+00:00",
            digest_id=digest_id,
            channels=channels or {"rss": "ok", "pages": "ok"},
        ),
        path,
    )
    return path


# =============================== the day is empty =================================
def test_a_fresh_day_publishes(tmp_path) -> None:
    should, reason, done = gate("2026-10-14", tmp_path / "runs.jsonl")
    assert should
    assert "尚未发布" in reason
    assert done == {}


# =============================== a repeat of the same content =====================
def test_the_same_digest_is_not_republished(tmp_path) -> None:
    """This is what the gate is for: a later schedule trigger must cost nothing."""
    path = published(tmp_path, "2026-10-14", "2026-10-14-219")

    should, reason, done = gate("2026-10-14", path, digest_id="2026-10-14-219")
    assert not should, "an identical repeat must be a no-op"
    assert "已发布" in reason
    assert done == {"rss": "ok", "pages": "ok"}, "the caller needs the channel states"


# =============================== changed content ==================================
def test_a_changed_digest_is_republished(tmp_path) -> None:
    """The bug: 219 events were published, then the same day produced 223."""
    path = published(tmp_path, "2026-10-14", "2026-10-14-219")

    should, reason, done = gate("2026-10-14", path, digest_id="2026-10-14-223")
    assert should, "the live page would otherwise describe content that is not the archive"
    assert "内容不同" in reason
    assert "2026-10-14-219" in reason and "2026-10-14-223" in reason
    assert done == {}, "everything must be re-sent, not just the missing channels"


def test_a_missing_digest_id_keeps_the_old_behaviour(tmp_path) -> None:
    """`cmd_gate` runs before collection, so it has no digest id and must stay cheap.

    That is the correct trade: exiting early saves an entire run, and the `run` command
    re-checks with a real id once the digest exists.
    """
    path = published(tmp_path, "2026-10-14", "2026-10-14-219")

    should, reason, _ = gate("2026-10-14", path)
    assert not should
    assert "已发布" in reason


def test_an_older_ledger_line_without_a_digest_id_still_gates(tmp_path) -> None:
    """Ledger lines written before `digest_id` existed must not crash the gate, and must
    not be treated as a mismatch — that would re-send the digest on every trigger."""
    path = tmp_path / "runs.jsonl"
    path.write_text(
        json.dumps({"date": "2026-10-14", "status": "published", "at": "x", "channels": {"rss": "ok"}}) + "\n",
        encoding="utf-8",
    )

    should, reason, done = gate("2026-10-14", path, digest_id="2026-10-14-223")
    assert not should, "no recorded id means nothing to compare against"
    assert done == {"rss": "ok"}


def test_an_empty_recorded_digest_id_is_not_a_mismatch(tmp_path) -> None:
    path = published(tmp_path, "2026-10-14", "")

    should, _, _ = gate("2026-10-14", path, digest_id="2026-10-14-223")
    assert not should


# =============================== partial runs =====================================
def test_a_partial_run_resumes_only_the_missing_channels(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    append_record(
        RunRecord(
            date="2026-10-14", status="partial", at="x", digest_id="2026-10-14-219",
            channels={"rss": "ok", "pages": "failed", "email": "ok"},
        ),
        path,
    )

    should, reason, done = gate("2026-10-14", path, digest_id="2026-10-14-219")
    assert should
    assert "补发" in reason
    assert done == {"rss": "ok", "email": "ok"}, "pages is missing, so it is retried"


def test_a_failed_run_retries_everything(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    append_record(
        RunRecord(date="2026-10-14", status="failed", at="x", channels={"rss": "failed"}),
        path,
    )

    should, reason, done = gate("2026-10-14", path, digest_id="2026-10-14-219")
    assert should
    assert done == {}
    assert "重试" in reason


# =============================== ledger robustness ================================
def test_the_latest_record_wins(tmp_path) -> None:
    """A day can have several records; only the most recent describes the current state."""
    path = published(tmp_path, "2026-10-14", "2026-10-14-200")
    append_record(
        RunRecord(date="2026-10-14", status="published", at="later",
                  digest_id="2026-10-14-219", channels={"rss": "ok"}),
        path,
    )

    should, _, done = gate("2026-10-14", path, digest_id="2026-10-14-219")
    assert not should, "the newest record matches, so this is a repeat"
    assert done == {"rss": "ok"}


def test_a_corrupt_line_does_not_make_the_day_unrecoverable(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    path.write_text(
        "not json at all\n"
        + json.dumps({"date": "2026-10-14", "status": "published", "at": "x",
                      "digest_id": "2026-10-14-219", "channels": {}}) + "\n",
        encoding="utf-8",
    )

    records = read_ledger(path)
    assert len(records) == 1, "the corrupt line is skipped, not fatal"
    should, _, _ = gate("2026-10-14", path, digest_id="2026-10-14-223")
    assert should


def test_the_exit_code_is_distinct_from_failure() -> None:
    """"Nothing to do" must never be mistaken for "something broke"."""
    assert EXIT_ALREADY_PUBLISHED == 10
    assert EXIT_ALREADY_PUBLISHED != 1
