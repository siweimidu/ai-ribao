"""Idempotency ledger and delivery channels.

The two behaviours worth guarding: a scheduled trigger that has nothing to do must be
cheap and unambiguous, and one failing channel must not take the others down with it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from _async import async_test
from aidaily.config import load_config
from aidaily.models import Digest, Event, SourceCoverage
from aidaily.publish import DeliveryReport, DeliveryResult, deliver_all, write_rss, write_site
from aidaily.state import RunRecord, append_record, gate, read_ledger

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


def make_event(**kw) -> Event:
    base = dict(
        event_id="e1", title="A story & <tag>", member_item_ids=["i1"], primary_item_id="i1",
        source_ids=["rss:test"], all_urls=["https://example.com/a?x=1&y=2"],
        independent_source_count=1, first_seen_at=NOW, last_updated_at=NOW,
        published_range=(NOW, NOW), evidence_level="single_source",
    )
    base.update(kw)
    return Event(**base)


def make_digest(**kw) -> Digest:
    base = dict(
        date="2026-10-14", kind="deep", generated_at=NOW,
        window_start=NOW, window_end=NOW, top_events=[make_event()],
        source_coverage=SourceCoverage(total=10, active=3), counts={"events": 1},
    )
    base.update(kw)
    return Digest(**base)


# =============================== ledger and gate =================================
def test_gate_publishes_when_no_record(tmp_path: Path) -> None:
    should, reason, done = gate("2026-10-14", tmp_path / "runs.jsonl")
    assert should and "尚未发布" in reason and done == {}


def test_gate_skips_after_a_successful_publish(tmp_path: Path) -> None:
    ledger = tmp_path / "runs.jsonl"
    append_record(RunRecord(date="2026-10-14", status="published", at="t0"), ledger)
    should, reason, done = gate("2026-10-14", ledger)

    assert not should
    assert "已发布" in reason


def test_gate_resumes_a_partial_run(tmp_path: Path) -> None:
    """Re-sending a delivered email is worse than not sending it: the reader cannot tell
    a duplicate from a correction."""
    ledger = tmp_path / "runs.jsonl"
    append_record(
        RunRecord(date="2026-10-14", status="partial", at="t0",
                  channels={"rss": "ok", "email": "failed", "telegram": "ok"}),
        ledger,
    )
    should, reason, done = gate("2026-10-14", ledger)

    assert should and "部分发布" in reason
    assert done == {"rss": "ok", "telegram": "ok"}, "only the missing channel should be retried"


def test_gate_is_per_day(tmp_path: Path) -> None:
    ledger = tmp_path / "runs.jsonl"
    append_record(RunRecord(date="2026-10-13", status="published", at="t0"), ledger)
    assert gate("2026-10-14", ledger)[0] is True


def test_corrupt_ledger_line_does_not_lock_the_day(tmp_path: Path) -> None:
    """A truncated write must not make a day permanently unpublishable."""
    ledger = tmp_path / "runs.jsonl"
    ledger.write_text(
        '{"date": "2026-10-14", "status": "published", "at": "t0"}\n{not json\n',
        encoding="utf-8",
    )
    records = read_ledger(ledger)
    assert len(records) == 1
    assert gate("2026-10-14", ledger)[0] is False


# =============================== local artefacts =================================
def test_rss_is_well_formed_and_escapes(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    result = write_rss(make_digest(), tmp_path, site_url="https://site.example")
    assert result.ok

    root = ET.parse(tmp_path / "feed" / "zh.xml").getroot()
    item = root.find("./channel/item")
    assert item is not None
    assert item.findtext("title") == "A story & <tag>"
    assert item.findtext("guid").endswith("e1")
    assert "example.com" in (item.findtext("description") or "")


def test_site_writes_a_day_page_and_an_index(tmp_path: Path) -> None:
    write_site(make_digest(), "# deep markdown", tmp_path, site_url="https://site.example")
    write_site(make_digest(date="2026-10-13"), "# older", tmp_path, site_url="https://site.example")

    assert (tmp_path / "site" / "2026-10-14.html").exists()
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "2026-10-14.html" in index and "2026-10-13.html" in index


# =============================== delivery ========================================
def _cfg():
    return load_config(env={})


@async_test
async def test_missing_credentials_skip_rather_than_fail(tmp_path: Path) -> None:
    """A fresh clone must be able to go green without every channel provisioned."""
    report = await deliver_all(
        make_digest(), "# brief", "# deep", _cfg(), {}, tmp_path, site_url="https://s.example"
    )

    assert report.all_ok, report.summary()
    assert report.channels["rss"] == "ok"
    assert report.channels["pages"] == "ok"
    assert report.channels["email"] == "skipped"
    assert report.channels["telegram"] == "skipped"


@async_test
async def test_unconfigured_channel_is_recorded_as_skipped_not_ok(tmp_path: Path) -> None:
    """Regression: the ledger recorded a credential-less skip as "ok".

    A skipped channel carries ok=True, and `channels` checked `ok` before `skipped`. The
    effect was that adding SMTP credentials later in the day would not resend the mail,
    because the ledger claimed it had already been sent.
    """
    report = await deliver_all(
        make_digest(), "# brief", "# deep", _cfg(), {}, tmp_path, site_url="https://s.example"
    )
    assert report.channels["email"] == "skipped", report.channels
    assert report.channels["email"] != "ok"


@async_test
async def test_already_done_channels_are_not_resent(tmp_path: Path) -> None:
    report = await deliver_all(
        make_digest(), "# brief", "# deep", _cfg(),
        {"SMTP_HOST": "smtp.example", "SMTP_PASSWORD": "x", "MAIL_TO": "a@b.c"},
        tmp_path, site_url="https://s.example", already_done={"email": "ok"},
    )

    email = next(r for r in report.results if r.channel == "email")
    assert email.skipped and "already sent" in email.detail


@async_test
async def test_one_failing_channel_does_not_stop_the_others(tmp_path: Path) -> None:
    """A dead Telegram endpoint must not prevent the RSS feed being written."""
    report = await deliver_all(
        make_digest(), "# brief", "# deep", _cfg(),
        {
            "SMTP_HOST": "smtp.example", "SMTP_PASSWORD": "x", "MAIL_TO": "a@b.c",
            "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c",
            "N8N_WEBHOOK_URL": "https://n8n.example/hook",
        },
        tmp_path, site_url="https://s.example",
    )

    assert report.channels["rss"] == "ok"
    assert report.channels["pages"] == "ok"
    # Email fails inside smtplib (host does not resolve), Telegram and n8n are attempted
    # against a transport we do not control. What matters is that rss/pages still ran.
    assert not report.all_ok
    assert report.summary()["failures"]


@async_test
async def test_disabled_channels_are_reported_as_skipped(tmp_path: Path) -> None:
    cfg = _cfg()
    cfg = cfg.model_copy(update={"delivery": cfg.delivery.model_copy(update={"email": False, "n8n": False})})
    report = await deliver_all(make_digest(), "# b", "# d", cfg, {}, tmp_path, site_url="https://s.example")

    by_name = {r.channel: r for r in report.results}
    assert by_name["email"].skipped and "disabled" in by_name["email"].detail


def test_delivery_report_counts_skips_as_non_failures() -> None:
    report = DeliveryReport(results=[
        DeliveryResult("rss", True, "ok"),
        DeliveryResult("email", True, "skipped", skipped=True),
        DeliveryResult("n8n", False, "boom"),
    ])
    assert report.channels == {"rss": "ok", "email": "skipped", "n8n": "failed"}
    assert not report.all_ok
    assert report.summary()["failures"] == [{"channel": "n8n", "detail": "boom"}]
