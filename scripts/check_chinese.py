"""Report how much of the digest a reader actually sees in Chinese.

The requirement is that everything displayed on the page is Chinese, with the original
language only reachable by following a link. That is a property of the *rendered* digest, so
it is measured the way the site renders it: `insight.title` when present, otherwise the
event's own title.

Run after a real (model-backed) pipeline run. With `--no-llm` the numbers are meaningless by
construction -- every item falls back to the source's own words.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def displayed_title(event: dict, insights: dict) -> str:
    insight = insights.get(event.get("event_id")) or {}
    title = insight.get("title")
    return (title or event.get("title") or "").strip()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "digests" / "2026-10-14.json"
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = payload["digest"]
    insights = payload.get("insights") or {}
    events = digest.get("top_events") or []

    usage = digest.get("llm_usage") or {}
    print(f"  events          : {len(events)}")
    print(f"  insights        : {len(insights)}")
    print(f"  LLM             : {usage.get('calls')} 次调用 / {usage.get('tokens')} token")

    final = [displayed_title(e, insights) for e in events]
    english = [t for t in final if not has_cjk(t)]
    print()
    print(f"  最终展示标题中无中文的: {len(english)}/{len(final)}")
    for t in english[:8]:
        print(f"    · {t[:64]}")

    # Also check the three body buckets, since those are what the page shows under a title.
    body_english: list[str] = []
    for event in events:
        insight = insights.get(event.get("event_id")) or {}
        for key in ("facts", "inferences", "uncertainties"):
            for line in insight.get(key) or []:
                if len(line) > 24 and not has_cjk(line):
                    body_english.append(line)
    print()
    print(f"  正文里无中文的长句: {len(body_english)}")
    for line in body_english[:5]:
        print(f"    · {line[:64]}")

    print()
    print("  前 10 条展示标题:")
    for i, title in enumerate(final[:10], start=1):
        mark = "" if has_cjk(title) else "  ⚠️EN"
        print(f"    {i:2}. {title[:58]}{mark}")

    # Exit non-zero when the requirement is violated, so this can gate a build.
    return 1 if (english or body_english) else 0


if __name__ == "__main__":
    raise SystemExit(main())
