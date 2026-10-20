"""Every module that formats a date must actually have the timezone it formats into.

A `NameError` on `_DISPLAY_TZ` in `analyze._materials` crashed every publish run for 45 minutes:
the constant was referenced but never defined, the workflow retried publish three times, and each
retry replayed 5685 items before dying in the same place. The existing date tests covered
`site._when` and the rendered pages, so they all passed while the pipeline was broken.

These tests call each formatter, which is the only way to catch a missing definition.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module,attribute",
    [
        ("aidaily.analyze", "_DISPLAY_TZ"),
        ("aidaily.render", "_DISPLAY_TZ"),
        ("aidaily.site", "_SITE_TZ"),
    ],
)
def test_display_timezone_is_defined(module: str, attribute: str) -> None:
    """Referencing a timezone without defining it is a `NameError` at runtime, not import time.

    `analyze.py` imported fine and every date test passed; the failure only appeared when the
    formatter ran, which is inside the publish job.
    """
    mod = importlib.import_module(module)
    tz = getattr(mod, attribute, None)
    assert tz is not None, f"{module}.{attribute} is referenced but never defined"
    assert str(tz) == "Asia/Shanghai", tz


def test_materials_formats_beijing_time() -> None:
    """The function that crashed: it must run, and it must show Beijing time."""
    from datetime import datetime, timezone

    from aidaily.analyze import _materials
    from aidaily.models import NormalizedItem

    ts = datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc)
    item = NormalizedItem(
        item_id="i1",
        source_id="rss:x",
        title="一条消息",
        title_norm="一条消息",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        published_at=ts,
        fetched_at=ts,
        first_seen_at=ts,
        updated_at=ts,
        summary="摘要",
        content_text="正文",
        content_sha256="0" * 64,
        simhash=0,
        language="zh",
    )

    text = _materials([item])
    # 21:47 UTC on the 19th is 05:47 Beijing on the 20th.
    assert "2026-10-20 05:47" in text, text
    assert "北京时间" in text
    assert "UTC" not in text
