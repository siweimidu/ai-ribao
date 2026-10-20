from pathlib import Path
p = Path("site/assets/components.css")
lines = p.read_text(encoding="utf-8").splitlines()
idx = next(i for i, ln in enumerate(lines) if ln.strip() == "overflow-y: visible;" and i > 600)
lines.insert(idx, "    max-height: none;")
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("max-height: none added at", idx + 1)