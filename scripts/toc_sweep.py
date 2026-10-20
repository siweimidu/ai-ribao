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
        await pg.wait_for_timeout(1200)

        # Fine-grained sweep: does the highlighted item stay inside the visible slice?
        bad = []
        for y in range(0, 24000, 800):
            await pg.evaluate("window.scrollTo(0, %d)" % y)
            await pg.wait_for_timeout(160)
            d = await pg.evaluate("""() => {
              const t = document.querySelector(".toc");
              const cur = t.querySelector('a[aria-current="true"]');
              if (!cur) return { none: true };
              const box = t.getBoundingClientRect();
              const it = cur.getBoundingClientRect();
              return {
                visible: it.top >= box.top - 1 && it.bottom <= box.bottom + 1,
                gapTop: Math.round(it.top - box.top),
                gapBottom: Math.round(box.bottom - it.bottom),
                cur: cur.textContent.trim().slice(0, 20),
              };
            }""")
            if d.get("none"):
                bad.append((y, "no highlight"))
            elif not d["visible"]:
                bad.append((y, "outside", d["gapTop"], d["gapBottom"], d["cur"]))

        print("  扫描 scrollY 0..24000（每 800 一档）：")
        if not bad:
            print("    所有档位下，高亮项都在目录可视区内")
        else:
            for row in bad[:10]:
                print("    FAIL", row)
            print("    共 %d 档异常" % len(bad))
        await b.close()

asyncio.run(main())
