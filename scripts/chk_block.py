import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = Path(r"D:\Code\AI日报\src\aidaily\site.py").read_text(encoding="utf-8").splitlines()

idx = next(i for i, ln in enumerate(lines) if "repo = None" in ln)
print("  card 块在 %d 行：" % (idx + 1))
for i in range(idx - 4, idx + 26):
    print("    %4d: %s" % (i + 1, lines[i][:96]))