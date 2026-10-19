import asyncio, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

SITE = Path(r"D:\Code\AI日报\data\digests\site")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 900})
        await pg.goto((SITE / "2026-10-18.html").as_uri(), wait_until="load")
        await pg.wait_for_timeout(1000)

        r = await pg.evaluate("""() => {
          const t = document.querySelector(".toc");
          const cs = getComputedStyle(t);
          return {
            position: cs.position,
            maxHeight: cs.maxHeight,
            overflowY: cs.overflowY,
            clientH: t.clientHeight,
            scrollH: t.scrollHeight,
            innerScrollbar: t.scrollHeight > t.clientHeight + 2,
            items: t.querySelectorAll(".toc__nav a").length,
          };
        }""")
        for k, v in r.items():
            print("  %-16s %s" % (k, v))

        print()
        print("  === 页面滚动时目录的位置 ===")
        for y in (0, 600, 1500, 3000):
            await pg.evaluate("window.scrollTo(0, %d)" % y)
            await pg.wait_for_timeout(250)
            d = await pg.evaluate("""() => {
              const t = document.querySelector(".toc");
              const r = t.getBoundingClientRect();
              return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height) };
            }""")
            print("    scrollY=%-5d toc.top=%-6d toc.bottom=%-6d h=%d" % (y, d["top"], d["bottom"], d["h"]))
        await b.close()

asyncio.run(main())
