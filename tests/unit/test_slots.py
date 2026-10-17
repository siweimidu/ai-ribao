"""The day is cut into as many slots as the schedule has collections.

## The regression this locks down

`gate` and `cmd_gate` both split the day at a hard-coded 13:00:

    slot = 0 if hour < 13 else 1

That was correct while there were two collections (07:00 / 19:00). When the schedule grew to
three (04:00 / 12:00 / 20:00) the expression kept returning 0 or 1, so the 20:00 run computed the
same slot index as the 12:00 run, was told "already published in this slot", and skipped
delivery. The evening's news never appeared.

Measured on 2026-10-17: the published issue's window closed at 06:38 UTC (14:38 Beijing), so the
entire afternoon -- including what the user calls the day's biggest release -- could not have been
in it.

The fix derives the index from `run.slots`, and these tests pin the arithmetic so the next
schedule change cannot quietly reintroduce a merge.
"""

from __future__ import annotations

import pytest

from aidaily.state import DEFAULT_SLOT_HOURS, _slot_index

THREE = (4, 12, 20)


@pytest.mark.parametrize(("hour", "expected"), [
    (4, 0), (5, 0), (11, 0),          # 04:00-11:59 belongs to the 04:00 collection
    (12, 1), (13, 1), (19, 1),        # 12:00-19:59 belongs to the 12:00 collection
    (20, 2), (23, 2),                 # 20:00-03:59 belongs to the 20:00 collection
    (0, 2), (3, 2),                   # after midnight is still the previous evening's tail
])
def test_three_slots_map_to_three_indices(hour: int, expected: int) -> None:
    assert _slot_index(hour, THREE) == expected


def test_each_collection_gets_its_own_index() -> None:
    """The exact bug: three collections must not produce two indices."""
    indices = {_slot_index(hour, THREE) for hour in (4, 12, 20)}
    assert indices == {0, 1, 2}, f"三个时段必须得到三个不同序号，实际 {indices}"


def test_two_slots_still_work() -> None:
    """The old schedule must keep the old behaviour -- this is a generalisation, not a swap."""
    assert _slot_index(7, (7, 19)) == 0
    assert _slot_index(19, (7, 19)) == 1
    assert _slot_index(2, (7, 19)) == 1


def test_default_matches_the_shipped_schedule() -> None:
    assert DEFAULT_SLOT_HOURS == (4, 12, 20)
