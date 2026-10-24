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


def test_deploy_requires_publish_to_have_succeeded() -> None:
    """Nothing else uploads the Pages artifact, so nothing else may trigger a deploy."""
    deploy = _job("deploy")
    cond = re.search(r"(?m)^    if:s*(.+)$", deploy)
    assert cond, "deploy must have an explicit condition"
    assert "needs.publish.result == 'success'" in cond.group(1)


def test_the_artifact_producer_is_the_only_trigger() -> None:
    """If the condition mentions another job, a skipped publish can still fire it."""
    deploy = _job("deploy")
    cond = re.search(r"(?m)^    if:s*(.+)$", deploy).group(1)
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