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
    # The archive stores the section layout *separately* from the digest: `digest` is
    # dumped with `exclude={"sections"}` and the top-level `sections` key holds
    # `{category: [event_id, ...]}`. Validating `digest` alone therefore yields a digest
    # with no sections at all, and every story lands in "其它" — which is exactly what the
    # first version of this script produced on the real page. Reattach them here.
    digest_doc = dict(payload["digest"])
    by_id = {e["event_id"]: e for e in digest_doc.get("top_events", [])}
    digest_doc["sections"] = {
        category: [by_id[eid] for eid in ids if eid in by_id]
        for category, ids in (payload.get("sections") or {}).items()
    }
    digest = Digest.model_validate(digest_doc)

    insights: dict[str, EventInsight] = {}
    for event_id, raw in (payload.get("insights") or {}).items():
        insights[event_id] = EventInsight(**raw)

    return digest, insights, {}


def load_tibo() -> dict:
    """Fetch the Codex reset monitor for the page, tolerating total failure.

    A source that is down must never stop the digest from rendering: the page falls back to
    its explicit empty state, which is honest, rather than to stale numbers presented as
    current.
    """
    try:
        from aidaily.aihot import AihotClient, activities, reset_events, reset_summary

        client = AihotClient(cache_dir=ROOT / "data" / "state" / "aihot_cache")
        payload = client.codex_resets()
        if not payload:
            return {}
        summary = reset_summary(payload, policy=client.policy)
        summary["events"] = reset_events(payload)
        summary["activities"] = activities(payload)
        summary["client_stats"] = dict(client.stats)
        return summary
    except Exception as exc:  # noqa: BLE001
        print(f"  （Tibo 监控数据获取失败，页面将显示空状态：{type(exc).__name__}: {exc}）")
        return {}


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

    rss = write_rss(digest, out_dir, site_url=site_url, insights=insights)
    tibo = load_tibo()
    site = write_site(
        digest, deep, out_dir,
        site_url=site_url, insights=insights, items_by_id=items, tibo=tibo,
    )

    # Keep the downloads the sidebar links next to the pages that link them: the deploy
    # uploads `site/` only, so anything outside it 404s on the live site.
    site_dir = out_dir / "site"
    site_dir.joinpath(f"{digest.date}.md").write_text(deep, encoding="utf-8")
    site_dir.joinpath(f"{digest.date}.brief.md").write_text(brief, encoding="utf-8")

    feed_dir = site_dir / "feed"
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
