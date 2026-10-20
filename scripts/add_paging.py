from pathlib import Path
p = Path("site/assets/motion.js")
lines = p.read_text(encoding="utf-8").splitlines()
block = Path("scripts/pick_block.txt").read_text(encoding="utf-8").splitlines()

start = next(i for i, ln in enumerate(lines) if ln.strip() == "const tocLinks = [...document.querySelectorAll('.toc__nav a')];")
# Replace through the line "setCurrent(best.a.hash.slice(1));" that ends pick().
end = next(i for i in range(start, len(lines)) if "setCurrent(best.a.hash.slice(1));" in lines[i])
lines[start:end + 1] = block
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("paging added", start + 1, "to", end + 1)