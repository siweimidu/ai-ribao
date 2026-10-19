"""An empty digest is a failure, not a quiet day.

On 2026-10-19 the pipeline published zero stories while every job reported success. Selection
returned 0 of 220 events, the fact-check had nothing to object to, and the run went green with
an empty page. The gap was invisible until the reader opened the site.

Two things had to change, and these tests pin both:

* the run must exit non-zero when the pool had candidates and selection produced none;
* the workflow must treat that exit code as a failure rather than a no-op.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml

from aidaily.__main__ import EXIT_EMPTY_SELECTION, EXIT_TOO_EARLY

ROOT = Path(__file__).resolve().parents[2]


def test_the_empty_selection_exit_code_is_distinct() -> None:
    """It must not collide with "not yet" (11) or "already published" (10)."""
    assert EXIT_EMPTY_SELECTION not in (0, 10, EXIT_TOO_EARLY)
    assert EXIT_EMPTY_SELECTION == 12


def test_cmd_run_guards_an_empty_selection() -> None:
    from aidaily.__main__ import cmd_run

    source = inspect.getsource(cmd_run)
    assert "EXIT_EMPTY_SELECTION" in source, "an empty digest is not treated as a failure"
    assert "events_considered" in source, (
        "the guard must distinguish an empty pool from an empty selection"
    )


def test_the_workflow_fails_on_an_empty_selection() -> None:
    """Exit 12 must not be swallowed like 10 and 11 are."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
    publish = next(
        step for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Publish"
    )
    script = publish["run"]
    assert '"$code" = "12"' in script, "the workflow does not branch on exit 12"
    assert "empty selection" in script
    # And it must exit non-zero, unlike the 10/11 branches which exit 0.
    branch = script[script.index('"$code" = "12"'):]
    branch = branch[:branch.index("fi")]
    assert "exit 1" in branch, "the 12 branch must fail the step"
