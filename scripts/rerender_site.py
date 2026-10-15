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
from aidaily.collect import read_items_jsonl  # noqa: E402
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

    # The raw items, keyed by id.
    #
    # This used to return {} -- an empty map. Nothing failed loudly, but every feature that
    # looks up a story's member items silently did nothing: most visibly, a headline whose
    # model-written title was still English could not fall back to the Chinese title of a
    # member outlet, so the day's biggest story rendered in English and was moved into the
    # untranslated block.
    items: dict[str, NormalizedItem] = {}
    raw_path = ROOT / "data" / "raw" / "items.jsonl"
    if raw_path.exists():
        for item in read_items_jsonl(str(raw_path)):
            items[item.item_id] = item

    return digest, insights, items


def load_sources() -> list[dict]:
    """The registry as plain dicts, for the 信息源 page.

    Read from the registry the collector actually uses, so the page cannot describe a
    different set of sources than the pipeline reads. A failure here degrades to an empty
    list rather than aborting: the page then says it has no data, which is honest.
    """
    try:
        from aidaily.registry import apply_overrides, load_overrides, load_registry

        sources, _ = apply_overrides(load_registry(), load_overrides())
        return [s.model_dump() for s in sources]
    except Exception as exc:  # noqa: BLE001
        print(f"  （信息源清单读取失败：{type(exc).__name__}: {exc}）")
        return []


#: Committed snapshot of the last successful Tibo fetch.
#:
#: `data/state/aihot_cache/` is gitignored -- it is a network cache for a third-party API,
#: subject to that API's caching terms. That is the right call for the cache, but it made the
#: Tibo page depend on a live call succeeding **on the machine doing the rendering**. In CI
#: it does not, so every CI-deployed `tibo.html` was the explicit empty state: 3 KB instead
#: of 82 KB, no calendar at all -- and `scripts/test_calendars.py`, which asserts the grid
#: exists, failed the build.
#:
#: This snapshot is deliberately outside the gitignored cache and *is* committed. It is small
#: (a few hundred reset events), it is the page's own data rather than a redistribution of the
#: upstream feed, and it means the page has something true to show when the API is unreachable.
TIBO_SNAPSHOT = ROOT / "data" / "state" / "aihot-codex-snapshot.json"


def load_tibo() -> dict:
    """The Codex reset monitor for the page: live when possible, snapshot when not.

    A source that is down must not stop the digest from rendering. It must also not silently
    become an empty page -- "the API is unreachable" and "there is nothing to show" look
    identical to a reader, and only one of them is true.
    """
    try:
        from aidaily.aihot import AihotClient, activities, reset_events, reset_summary

        client = AihotClient(cache_dir=ROOT / "data" / "state" / "aihot_cache")
        payload = client.codex_resets()
        if payload:
            summary = reset_summary(payload, policy=client.policy)
            summary["events"] = reset_events(payload)
            summary["activities"] = activities(payload)
            summary["client_stats"] = dict(client.stats)
            summary.pop("stale", None)
            try:
                TIBO_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
                TIBO_SNAPSHOT.write_text(
                    json.dumps(summary, ensure_ascii=False), encoding="utf-8"
                )
            except OSError:
                # A read-only checkout must not break rendering; the snapshot is an
                # optimisation, not a requirement.
                pass
            return summary
        reason = "抓取返回空"
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {str(exc)[:80]}"

    if TIBO_SNAPSHOT.exists():
        try:
            summary = json.loads(TIBO_SNAPSHOT.read_text(encoding="utf-8"))
            summary["stale"] = reason
            print(f"  （Tibo 实时抓取失败（{reason}），改用已提交快照）")
            return summary
        except (OSError, ValueError) as exc:
            print(f"  （Tibo 快照也无法读取：{type(exc).__name__}）")

    print(f"  （Tibo 监控数据获取失败且无快照，页面显示空状态：{reason}）")
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
        sources=load_sources(),
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
