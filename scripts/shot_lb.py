import asyncio, io, re, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

root = Path(r"D:\Code\AI日报")
site = root / "data" / "digests" / "site"
html = (site / "leaderboard.html").read_text(encoding="utf-8")

# Inline the CSS so the screenshot shows the real design.
for name in ("tokens.css", "components.css"):
    css = (site / "assets" / name).read_text(encoding="utf-8")
    html = html.replace(f'<link rel="stylesheet" href="assets/{name}">', f"<style>{css}</style>")
html = re.sub(r'<link[^>]+href="assets/[^"]+\.css"[^>]*>', "", html)
html = re.sub(r'<link rel="preconnect"[^>]*>', "", html)
html = re.sub(r'<link rel="stylesheet" href="https://[^"]+">', "", html)

tmp = root / "docs" / "_lb.html"
tmp.parent.mkdir(exist_ok=True)
tmp.write_text(html, encoding="utf-8")

from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1240, "height": 900}, device_scale_factor=2)
        await pg.goto(tmp.as_uri())
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=str(root / "docs" / "lb-light.png"))
        print("  light ok")

        # Dark theme
        await pg.evaluate("document.documentElement.setAttribute('data-theme','dark')")
        await pg.wait_for_timeout(300)
        await pg.screenshot(path=str(root / "docs" / "lb-dark.png"))
        print("  dark ok")
        await b.close()

asyncio.run(main())
