from pathlib import Path

p = Path("scripts/ui_variants.py")
s = p.read_text(encoding="utf-8")

# Drop the data-n injection: the page already renders `.item__no`.
old_js = """            # Number the stories so the marker rules have something to render.
            await page.evaluate(\"\"\"() => {
              document.querySelectorAll(\".item\").forEach((el, i) => {
                el.setAttribute(\"data-n\", String(i + 1).padStart(2, \"0\"));
              });
            }\"\"\")
"""
assert old_js in s, "js block"
s = s.replace(old_js, "", 1)

# Style the existing number instead of inventing one.
s = s.replace(""".item::before { position: absolute; left: 0; top: 1.2rem; font-family: var(--f-mono);
  font-size: .8rem; color: var(--accent); content: attr(data-n); }""",
""".item__no { font-family: var(--f-mono); font-size: .8rem; color: var(--accent);
             align-self: start; padding-top: .2rem; }""")

s = s.replace(""".item::before { position: absolute; left: 1.1rem; top: 1.18rem; width: 1.35rem; height: 1.35rem;
  border-radius: 50%; background: var(--accent-soft); color: var(--accent);
  display: grid; place-items: center; font-family: var(--f-mono); font-size: .68rem;
  font-weight: 600; content: attr(data-n); }""",
""".item__no { width: 1.35rem; height: 1.35rem; border-radius: 50%; background: var(--accent-soft);
             color: var(--accent); display: grid; place-items: center;
             font-family: var(--f-mono); font-size: .68rem; font-weight: 600; flex: none; }""")

s = s.replace(""".item::before { position: absolute; left: 0; top: .68rem; font-family: var(--f-mono);
  font-size: .72rem; color: var(--muted-fg); content: attr(data-n); }""",
""".item__no { font-family: var(--f-mono); font-size: .72rem; color: var(--muted-fg); }""")

p.write_text(s, encoding="utf-8")
print("preview fixed")
