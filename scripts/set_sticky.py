from pathlib import Path
import re
p = Path("site/assets/components.css")
s = p.read_text(encoding="utf-8")
block = Path("scripts/toc_sticky.css").read_text(encoding="utf-8").rstrip("\n")

# Replace the previous override (the one that removed sticky) with this one.
start = s.index("@media (min-width: 1400px) {\n  /* The TOC scrolls with the page")
end = s.index("}", s.index("overscroll-behavior: auto;", start)) + 2
s = s[:start] + block + "\n" + s[end:]
p.write_text(s, encoding="utf-8")
print("sticky restored with paging")