import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

p = Path(r"D:\Code\AI日报\src\aidaily\pipeline.py")
s = p.read_text(encoding="utf-8")
new = Path(r"D:\Code\AI日报\scripts\pat2.txt").read_text(encoding="utf-8").rstrip()

start = s.index("_MODEL_NAME = re.compile(")
end = s.index(")", s.index("re.IGNORECASE,")) + 1
s = s[:start] + new + s[end:]

# `leads_the_issue` now tests family + version + verb.
old = "    if not _MODEL_NAME.search(lower):"
new2 = "    if not (_MODEL_FAMILY.search(lower) and _VERSION.search(text)):"
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new2, 1)

p.write_text(s, encoding="utf-8")
print("two-stage match")