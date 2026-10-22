import asyncio, io, sys, re, json
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 900})
        await pg.goto("https://aihot.news/hot", wait_until="networkidle", timeout=90000)
        await pg.wait_for_timeout(2500)
        r = await pg.evaluate("""() => ({
          html_len: document.documentElement.outerHTML.length,
          bodyHead: document.body.innerText.slice(0, 1200),
        })""")
        print("  html_len=%s" % r["html_len"])
        print()
        print(r["bodyHead"])
        await b.close()

asyncio.run(main())
