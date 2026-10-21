import io, re, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
root = Path(r"D:\Code\AI日报")
t = (root / "tests" / "contract" / "test_source_coverage.py").read_text(encoding="utf-8")
lines = t.splitlines()
print("  %d 行，出现 151 的位置：" % len(lines))
for i, ln in enumerate(lines, 1):
    if "151" in ln or "BASELINE" in ln.upper():
        print("  %4d: %s" % (i, ln.strip()[:100]))