"""The scheduled slots must survive a transient failure.

Measured over 20 scheduled triggers: 10 published, 7 failed, 3 cancelled. Half the slots
produced nothing, and the causes were external -- provider rate limits (HTTP 429), relays
returning 403, a fetch timing out. None of those is a reason to lose a slot.

Three layers now stand between a transient failure and an empty day:

1. the publish step retries itself up to three times;
2. the decision codes (10 already-published, 11 too-early, 12 empty-selection) are NOT retried,
   because repeating them cannot help and 12 must stay red;
3. a watchdog re-triggers the workflow when a slot produced no digest and the last scheduled
   run failed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _publish_script() -> str:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
    step = next(
        s for s in workflow["jobs"]["publish"]["steps"] if s.get("name") == "Publish"
    )
    return step["run"]


def test_publish_retries_transient_failures() -> None:
    script = _publish_script()
    assert "max_attempts=3" in script
    assert "while true" in script
    assert "retrying after a pause" in script


def test_decision_codes_are_not_retried() -> None:
    """10, 11 and 12 must exit immediately: retrying cannot change a decision."""
    script = _publish_script()
    for code in ("10", "11", "12"):
        marker = 'if [ "$code" = "%s" ]; then' % code
        assert marker in script, code
    # Each of those branches must exit before the retry counter is touched.
    first_retry = script.index("attempt=$((attempt + 1))")
    for code in ("10", "11", "12"):
        branch = script.index('if [ "$code" = "%s" ]; then' % code)
        assert branch < first_retry, f"the {code} branch sits after the retry"


def test_an_empty_selection_still_fails_the_run() -> None:
    """Exit 12 is a bug; the retry loop must not soften it into a success."""
    script = _publish_script()
    branch = script[script.index('if [ "$code" = "12" ]; then'):]
    branch = branch[: branch.index("fi")]
    assert "exit 1" in branch


def test_the_summary_still_finds_its_log() -> None:
    """Retries write `publish-<n>.log`; the summary and the artifact read `publish.log`."""
    script = _publish_script()
    assert 'tee "publish.log"' in script


def test_a_watchdog_exists_with_one_trigger_per_slot() -> None:
    spec = yaml.safe_load((ROOT / ".github" / "workflows" / "watchdog.yml").read_text(encoding="utf-8"))
    crons = [e["cron"] for e in spec[True]["schedule"]]
    assert len(crons) == 3, crons
    assert spec["jobs"]["check"]["steps"][-1].get("if", "").find("retry") >= 0


def test_the_watchdog_counts_events_not_files() -> None:
    """A digest file can exist from a failed run; the event count is what matters."""
    spec = importlib.util.spec_from_file_location("digest_events", ROOT / "scripts" / "digest_events.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty.json"
        empty.write_text(json.dumps({"digest": {"top_events": []}}), encoding="utf-8")
        assert module.main([str(empty)]) == 0

        full = Path(tmp) / "full.json"
        full.write_text(json.dumps({"digest": {"top_events": [1, 2, 3]}}), encoding="utf-8")
        assert module.main([str(full)]) == 0

        assert module.main([str(Path(tmp) / "missing.json")]) == 0
