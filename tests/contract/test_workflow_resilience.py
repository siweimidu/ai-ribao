"""The scheduled workflow must not report a correct decision as a failure.

Nine of forty AI Daily runs were red. Grouped by cause:

* seven died on `ModuleNotFoundError: No module named 'bs4'` in the gate step -- a missing
  runtime dependency, fixed by promoting `beautifulsoup4` to a core dependency;
* one was a publish that correctly returned exit 11 ("too early") while the gate step only
  understood exit codes 0 and 10, so it printed `::error::` and exited non-zero;
* two were `git push` conflicts in the commit step, where the retry loop aborted the rebase on
  the first conflict, so all five attempts failed identically.

This module pins the parts that can be checked without a runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "daily.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def _script(steps: list[dict], name: str) -> str:
    for step in steps:
        if step.get("name") == name:
            return step.get("run") or ""
    raise AssertionError(f"no step named {name!r}")


def test_the_gate_treats_too_early_as_a_no_op(workflow: dict) -> None:
    """Exit 11 means "not yet", and the gate must say so rather than fail the run.

    A scheduled trigger that arrives before the collection window used to turn the whole
    workflow red on a decision the code made correctly.
    """
    script = _script(_steps(workflow, "gate"), "Decide whether today still needs publishing")
    assert "11)" in script or "11)" in script.replace(" ", ""), "gate does not branch on exit 11"
    # It must set run=false, not just print a notice: the collect job is gated on that output.
    assert 'echo "run=false"' in script


def test_the_publish_step_treats_too_early_as_a_no_op(workflow: dict) -> None:
    script = _script(_steps(workflow, "publish"), "Publish")
    assert '"$code" = "11"' in script
    assert "::notice::too early" in script


def test_the_commit_step_does_not_abort_on_a_generated_file_conflict(workflow: dict) -> None:
    """Two runs generating the same files is not a disagreement to resolve by hand.

    The loop used to `git rebase` and `exit 1` on the first conflict, so all five attempts
    failed the same way. It must prefer the newest generation instead.
    """
    script = _script(_steps(workflow, "publish"), "Commit state and digests")
    assert "-X theirs" in script, "rebase must prefer this run's generated output"
    assert "-X ours" in script, "merge fallback must prefer this run's generated output"
    assert "git rebase --abort 2>/dev/null || true" in script, "an aborted rebase must not fail the step"


def test_beautifulsoup_is_a_runtime_dependency() -> None:
    """`aidaily.collect` imports bs4, and the gate job imports collect. A fetchers-only extra
    killed seven scheduled runs before anyone saw a digest."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    core = " ".join(data["project"]["dependencies"])
    assert "beautifulsoup4" in core, "bs4 must be a core dependency, not an extra"


def test_every_job_that_imports_collect_installs_the_parser_extras(workflow: dict) -> None:
    """Gate, collect and publish all reach the fetcher layer, so all three need the extras."""
    for job in ("gate", "collect", "publish"):
        script = " ".join(s.get("run") or "" for s in _steps(workflow, job))
        assert "pip install" in script, f"{job} installs nothing"
        assert "[fetchers" in script, f"{job} installs without the fetchers extra"

def test_each_job_is_defined_once(workflow: dict) -> None:
    """A duplicated job key makes GitHub reject the whole file.

    After an edit inserted a block at the wrong offset, `publish:` appeared twice. PyYAML keeps
    the last definition and reports no error, so every Python test still passed while the
    workflow failed to load with zero jobs -- the run page said only "this run likely failed
    because of a workflow file issue".
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    for job in workflow["jobs"]:
        occurrences = sum(1 for ln in text.splitlines() if ln == f"  {job}:")
        assert occurrences == 1, f"{job}: defined {occurrences} times"


def test_no_job_reads_outputs_from_a_needs_it_did_not_declare(workflow: dict) -> None:
    """`needs.gate` from a job declaring `needs: publish` is an invalid expression.

    GitHub rejects the *file* for it, not just the step. This is the second half of the same
    breakage and it survived the duplicate-key fix.
    """
    import re

    for name, spec in workflow["jobs"].items():
        needs = spec.get("needs") or []
        declared = {needs} if isinstance(needs, str) else set(needs)
        body = yaml.safe_dump(spec)
        for referenced in set(re.findall(r"needs\.([A-Za-z0-9_-]+)\.", body)):
            assert referenced in declared, (
                f"job {name!r} reads needs.{referenced} but declares needs={sorted(declared)}"
            )
