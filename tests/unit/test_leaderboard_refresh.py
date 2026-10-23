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