import io, sys, yaml
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
srcs = []
for name in ("sources/registry.yaml", "sources/local.yaml"):
    d = yaml.safe_load((root / name).read_text(encoding="utf-8"))
    srcs.extend(d.get("sources") or d)

print("  已有的 juya / hex2077 / aihot 源：")
for s in srcs:
    blob = ((s.get("url") or "") + " " + (s.get("name") or "")).lower()
    if any(k in blob for k in ("juya", "hex2077", "aihot")):
        print("    %-42s %s" % (s.get("source_id"), (s.get("url") or "")[:62]))
        print("       type=%s enabled=%s category=%s" % (s.get("source_type"), s.get("enabled"), s.get("category")))