"""The external kick entry point must be safe to call at any frequency.

GitHub's `schedule` is best-effort: of the last 20 scheduled triggers on this repository, 10
published and 3 never created a job. Neither in-process retries nor the watchdog can help with a
trigger that never fired, so a third-party cron calls `slot-kick.yml` instead.

That makes the entry point reachable from the outside, which imposes two rules these tests pin:

1. it must be harmless to call repeatedly -- two kicks minutes apart must produce at most one
   run (measured: before the guard, a second kick started a second full run);
2. it must not be able to start anything but the daily workflow, so a leaked token is not a
   blanket "run any workflow" grant.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "slot-kick.yml"


def _spec() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(name_fragment: str) -> dict:
    for step in _spec()["jobs"]["kick"]["steps"]:
        if name_fragment in (step.get("name") or ""):
            return step
    raise AssertionError(f"no step matching {name_fragment!r}")


def test_it_is_reachable_by_repository_dispatch() -> None:
    spec = _spec()
    dispatch = spec[True]["repository_dispatch"]
    assert "slot-kick" in dispatch["types"]


def test_it_checks_for_an_in_flight_run_before_dispatching() -> None:
    """Two kicks minutes apart must not start two runs.

    The gate alone is not enough: it answers *yes* for a later slot of the same day by design,
    because the evening edition re-merges the morning's news. Measured before this guard, a
    second kick five minutes after the first started a second AI Daily run.
    """
    script = _step("still need publishing")["run"]
    assert "in_flight" in script
    assert "in_progress" in script and "queued" in script and "pending" in script
    # And the decision must come before the gate, so a busy repo skips the work entirely.
    assert script.index("in_flight") < script.index("aidaily gate")


def test_the_decision_codes_are_all_handled() -> None:
    script = _step("still need publishing")["run"]
    for code in ("0)", "10)", "11)"):
        assert code in script, code
    assert "go=true" in script and "go=false" in script


def test_it_dispatches_only_the_daily_workflow() -> None:
    """A leaked token must not be a blanket grant to run any workflow."""
    script = _step("Dispatch")["run"]
    assert "gh workflow run daily.yml" in script
    assert script.count("gh workflow run") == 1


def test_dispatch_is_gated_on_the_decision() -> None:
    step = _step("Dispatch")
    assert step.get("if") == "steps.decide.outputs.go == 'true'"


def test_the_documentation_exists() -> None:
    """The wiring steps live in the repo, not in a chat message."""
    doc = ROOT / "docs" / "EXTERNAL-CRON.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "event_type" in text and "slot-kick" in text
    assert "Contents: Read-only" in text, "the token scope must be stated"
