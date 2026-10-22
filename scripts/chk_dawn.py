import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")

srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

print("  已存在的 dailydawn 源：")
hits = [s for s in srcs if "dailydawn" in ((s.get("url") or "") + (s.get("name") or "")).lower()]
if not hits:
    print("    无")
for s in hits:
    print("    %-40s %s" % (s.get("source_id"), (s.get("url") or "")[:56]))
    print("       type=%s enabled=%s category=%s" % (s.get("source_type"), s.get("enabled"), s.get("category")))