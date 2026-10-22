import asyncio, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 900})
        try:
            await pg.goto("https://aihot.news/agent?tab=api", wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_timeout(2000)
            txt = await pg.evaluate("() => document.body.innerText")
            print(txt[:2500])
        except Exception as e:
            print("  ERR %s" % str(e)[:90])
        await b.close()

asyncio.run(main())
