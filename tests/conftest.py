"""Shared fixtures.

`src/` is put on sys.path so the suite runs from a clean checkout with no install
step -- the same way GitHub Actions runs it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aidaily.ingest import compute_age_bucket  # noqa: E402
from aidaily.models import NormalizedItem  # noqa: E402
from aidaily.normalize import (  # noqa: E402
    content_fingerprint,
    simhash,
    strip_html,
    title_norm,
    try_normalize_url,
)

FIXED_NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


@pytest.fixture
def make_item():
    """Build a NormalizedItem with fingerprints derived exactly as production does.

    `age_bucket` is computed rather than defaulted: production items always carry one,
    and a fixture that leaves it as "unknown" makes window tests pass or fail for the
    wrong reason.
    """

    def _make(
        *,
        title: str = "Untitled",
        url: str = "https://example.com/x",
        content: str = "",
        summary: str = "",
        source_id: str = "rss:test",
        published_at: datetime | None = FIXED_NOW,
        canonical_url: str | None = None,
        item_id: str | None = None,
    ) -> NormalizedItem:
        body = strip_html(content or summary or title)
        from aidaily.models import SourceSpec

        spec = SourceSpec(
            source_id=source_id, name=source_id, url=url or "https://example.com/x",
            normalized_url=url or "https://example.com/x",
            domain=(url or "example.com").split("/")[2] if "//" in (url or "") else "example.com",
            category="media", source_type="rss", adapter="RssFetcher",
            found_in=["repo:file#key"], repositories=["repo"],
        )
        return NormalizedItem(
            item_id=item_id or f"i{abs(hash((url, title))) % 10**12:012d}",
            source_id=source_id,
            title=title,
            title_norm=title_norm(title),
            url=url,
            canonical_url=canonical_url,
            published_at=published_at,
            fetched_at=FIXED_NOW,
            first_seen_at=FIXED_NOW,
            updated_at=FIXED_NOW,
            summary=summary,
            content_text=body,
            content_sha256=content_fingerprint(body),
            simhash=simhash(body),
            age_bucket=compute_age_bucket(
                published_at, FIXED_NOW.date(), window_source=False
            ),
        )

    return _make
