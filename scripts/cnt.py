import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")
d = json.loads((root / "data" / "digests" / "2026-10-21.json").read_text(encoding="utf-8"))
print("  counts: %s" % json.dumps(d["digest"]["counts"], ensure_ascii=False, indent=2)[:900])
print()
print("  warnings: %s" % json.dumps(d["digest"]["warnings"], ensure_ascii=False)[:600])