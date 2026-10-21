import io, json, re, sys
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

# Did the collector even SEE juya's 10-21 issue? The snapshot is from 23:10 UTC, the issue
# appeared at 01:28 UTC. So no. Confirm against the raw artifact.
p = r"C:\Users\35238\AppData\Local\Temp\items21\data\raw\items.jsonl"
juya = []
for line in open(p, encoding="utf-8"):
    if not line.strip():
        continue
    d = json.loads(line)
    if "juya" not in (d.get("source_id") or ""):
        continue
    juya.append((d.get("published_at"), d.get("title")))

juya.sort(key=lambda x: str(x[0]), reverse=True)
print("  采集快照里 juya 最新 5 条：")
for ts, t in juya[:5]:
    print("    %s  %s" % (str(ts)[:16], (t or "")[:56]))
print()
print("  快照里有没有 10-21 那期？ %s" % any("10-21" in str(ts) for ts, _ in juya))