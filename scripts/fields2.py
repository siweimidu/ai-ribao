import io, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.models import NormalizedItem
print("  NormalizedItem 字段：")
for k, v in NormalizedItem.model_fields.items():
    req = "必填" if v.is_required() else "可选"
    print("    %-18s %-6s %s" % (k, req, str(v.annotation)[:40]))