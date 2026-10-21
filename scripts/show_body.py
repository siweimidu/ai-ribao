import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
s = Path(r"D:\Code\AI日报\src\aidaily\media.py").read_text(encoding="utf-8")
lines = s.splitlines()
i = next(i for i, ln in enumerate(lines) if "Body images only" in ln)
j = next(k for k in range(i, len(lines)) if lines[k].strip() == "return out[:limit]")
for k in range(i - 2, j + 1):
    print("  %4d: %s" % (k + 1, lines[k][:92]))