"""`deploy` must not run when `publish` produced no Pages artifact.

## The failure

Measured 2026-10-24 08:35, one of five red scheduled runs that week:

    gate        success
    leaderboard success
    collect     skipped
    publish     skipped
    deploy      failure   <- No artifacts named "github-pages" were found

The gate had decided today was already published, so `collect` and `publish` were skipped.
`deploy` still ran, because `needs.publish.result` compares equal to `'success'` for a
**skipped** job -- the job did not fail, so its result is success. Deploy then found zero
artifacts and turned an "already done" run red.

## The fix

`publish` now exports a `pages` output that is set only by the upload step, and `deploy` keys
on that. `always()` comes first because GitHub's implicit success-check on `needs`
short-circuits the whole expression when anything upstream was skipped, and the condition would
never be evaluated.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))


def _condition() -> str:
    return str(WORKFLOW["jobs"]["deploy"].get("if") or "")


def test_deploy_is_gated_on_the_artifact_not_the_job_result() -> None:
    """`needs.X.result == 'success'` is true for a skipped job; the artifact is not."""
    condition = _condition()
    assert "needs.publish.outputs.pages" in condition


def test_deploy_keeps_the_always_prefix() -> None:
    """Without it the implicit needs-success check short-circuits the expression."""
    assert _condition().strip().startswith("always()")


def test_publish_declares_the_pages_output() -> None:
    outputs = WORKFLOW["jobs"]["publish"].get("outputs") or {}
    assert "pages" in outputs
    assert "steps.upload-pages" in str(outputs["pages"])


def test_the_upload_step_has_the_id_the_output_refers_to() -> None:
    steps = WORKFLOW["jobs"]["publish"]["steps"]
    ids = {s.get("id") for s in steps if s.get("id")}
    assert "upload-pages" in ids


def test_the_upload_step_uses_the_pages_action() -> None:
    step = next(s for s in WORKFLOW["jobs"]["publish"]["steps"] if s.get("id") == "upload-pages")
    assert "upload-pages-artifact" in str(step.get("uses"))


def test_the_condition_references_no_other_job() -> None:
    """Only `publish` produces the artifact; naming another job re-introduces the bug."""
    condition = _condition()
    for job in ("leaderboard", "collect", "gate"):
        assert f"needs.{job}" not in condition, job