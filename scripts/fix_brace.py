from pathlib import Path
p = Path("site/assets/motion.js")
lines = p.read_text(encoding="utf-8").splitlines()

idx = next(i for i, ln in enumerate(lines) if "syncTocScroll(best.a);" in ln)
assert lines[idx + 1].strip() == "};" and lines[idx + 2].strip() == "};", lines[idx:idx + 3]
del lines[idx + 2]
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("removed duplicate brace at line", idx + 3)