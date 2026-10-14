"""Re-render the published site from an archived digest.

Why this exists: a design change should not require re-running the LLM. The digest JSON
already carries everything the renderer needs — the events, the three-bucket insights, the
counts, the source coverage — so the site can be rebuilt byte-for-byte from the archive at
zero token cost and with full reproducibility.

It is also how a merge conflict over artifacts is resolved honestly: the committed digest
holds the *real* run (25 LLM calls, 16k tokens), while a local `--no-llm` render holds a
placeholder. Regenerating from the real archive keeps the real content and the new design.

Usage:
    python scripts/rerender_site.py data/digests/2026-10-14.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aidaily.analyze import EventInsight  # noqa: E402
from aidaily.models import Digest, NormalizedItem  # noqa: E402
from aidaily.publish import write_rss, write_site  # noqa: E402
from aidaily.render import render_brief, render_deep, render_json_feed  # noqa: E402


def load(path: Path) -> tuple[Digest, dict[str, EventInsight], dict[str, NormalizedItem]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = Digest.model_validate(payload["digest"])

    insights: dict[str, EventInsight] = {}
    for event_id, raw in (payload.get("insights") or {}).items():
        insights[event_id] = EventInsight(**raw)

    # `insights` are keyed by event id, and the members live in the digest's own events,
    # so the item map is rebuilt from those members rather than from a separate archive.
    # Only the fields the site renders are needed; a missing body degrades to a bare
    # headline row, which is visible rather than wrong.
    items: dict[str, NormalizedItem] = {}
    return digest, insights, items


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    json_path = Path(sys.argv[1])
    if not json_path.is_absolute():
        json_path = ROOT / json_path
    out_dir = json_path.parent

    digest, insights, items = load(json_path)
    site_url = "https://siweimidu.github.io/ai-ribao"

    brief = render_brief(digest, insights, items, max_items=digest.counts.get("brief_items", 12))
    deep = render_deep(digest, insights, items, max_items=len(digest.top_events))
    feed = render_json_feed(digest, insights, site_url=site_url)

    (out_dir / f"{digest.date}.brief.md").write_text(brief, encoding="utf-8")
    (out_dir / f"{digest.date}.deep.md").write_text(deep, encoding="utf-8")

    rss = write_rss(digest, out_dir, site_url=site_url)
    site = write_site(
        digest, deep, out_dir,
        site_url=site_url, insights=insights, items_by_id=items,
    )

    feed_dir = out_dir / "site" / "feed"
    feed_dir.mkdir(parents=True, exist_ok=True)
    feed_dir.joinpath("zh.json").write_text(feed, encoding="utf-8")

    print(f"date     : {digest.date}")
    print(f"events   : {digest.counts.get('events')} (多源 {digest.counts.get('multi_source_events')})")
    print(f"insights : {len(insights)}")
    print(f"rss      : {rss.detail}")
    print(f"site     : {site.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
