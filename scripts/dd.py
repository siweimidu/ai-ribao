import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = Path(r"D:\Code\AI日报\src\aidaily\dedup.py").read_text(encoding="utf-8").splitlines()
import re
print("  dedup.py 函数：")
for i, ln in enumerate(lines):
    m = re.match(r"^(?:async )?def (\w+)\(", ln)
    if m:
        print("    %4d: %s" % (i + 1, ln.strip()[:80]))