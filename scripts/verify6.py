import io, sys, re, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")

srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

print("  === 你截图列出的 6 个 AIHOT feed 是否都在 ====")
WANT = ("feed.xml", "feed/full.xml", "feed/all.xml", "feed/daily.xml", "feed/weekly.xml", "feed/monthly.xml")
for w in WANT:
    hit = [s for s in srcs if (s.get("url") or "").endswith(w)]
    if hit:
        s = hit[0]
        print("    OK  %-22s enabled=%-5s %s" % (w, s.get("enabled"), s.get("source_id")))
    else:
        print("    缺  %s" % w)

print()
print("  === dailydawn ====")
for s in srcs:
    if "dailydawn" in (s.get("url") or ""):
        print("    %-30s enabled=%-5s type=%-8s %s" % (s.get("source_id"), s.get("enabled"), s.get("source_type"), s.get("url")))