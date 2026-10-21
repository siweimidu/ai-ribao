import io, json, sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.l3 import coarse_clusters
from aidaily.models import NormalizedItem
from aidaily.normalize import title_similarity

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))
now = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)

by_id = {}
proxies = []
for e in d["digest"]["top_events"]:
    t = e.get("title") or ""
    if "物理" in t:
        proxies.append(NormalizedItem(
            item_id=e["event_id"], source_id=(e.get("source_ids") or ["x"])[0],
            title=t, title_norm=t.lower(), url=(e.get("all_urls") or [""])[0],
            fetched_at=now, first_seen_at=now, updated_at=now,
            content_sha256="0" * 16, simhash=0, published_at=now, summary="", language="zh",
        ))
        by_id[e["event_id"]] = t

c = coarse_clusters(proxies)[0]
titles = [by_id[i] for i in c.item_ids]
print("  簇内 %d 条，共享实体 %d" % (len(titles), len(c.shared_entities)))
print()
best = 0.0
for a, b in combinations(titles, 2):
    s = title_similarity(a.lower(), b.lower())
    if s > best:
        best = s
print("  best_similarity = %.3f" % best)
print("  shared = %d" % len(c.shared_entities))
print()
print("  判定：")
print("    (shared>=3 and best>=0.35): %s" % (len(c.shared_entities) >= 3 and best >= 0.35))
print("    (shared>=2 and best>=0.5):  %s" % (len(c.shared_entities) >= 2 and best >= 0.5))