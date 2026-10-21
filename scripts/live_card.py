import asyncio, sys, time, re
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

v = int(time.time())

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 820})
        await pg.goto("https://siweimidu.github.io/ai-ribao/2026-10-21.html?v=%d" % v, wait_until="load")
        await pg.wait_for_timeout(2500)

        r = await pg.evaluate("""() => {
          const items = [...document.querySelectorAll("li.item")];
          const both = items.filter(li => li.querySelector(".item__cardwrap") && li.querySelector(".item__images"));
          const cards = items.filter(li => li.querySelector(".item__cardwrap"));
          const cardTitles = cards.map(li => (li.querySelector(".ghm__title") || {}).textContent || "?");
          return {
            items: items.length,
            cards: cards.length,
            both: both.length,
            cardTitles: cardTitles,
          };
        }""")
        for k, val in r.items():
            print("  %-12s %s" % (k, val))
        await b.close()

asyncio.run(main())
