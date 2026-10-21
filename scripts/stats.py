import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))

# Look for cluster stats in the archive
print("  digest 顶层键：")
for k in d["digest"]:
    v = d["digest"][k]
    print("    %-24s %s" % (k, type(v).__name__))

print()
for key in ("cluster_stats", "stats", "report", "diagnostics"):
    if key in d.get("digest", {}) or key in d:
        print("  %s: %s" % (key, json.dumps(d.get("digest", {}).get(key) or d.get(key), ensure_ascii=False)[:400]))