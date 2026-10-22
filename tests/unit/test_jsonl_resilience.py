"""A truncated JSONL line must not cost the whole run.

Measured on 2026-10-22: a collect job wrote `data/raw/items.jsonl` and was cut off mid-line,
leaving `Invalid JSON: EOF while parsing a string at column 2067`. `read_items_jsonl` raised,
publish failed, the workflow retried three times, and all three failed the same way -- the day
produced no issue at all, over one damaged line out of several thousand.

A partially written file is an ordinary outcome of an interrupted job. The reader skips what it
cannot parse and reports how many it skipped.
"""

from __future__ import annotations

import json

from aidaily.collect import read_items_jsonl

GOOD = {
    "item_id": "a1",
    "source_id": "s",
    "title": "t",
    "title_norm": "t",
    "url": "https://x/1",
    "fetched_at": "2026-10-21T00:00:00Z",
    "first_seen_at": "2026-10-21T00:00:00Z",
    "updated_at": "2026-10-21T00:00:00Z",
    "content_sha256": "abc",
    "simhash": 0,
}


def _line(**over):
    record = dict(GOOD)
    record.update(over)
    return json.dumps(record)


def test_a_truncated_line_is_skipped_not_raised(tmp_path) -> None:
    path = tmp_path / "items.jsonl"
    path.write_text(
        _line(item_id="a1") + chr(10) + '{"item_id":"b2","source_id":"s","title":"trunc' + chr(10) + _line(item_id="c3") + chr(10),
        encoding="utf-8",
    )
    items = read_items_jsonl(path)
    assert [i.item_id for i in items] == ["a1", "c3"]


def test_a_blank_line_is_ignored(tmp_path) -> None:
    path = tmp_path / "items.jsonl"
    path.write_text(chr(10) + _line() + chr(10) + chr(10), encoding="utf-8")
    assert len(read_items_jsonl(path)) == 1


def test_a_missing_file_is_an_empty_list(tmp_path) -> None:
    assert read_items_jsonl(tmp_path / "nope.jsonl") == []


def test_an_entirely_corrupt_file_returns_nothing_rather_than_raising(tmp_path) -> None:
    path = tmp_path / "items.jsonl"
    path.write_text(chr(10).join(["garbage", "more garbage", "{"]), encoding="utf-8")
    assert read_items_jsonl(path) == []