import io, re, sys, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")

print("  site 目录里的期次文件：")
for p in sorted((root / "data" / "digests" / "site").glob("2026-*.html")):
    print("    %s  %d bytes" % (p.name, p.stat().st_size))
print()
print("  data/digests 下的归档 json：")
for p in sorted((root / "data" / "digests").glob("2026-*.json")):
    print("    %s" % p.name)
print()

h = (root / "data" / "digests" / "site" / "2026-10-19.html").read_text(encoding="utf-8")
m = re.search(r'id="calendar-data">(.*?)</script>', h, re.S)
if m:
    d = json.loads(m.group(1))
    print("  10-19 页面 calendar: current=%s" % d.get("current"))
    print("    dates=%s" % (d.get("dates") or [])[:8])