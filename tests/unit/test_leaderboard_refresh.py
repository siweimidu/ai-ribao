"""The leaderboard must refresh even when the day has already been published.

The gate exists so a day is published once. On a three-slot day that means the 04:00 build
publishes and the 12:00 and 20:00 builds skip everything -- and the leaderboard, which used to be
written only inside `write_site`, kept showing pre-dawn data until tomorrow.

The page is not part of the digest: it is fed by an outside service and should follow that
service, not our publish ledger. `refresh_site_page` exists so a workflow job can update one page
without building anything.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

from aidaily import leaderboard


def test_refresh_does_not_build_a_digest() -> None:
    """It must touch one file, not run collection or analysis."""
    source = inspect.getsource(leaderboard.refresh_site_page)
    for forbidden in ("collect(", "analyze(", "deliver_all", "pipeline"):
        assert forbidden not in source, f"{forbidden} must not run for a page refresh"


def test_refresh_reports_whether_it_changed_anything() -> None:
    """A no-op run must not rewrite the file and dirty the working tree."""
    source = inspect.getsource(leaderboard.refresh_site_page)
    assert "已是最新" in source
    assert "return False" in source


def test_refresh_survives_a_failed_fetch() -> None:
    """A network failure must leave the existing page alone, not blank it."""
    source = inspect.getsource(leaderboard.refresh_site_page)
    assert "取不到模型数据" in source


def test_the_snapshot_ttl_is_short_enough_for_a_three_slot_day() -> None:
    """Six hours means every slot sees data from this slot, not from before dawn."""
    signature = inspect.signature(leaderboard.load_models)
    default = signature.parameters["max_age_hours"].default
    assert default <= 8.0


def test_the_cli_command_exists() -> None:
    from aidaily.__main__ import build_parser

    parser = build_parser()
    # argparse stores subparsers under the `_subparsers` action; find it by type.
    choices = {}
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            choices = action.choices
            break
    assert "leaderboard" in choices


# ---------------------------------------------------------------------------------------------
# The run must not stay green while the page is frozen.
#
# From 2026-11-15 to 2026-11-21 upstream had reshaped its rows and every one was dropped. The
# command exited 0 each time, the page was byte-identical, nothing was committed, and the site
# served 2026-11-14 data for a week. "Already fresh" and "cannot be refreshed" have to end in
# different exit codes, and the threshold is a day because the page is meant to move daily.
# ---------------------------------------------------------------------------------------------


def _run_cli(monkeypatch, *, age_hours: float | None) -> int:
    from aidaily import __main__ as cli

    monkeypatch.setattr(leaderboard, "refresh_site_page", lambda root, **kw: (False, "页面已是最新"))
    monkeypatch.setattr(leaderboard, "snapshot_age_hours", lambda root: age_hours)
    args = cli.build_parser().parse_args(["leaderboard"])
    return cli.cmd_leaderboard(args)


def test_the_cli_stays_green_when_the_snapshot_is_from_this_cycle(monkeypatch) -> None:
    assert _run_cli(monkeypatch, age_hours=5.0) == 0


def test_a_single_missed_fetch_does_not_paint_the_run_red(monkeypatch) -> None:
    """One failed fetch leaves yesterday's page up; that is not an incident yet."""
    assert _run_cli(monkeypatch, age_hours=20.0) == 0


def test_the_cli_fails_once_a_whole_cycle_was_missed(monkeypatch, capsys) -> None:
    assert _run_cli(monkeypatch, age_hours=168.0) == 1
    err = capsys.readouterr().err
    assert "陈旧" in err and "168" in err


def test_the_cli_fails_when_there_is_no_snapshot_at_all(monkeypatch, capsys) -> None:
    assert _run_cli(monkeypatch, age_hours=None) == 1
    assert "快照" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------
# "Unchanged" must not be confused with "could not refresh".
#
# The age was read *before* the fetch attempt, so a healthy cycle that fetched fresh data and
# produced the same page reported "抓取没有成功" -- a lie the canary run on a real runner caught:
# it fetched 287 models in 1.4s and still printed that line. The age has to be read after.
# ---------------------------------------------------------------------------------------------


def _site(tmp_path, page_text: str):
    site = tmp_path / "data" / "digests" / "site"
    site.mkdir(parents=True)
    (site / "leaderboard.html").write_text(page_text, encoding="utf-8")
    return site


def test_a_fresh_fetch_that_changes_nothing_is_not_reported_as_a_failure(tmp_path, monkeypatch) -> None:
    snapshot = tmp_path / "data" / "state" / "leaderboard.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps({"fetched_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}),
        encoding="utf-8",
    )
    _site(tmp_path, "RENDERED")

    def fake_load_models(root, *, max_age_hours=6.0):
        snapshot.write_text(
            json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8"
        )
        return [leaderboard.Model(slug="a", name="A", creator="B")]

    monkeypatch.setattr(leaderboard, "load_models", fake_load_models)
    monkeypatch.setattr("aidaily.site.render_leaderboard", lambda *a, **kw: "RENDERED")

    # max_age_hours=0 forces the "the snapshot was older than the TTL" branch, which is exactly
    # where the wrong wording lived.
    changed, note = leaderboard.refresh_site_page(tmp_path, max_age_hours=0)

    assert changed is False
    assert note == "页面已是最新"


def test_a_fetch_that_never_landed_is_reported_as_a_failure(tmp_path, monkeypatch) -> None:
    snapshot = tmp_path / "data" / "state" / "leaderboard.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps({"fetched_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}),
        encoding="utf-8",
    )
    _site(tmp_path, "RENDERED")

    # The fetch failed: the snapshot is untouched, so it is still three days old afterwards.
    monkeypatch.setattr(
        leaderboard, "load_models", lambda root, **kw: [leaderboard.Model(slug="a", name="A", creator="B")]
    )
    monkeypatch.setattr("aidaily.site.render_leaderboard", lambda *a, **kw: "RENDERED")

    changed, note = leaderboard.refresh_site_page(tmp_path, max_age_hours=6)

    assert changed is False
    assert "抓取没有成功" in note and "72" in note

