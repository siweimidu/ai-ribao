from pathlib import Path
p = Path("site/assets/components.css")
lines = p.read_text(encoding="utf-8").splitlines()

start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("/* The TOC stays in the viewport"))
end = next(i for i in range(start, len(lines)) if lines[i].strip() == "}" and i > start)

# The block run ends with a closing brace at column 0 (the @media), so stop at the first
# line that is exactly "}" after the .toc rule.
while lines[end - 1].strip() != "}":
    end += 1
while lines[end - 1].strip() != "}":
    end += 1
del lines[start - 1:end]
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("removed lines", start, "to", end)