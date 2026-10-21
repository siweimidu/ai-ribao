import io, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.l3 import coarse_clusters
from aidaily.models import NormalizedItem

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))
now = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)

proxies = []
for e in d["digest"]["top_events"]:
    t = e.get("title") or ""
    if "物理" in t:
        proxies.append(NormalizedItem(
            item_id=e["event_id"], source_id=(e.get("source_ids") or ["x"])[0],
            title=t, title_norm=t.lower(), url=(e.get("all_urls") or [""])[0],
            fetched_at=now, first_seen_at=now, updated_at=now,
            content_sha256="0" * 16, simhash=0,
            published_at=now, summary="", language="zh",
        ))

print("  代理条目 %d 个" % len(proxies))
clusters = coarse_clusters(proxies)
print("  聚成 %d 个簇：" % len(clusters))
for c in clusters:
    print("    %d 条, 共享实体 %d" % (len(c.item_ids), len(c.shared_entities)))