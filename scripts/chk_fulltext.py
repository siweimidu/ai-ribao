import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")
srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

on = [s for s in srcs if s.get("site_fulltext")]
print("  已开启 site_fulltext 的源: %d" % len(on))
for s in on:
    print("    %-34s %s" % (s.get("source_id"), (s.get("url") or "")[:52]))
print()
print("  目标源的现状：")
for s in srcs:
    if any(k in (s.get("url") or "") for k in ("juya", "hex2077", "dailydawn", "aihot.news/feed")):
        print("    %-30s site_fulltext=%-5s %s" % (s.get("source_id"), s.get("site_fulltext"), (s.get("url") or "")[:46]))