from pathlib import Path
p = Path("site/assets/components.css")
lines = p.read_text(encoding="utf-8").splitlines()
block = Path("scripts/toc.css").read_text(encoding="utf-8").splitlines()

start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("/* `sticky` also establishes"))
end = next(i for i in range(start, len(lines)) if "overscroll-behavior" in lines[i])
lines[start:end + 1] = block
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("TOC restored to follow-the-page", start + 1, "to", end + 1)