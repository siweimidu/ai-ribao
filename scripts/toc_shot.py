import asyncio, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

SITE = Path(r"D:\Code\AI日报\data\digests\site")
OUT = Path(r"D:\Code\AI日报\data\state\shots")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1500, "height": 820}, device_scale_factor=2)
        await pg.goto((SITE / "2026-10-18.html").as_uri(), wait_until="load")
        await pg.wait_for_timeout(1200)
        await pg.evaluate("window.scrollTo(0, 13000)")
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=str(OUT / "toc-follow.png"))
        print("  saved data/state/shots/toc-follow.png")
        await b.close()

asyncio.run(main())
