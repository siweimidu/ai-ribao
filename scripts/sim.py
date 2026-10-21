import io, json, sys
from itertools import combinations
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.normalize import title_similarity

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))
rows = [e["title"] for e in d["digest"]["top_events"] if "物理" in (e.get("title") or "")]

print("  两两标题相似度：")
vals = []
for a, b in combinations(rows, 2):
    s = title_similarity(a.lower(), b.lower())
    vals.append(s)
    if s > 0.1:
        print("    %.3f  %s | %s" % (s, a[:26], b[:26]))

print()
print("  最大相似度: %.3f  阈值需要 0.35 或 0.5" % max(vals))