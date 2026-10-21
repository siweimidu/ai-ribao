import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.entities import extract_entities
from aidaily.samestory import same_message

root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))

rows = []
for e in d["digest"]["top_events"]:
    t = e.get("title") or ""
    if "物理" in t:
        rows.append(t)

print("  %d 条，各自实体：" % len(rows))
for t in rows:
    ents = extract_entities(t)
    print("    %s" % t[:58])
    print("       %s" % sorted(ents))

print()
print("  两两共享实体数 + same_message：")
for i in range(len(rows)):
    for j in range(i + 1, len(rows)):
        a, b = extract_entities(rows[i]), extract_entities(rows[j])
        shared = a & b
        sm = same_message(rows[i], rows[j])
        if shared or sm:
            print("    %d-%d shared=%d %s same_message=%s" % (i, j, len(shared), sorted(shared), sm))