import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
s = Path(r"D:\Code\AI日报\src\aidaily\__main__.py").read_text(encoding="utf-8")

for i, ln in enumerate(s.splitlines(), 1):
    if any(k in ln for k in ("幂等", "idempot", "already_done", "已推送", "ledger")):
        print("  %4d: %s" % (i, ln.strip()[:94]))