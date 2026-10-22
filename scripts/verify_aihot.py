import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")
srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

print("  所有 aihot.news 的源：")
for s in srcs:
    u = s.get("url") or ""
    if "aihot.news" in u:
        print("    %-28s enabled=%-5s %s" % (s.get("source_id"), s.get("enabled"), u))
print()
print("  aihot.news/feed.xml （精选摘要）单独查：")
hit = [s for s in srcs if (s.get("url") or "") == "https://aihot.news/feed.xml"]
print("    找到 %d 条" % len(hit))
for s in hit:
    print("      %s enabled=%s" % (s.get("source_id"), s.get("enabled")))