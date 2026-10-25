"""The external scheduler must read the checker's marker, not guess.

## Why an external scheduler

GitHub Actions `schedule` is best-effort: the docs say events may be delayed under load and that
queued jobs may be dropped. Measured over the week to 2026-10-25, `daily.yml` fired 2 or 3
times on days configured for 3, and the 12:00 Beijing slot produced no run at all on 2026-10-21.

Two defences already live inside GitHub -- six triggers per slot and a two-hourly watchdog --
but both sit on the same scheduler that is dropping events. A clock outside GitHub is the only
thing that recovers from a window GitHub never opened.

## What these tests pin down

The local task does not re-implement the slot rules. It calls `scripts/missing_slots.py` and
reads its `retry=` marker. If that contract breaks -- the marker disappears, or a silent exit
looks like "no retry" -- the external scheduler becomes a no-op that reports success, which is
the worst possible failure: it looks like coverage and is not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "missing_slots.py"
TRIGGER = ROOT / "scripts" / "external_trigger.ps1"
REGISTER = ROOT / "scripts" / "register_task.ps1"


def _run_checker() -> str:
    # errors="replace": the checker prints Chinese, and on a cp936 console the captured bytes
    # are not always UTF-8. A decoding crash would make this test about the console rather
    # than about the marker.
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={"GITHUB_REPOSITORY": "siweimidu/ai-ribao", "PYTHONIOENCODING": "utf-8"},
        cwd=str(ROOT),
    )
    return (result.stdout or "") + (result.stderr or "")


def test_the_checker_always_prints_a_retry_marker() -> None:
    """A silent exit is indistinguishable from a crash before deciding."""
    out = _run_checker()
    assert "retry=true" in out or "retry=false" in out, out[-400:]


def test_the_checker_always_prints_a_reason() -> None:
    out = _run_checker()
    assert "reason=" in out, out[-400:]


def test_the_trigger_script_reads_the_marker() -> None:
    """It must not re-implement the slot rules -- only one copy may exist."""
    text = TRIGGER.read_text(encoding="utf-8")
    assert "missing_slots.py" in text
    assert "retry=" in text


def test_the_trigger_script_does_not_hardcode_slot_hours() -> None:
    """A second copy of the slot list would be the one nobody tests."""
    #
    # The block comment at the top legitimately quotes the slot hours when explaining why a
    # local clock exists. What must not appear is a *rule*: a comparison or a schedule
    # entry. Check the executable lines only.
    text = TRIGGER.read_text(encoding="utf-8")
    lines = text.splitlines()
    code = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<#"):
            in_block = True
            continue
        if in_block:
            if stripped.endswith("#>"):
                in_block = False
            continue
        if stripped.startswith("#"):
            continue
        code.append(line)
    body = chr(10).join(code)
    for marker in ("04:00", "12:00", "20:00", "-At "):
        assert marker not in body, marker

def test_the_register_script_creates_three_triggers() -> None:
    text = REGISTER.read_text(encoding="utf-8")
    assert text.count("New-ScheduledTaskTrigger") == 3


def test_the_task_survives_a_sleeping_machine() -> None:
    """`StartWhenAvailable` is the whole point: a missed window still runs on wake."""
    text = REGISTER.read_text(encoding="utf-8")
    assert "StartWhenAvailable" in text


def test_the_trigger_dispatches_without_forcing() -> None:
    """`-f force=true` would bypass the idempotency gate and republish a finished day."""
    text = TRIGGER.read_text(encoding="utf-8")
    assert "force=false" in text
    assert "force=true" not in text