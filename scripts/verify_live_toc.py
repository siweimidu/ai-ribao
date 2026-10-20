import asyncio, sys, time
sys.path.insert(0, r"D:\Code\AI日报\src")
from playwright.async_api import async_playwright

v = int(time.time())

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1600, "height": 900})
        await pg.goto("https://siweimidu.github.io/ai-ribao/2026-10-18.html?v=%d" % v, wait_until="load")
        await pg.wait_for_timeout(2500)

        st = await pg.evaluate("""() => {
          const t = document.querySelector(".toc");
          if (!t) return { missing: true };
          const cs = getComputedStyle(t);
          return { position: cs.position, overflowY: cs.overflowY,
                   clientH: t.clientHeight, scrollH: t.scrollHeight };
        }""")
        print("  目录: position=%s overflow=%s clientH=%s scrollH=%s" % (
            st.get("position"), st.get("overflowY"), st.get("clientH"), st.get("scrollH")))
        print()
        print("  scrollY | tocTop | 内部scrollTop | 高亮")
        for y in (0, 5000, 9000, 14000, 20000):
            await pg.evaluate("window.scrollTo(0, %d)" % y)
            await pg.wait_for_timeout(350)
            d = await pg.evaluate("""() => {
              const t = document.querySelector(".toc");
              const cur = t.querySelector('a[aria-current="true"]');
              return { top: Math.round(t.getBoundingClientRect().top),
                       inner: Math.round(t.scrollTop),
                       cur: cur ? cur.textContent.trim().slice(0, 24) : "(无)" };
            }""")
            print("   %6d | %6d | %13d | %s" % (y, d["top"], d["inner"], d["cur"]))
        await b.close()

asyncio.run(main())
