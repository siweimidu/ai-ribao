import asyncio, sys, time
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

v = int(time.time())

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1300, "height": 900})
        pg = await ctx.new_page()
        await pg.goto("https://siweimidu.github.io/ai-ribao/sources.html?v=%d" % v, wait_until="load")
        await pg.wait_for_timeout(1800)

        r = await pg.evaluate("""() => {
          const rows = [...document.querySelectorAll(".source-row")];
          const links = rows.filter(x => x.tagName === "A");
          const first = links[0];
          return {
            rows: rows.length,
            links: links.length,
            allBlank: links.every(a => a.getAttribute("target") === "_blank"),
            display: first ? getComputedStyle(first).display : null,
            firstHref: first ? first.getAttribute("href") : null,
          };
        }""")
        for k, v2 in r.items():
            print("  %-10s %s" % (k, v2))

        # Click and confirm a new tab opens.
        href = r["firstHref"]
        if href:
            async with ctx.expect_page(timeout=20000) as info:
                await pg.click('a.source-row[href="%s"]' % href)
            np = await info.value
            await np.wait_for_load_state("domcontentloaded", timeout=20000)
            print()
            print("  点击后新标签页: %s" % np.url[:64])
            print("  原页面仍在:     %s" % pg.url.split("/")[-1].split("?")[0])
        await b.close()

asyncio.run(main())
