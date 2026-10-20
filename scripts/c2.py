import io, json, sys
from collections import Counter
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

p = Path(r"C:\Users\35238\AppData\Local\Temp\art39402619865\raw-items\data\raw\items.jsonl")
n = 0
story = 0
by = Counter()
for line in p.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    d = json.loads(line)
    n += 1
    u = (d.get("url") or "") + (d.get("canonical_url") or "")
    if "#story-" in u:
        story += 1
    by[d.get("source_id")] += 1

print("  条目 %d，其中展开出的单条 %d" % (n, story))
print()
print("  ainewslog: %d" % by.get("rss:ainewslog-com", 0))
print("  juya     : %d" % by.get("rss:daily-juya-uk", 0))