"""Diagnostic: is a 0% L2 merge rate real, or is the pipeline broken?

Independent of the dedup module, this computes pairwise title similarity over the
windowed items and prints the closest pairs, so the reported merge rate can be checked
against evidence rather than trusted.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aidaily.collect import read_items_jsonl  # noqa: E402
from aidaily.config import load_config  # noqa: E402
from aidaily.normalize import hamming, title_similarity  # noqa: E402
from aidaily.select import select_window  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
items = read_items_jsonl(ROOT / "data" / "raw" / "items.jsonl")
cfg = load_config(env={})
window = select_window(items, cfg)
kept = window.kept

print(f"items in file        : {len(items)}")
print(f"kept after window    : {len(kept)}")
print(f"sources in window    : {len(window.sources_with_items)}")

# Which sources contributed nothing inside the window?
all_sources = {i.source_id for i in items}
in_window = window.sources_with_items
print(f"\n-- sources collected but with nothing in the {cfg.run.window_hours}h window ({len(all_sources - in_window)}) --")
newest_by_source: dict[str, str] = {}
for i in items:
    if i.published_at:
        cur = newest_by_source.get(i.source_id)
        iso = i.published_at.isoformat()
        if cur is None or iso > cur:
            newest_by_source[i.source_id] = iso
for sid in sorted(all_sources - in_window):
    print(f"   {sid:56} newest={newest_by_source.get(sid, 'no dated item')}")

print(f"\n-- windowed items per source --")
for sid, n in Counter(i.source_id for i in kept).most_common():
    print(f"   {n:4}  {sid}")

# Independent near-duplicate search: O(n^2) is fine for a diagnostic.
print(f"\n-- closest title pairs in the window (independent of dedup.py) --")
pairs = []
for idx, a in enumerate(kept):
    for b in kept[idx + 1:]:
        if not a.title_norm or not b.title_norm:
            continue
        sim = title_similarity(a.title_norm, b.title_norm)
        hs = hamming(a.simhash, b.simhash) if (a.simhash and b.simhash) else 64
        if sim >= 0.60 or hs <= 6:
            pairs.append((sim, hs, a, b))
pairs.sort(key=lambda p: (-p[0], p[1]))
print(f"   candidate pairs at sim>=0.60 or hamming<=6: {len(pairs)}")
for sim, hs, a, b in pairs[:12]:
    same_src = "SAME-SRC" if a.source_id == b.source_id else "cross-src"
    samedom = "same-domain" if a.url.split('/')[2] == b.url.split('/')[2] else "diff-domain"
    print(f"\n   sim={sim:.3f} hamming={hs:2} [{same_src} {samedom}]")
    print(f"     A {a.source_id}: {a.title[:70]}")
    print(f"     B {b.source_id}: {b.title[:70]}")
