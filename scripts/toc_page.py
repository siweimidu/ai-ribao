import asyncio, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

SITE = Path(r"D:\Code\AI日报\data\digests\site")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 900})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto((SITE / "2026-10-18.html").as_uri(), wait_until="load")
        await pg.wait_for_timeout(1200)

        st = await pg.evaluate("""() => {
          const t = document.querySelector(".toc");
          const cs = getComputedStyle(t);
          return { position: cs.position, overflowY: cs.overflowY,
                   clientH: t.clientHeight, scrollH: t.scrollHeight };
        }""")
        print("  目录: position=%s overflow=%s clientH=%d scrollH=%d" % (
            st["position"], st["overflowY"], st["clientH"], st["scrollH"]))
        print()
        print("  scrollY | tocStickyTop | 内部scrollTop | 当前高亮" )

        for y in (0, 900, 2500, 5000, 9000, 14000, 20000):
            await pg.evaluate("window.scrollTo(0, %d)" % y)
            await pg.wait_for_timeout(320)
            d = await pg.evaluate("""() => {
              const t = document.querySelector(".toc");
              const cur = t.querySelector('a[aria-current="true"]');
              return {
                top: Math.round(t.getBoundingClientRect().top),
                inner: Math.round(t.scrollTop),
                cur: cur ? cur.textContent.trim().slice(0, 22) : "(无)",
              };
            }""")
            print("   %6d | %12d | %13d | %s" % (y, d["top"], d["inner"], d["cur"]))

        print()
        print("  JS 错误:", errors or "无")
        await b.close()

asyncio.run(main())
