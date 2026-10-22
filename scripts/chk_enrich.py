import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")

# Does the pipeline already fetch full text for RSS items whose body is missing?
src = (root / "src" / "aidaily" / "enrich.py").read_text(encoding="utf-8") if (root / "src" / "aidaily" / "enrich.py").exists() else ""
print("  enrich.py 存在: %s (%d 字符)" % (bool(src), len(src)))

import re
for f in ("enrich.py", "pipeline.py", "publish.py"):
    p = root / "src" / "aidaily" / f
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    hits = [m.start() for m in re.finditer(r"fetch_fulltext|content_text is None|full.?text", t)]
    print("  %-14s 命中 %d" % (f, len(hits)))
    for h in hits[:3]:
        ln = t[:h].count(chr(10)) + 1
        print("      line %d: %s" % (ln, t.splitlines()[ln-1].strip()[:88]))