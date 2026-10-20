from pathlib import Path
p = Path("site/assets/components.css")
lines = p.read_text(encoding="utf-8").splitlines()

# Drop the stale "scrolls with the page" override that sits at the end of the file.
start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("/* The TOC scrolls with the page"))
while not lines[start].startswith("@media"):
    start -= 1
end = start
while lines[end].strip() != "}":
    end += 1
del lines[start:end + 1]

body = "\n".join(lines).rstrip("\n")
body += "\n" + Path("scripts/final_toc.css").read_text(encoding="utf-8")
p.write_text(body, encoding="utf-8")
print("stale removed, sticky appended; lines:", len(body.splitlines()))