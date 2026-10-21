import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.l3 import coarse_clusters
from aidaily.models import NormalizedItem
from datetime import datetime, timezone

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))

# Rebuild proxy items from the archived events
now = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
proxies = []
for e in d["digest"]["top_events"]:
    t = e.get("title") or ""
    if "物理" in t:
        proxies.append(NormalizedItem(
            item_id=e["event_id"], title=t, url=(e.get("all_urls") or [""])[0],
            summary="", source_id=(e.get("source_ids") or ["x"])[0],
            language="zh", published_at=now, fetched_at=now,
        ))

print("  代理条目 %d 个" % len(proxies))
clusters = coarse_clusters(proxies)
print("  聚成 %d 个簇：" % len(clusters))
for c in clusters:
    print("    %d 条, 共享实体 %d 个: %s" % (len(c.item_ids), len(c.shared_entities), sorted(c.shared_entities)[:5]))