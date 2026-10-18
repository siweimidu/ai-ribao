import asyncio, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

BASE = "file:///D:/Code/AI%E6%97%A5%E6%8A%A5/data/digests/site/"
OUT = Path(r"D:\Code\AI日报\data\state\shots")

async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1240, "height": 1000}, device_scale_factor=2)
        for name, tag in (("2026-10-17.html", "fix-issue"), ("index.html", "fix-home")):
            await pg.goto(BASE + name, wait_until="load")
            await pg.wait_for_timeout(1800)
            await pg.screenshot(path=str(OUT / (tag + ".png")))
            print("shot:", tag)
        await b.close()

asyncio.run(main())
