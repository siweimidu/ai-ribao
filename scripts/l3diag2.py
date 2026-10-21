import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))

print("  这 7 条的 event 信息：")
for e in d["digest"]["top_events"]:
    t = e.get("title") or ""
    if "物理" in t:
        print("    %s" % t[:50])
        print("       event_id: %s" % e.get("event_id"))
        print("       member_item_ids: %d 个" % len(e.get("member_item_ids") or []))
        print("       independent_source_count: %s" % e.get("independent_source_count"))
        print("       first_seen: %s" % e.get("first_seen_at"))