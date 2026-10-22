import asyncio, io, sys, json
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 2000})
        await pg.goto("https://aihot.news/hot", wait_until="load", timeout=90000)
        await pg.wait_for_timeout(3000)
        # Scroll to force all cards
        for _ in range(4):
            await pg.mouse.wheel(0, 1500)
            await pg.wait_for_timeout(600)
        r = await pg.evaluate("""() => {
          const cards = [...document.querySelectorAll("article.card")];
          return cards.map(c => {
            const t = (c.innerText || "").trim();
            const m = t.match(/^NO\.\s*(\d+)\s*([\s\S]{0,12})/);
            const head = c.querySelector("h2, h3");
            return {
              no: m ? m[1] : "?",
              chip: m ? m[2].replace(/\n/g, " ").trim() : "",
              title: head ? head.innerText.trim() : t.slice(0, 50),
            };
          });
        }""")
        print("  卡片 %d 个" % len(r))
        for x in r:
            print("    NO.%-3s chip=%-14s %s" % (x["no"], x["chip"][:14], x["title"][:52]))
        await b.close()

asyncio.run(main())
