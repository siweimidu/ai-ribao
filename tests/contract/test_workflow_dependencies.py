"""A skipped job must not turn into a red workflow.

Measured 2026-10-24 08:35: the gate decided today was already published, so `collect` and
`publish` were skipped. `leaderboard` succeeded, `deploy` ran because its condition accepted a
successful `leaderboard`, and `deploy-pages` failed:

    Error: No artifacts named "github-pages" were found for this workflow run.

The artifact is uploaded inside `publish`. A job that consumes it must depend on `publish`
succeeding, not on some other job that happens to be in the same workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")


def _job(name: str) -> str:
    """The text of one job, from its key to the next top-level job key."""
    start = WORKFLOW.index(chr(10) + "  " + name + ":" + chr(10))
    rest = WORKFLOW[start + 1:]
    nxt = re.search(r"(?m)^  [a-z-]+:$", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 1]


def _condition_of(job_text: str) -> str:
    """Everything under a job's `if:`, including a `>-` block."""
    match = re.search(r"(?m)^    if:s*(.*)$", job_text)
    if not match:
        return ""
    first = match.group(1).strip()
    if first not in ("", ">-", ">", "|", "|-"):
        return first
    # Multi-line: collect indented lines until one is not deeper than the `if:` key.
    rest = job_text[match.end():].splitlines()
    parts = []
    for line in rest:
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= 4:
            break
        parts.append(line.strip())
    return " ".join(parts)

def test_deploy_requires_publish_to_have_succeeded() -> None:
    """Nothing else uploads the Pages artifact, so nothing else may trigger a deploy."""
    deploy = _job("deploy")
    # The condition is a `>-` block now, so read every line between `if:` and the next
    # top-level key rather than assuming one line.
    cond = _condition_of(deploy)
    assert cond, "deploy must have an explicit condition"
    assert "needs.publish.result == " + chr(39) + "success" + chr(39) in cond


def test_the_artifact_producer_is_the_only_trigger() -> None:
    """If the condition mentions another job, a skipped publish can still fire it."""
    deploy = _job("deploy")
    cond = _condition_of(deploy)
    referenced = set(re.findall(r"needs\.([a-z]+)\.", cond))
    assert referenced == {"publish"}, f"deploy condition references {referenced}"


def test_publish_uploads_the_pages_artifact() -> None:
    """The invariant the condition above rests on."""
    assert "upload-pages-artifact" in _job("publish")


def test_publish_is_still_gated_on_the_ledger() -> None:
    """The gate exists so a day is published once; that must not have been relaxed."""
    publish = _job("publish")
    assert "needs.gate.outputs.run == 'true'" in publish


def test_leaderboard_runs_even_when_the_gate_says_done() -> None:
    """The leaderboard is not part of the digest and must still refresh."""
    leaderboard = _job("leaderboard")
    assert "always()" in leaderboard