"""The watchdog must notice a broken site, not only a missing digest.

A digest that published but lost a page is still a broken site: the rail links every required
page from every issue, so a missing file is a 404 behind a navigation item that nobody notices
until a reader clicks it.

`leaderboard.html` matters twice over -- it is the only page fed by an outside service, so a
*missing* file means the build step did not run (a failed fetch still renders the page with an
explanation), and a *stale* one means the module stopped refreshing while everything else kept
working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from missing_slots import (  # noqa: E402
    MIN_PAGE_BYTES,
    REQUIRED_PAGES,
    leaderboard_problem,
    page_problems,
)


def _fill(directory: Path, *, skip: str = "", size: int = 20_000) -> None:
    for name in REQUIRED_PAGES:
        if name == skip:
            continue
        (directory / name).write_text("x" * size, encoding="utf-8")


def test_the_four_pages_the_rail_links_are_required() -> None:
    assert set(REQUIRED_PAGES) == {"index.html", "tibo.html", "sources.html", "leaderboard.html"}


def test_a_missing_page_is_reported(tmp_path) -> None:
    _fill(tmp_path, skip="leaderboard.html")
    problems = page_problems(tmp_path)
    assert len(problems) == 1
    assert "leaderboard.html" in problems[0]


def test_a_stub_page_is_reported(tmp_path) -> None:
    """A few hundred bytes is an error page, not a rendered issue."""
    _fill(tmp_path)
    (tmp_path / "leaderboard.html").write_text("stub", encoding="utf-8")
    problems = page_problems(tmp_path)
    assert problems and "字节" in problems[0]


def test_an_empty_directory_reports_all_four(tmp_path) -> None:
    assert len(page_problems(tmp_path)) == len(REQUIRED_PAGES)


def test_a_complete_site_has_no_problems(tmp_path) -> None:
    _fill(tmp_path)
    assert page_problems(tmp_path) == []


def test_a_stale_leaderboard_is_reported(tmp_path) -> None:
    (tmp_path / "leaderboard.html").write_text("抓取于 2020-01-01。", encoding="utf-8")
    problem = leaderboard_problem(tmp_path)
    assert problem and "天前" in problem


def test_a_leaderboard_without_a_date_is_reported(tmp_path) -> None:
    (tmp_path / "leaderboard.html").write_text("no date", encoding="utf-8")
    assert leaderboard_problem(tmp_path) == "模型榜没有抓取日期"


def test_a_missing_leaderboard_is_left_to_page_problems(tmp_path) -> None:
    """Two checks reporting the same absence would send two retries."""
    assert leaderboard_problem(tmp_path) is None


def test_the_size_floor_is_above_an_error_page() -> None:
    assert MIN_PAGE_BYTES >= 4000