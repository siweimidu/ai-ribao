import io, re, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = Path(r"D:\Code\AI日报\src\aidaily\l3.py").read_text(encoding="utf-8").splitlines()

print("  l3.py %d 行，函数：" % len(lines))
for i, ln in enumerate(lines):
    m = re.match(r"^(?:async )?def (\w+)\(", ln)
    if m:
        print("    %4d: %s" % (i + 1, ln.strip()[:84]))