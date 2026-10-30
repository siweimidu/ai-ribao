"""A publish is not proof that the last slot rebuilt anything.

The ledger records that *a* run published today. The evening slot can fail after the morning one
succeeded and nothing noticed: a publish exists, the archive exists, the event count is fine. The
issue is simply eight hours old.

`generated_at` is the only field that says when the content was produced, so after the last
deadline it has to be recent.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

# `scripts/` is not a package, so CI cannot import it by name. Load it by path.
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "missing_slots",
    Path(__file__).resolve().parents[2] / "scripts" / "missing_slots.py",
)
missing_slots = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(missing_slots)

#: A time after the last slot deadline, so all three slots count as due.
NOW_CN = datetime(2026, 10, 30, 22, 30)


def _run(monkeypatch, tmp_path, *, hours_ago: float, published: list[str]):
    stamp = (NOW_CN - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {"digest": {"generated_at": stamp, "top_events": [{} for _ in range(40)]}}
    archive = tmp_path / (NOW_CN.strftime("%Y-%m-%d") + ".json")
    archive.write_text(json.dumps(payload), encoding="utf-8")

    ledger = tmp_path / "runs.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps({"status": "published", "date": NOW_CN.strftime("%Y-%m-%d"), "at": at})
            for at in published
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(missing_slots, "ARCHIVE", tmp_path)
    monkeypatch.setattr(missing_slots, "LEDGER", ledger)
    monkeypatch.setattr(missing_slots, "REQUIRED_PAGES", ())
    monkeypatch.setattr(missing_slots, "beijing_now", lambda: NOW_CN)
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        missing_slots, "_output", lambda retry, reason: captured.update(retry=retry, reason=reason)
    )
    missing_slots.main()
    return captured


def _published() -> list[str]:
    day = NOW_CN.strftime("%Y-%m-%d")
    # UTC hours chosen so each publish maps to one slot after the +8 shift:
    # 22:00Z -> 06:00 CN (slot 5), 04:00Z -> 12:00 CN (slot 13), 12:00Z -> 20:00 CN (slot 21).
    return [f"{day}T22:00:00Z", f"{day}T04:00:00Z", f"{day}T12:00:00Z"]


def test_a_stale_archive_triggers_a_retry(monkeypatch, tmp_path) -> None:
    """The ledger says all three slots published; the content is 20 hours old."""
    got = _run(monkeypatch, tmp_path, hours_ago=20, published=_published())
    assert got["retry"] == "true"
    assert "没重建" in got["reason"]


def test_a_fresh_archive_does_not(monkeypatch, tmp_path) -> None:
    got = _run(monkeypatch, tmp_path, hours_ago=1, published=_published())
    assert got["retry"] == "false"