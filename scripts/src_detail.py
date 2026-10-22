import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

for s in srcs:
    if s.get("source_id") in ("rss:daily-juya-uk", "rss:hex2077-dev-rss-zh-cn", "rss:aihot-news-full"):
        print("  %s" % s.get("source_id"))
        print("    url      : %s" % s.get("url"))
        print("    category : %s" % s.get("category"))
        print("    dedup    : %s" % s.get("dedup_group"))
        print("    params   : %s" % s.get("params"))
        print("    notes    : %s" % str(s.get("notes"))[:130])
        print()