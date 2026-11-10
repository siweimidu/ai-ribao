from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DAY = "2026-11-10"
target = Path(f"data/digests/site/{DAY}.html").resolve()
out = Path("work/item-x.png")
out.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.goto(target.as_uri())
    # 卡片是 loading="lazy"，不滚到视口里就不会解码，量出来高度是 2px。
    page.evaluate("document.querySelectorAll('img[loading=lazy]').forEach(i => { i.loading = 'eager'; })")
    page.wait_for_timeout(2500)
    page.evaluate("Promise.all([...document.images].map(i => i.decode().catch(() => {})))")
    page.wait_for_timeout(800)
    node = page.query_selector(".item__x")
    if node is None:
        print("条目里没有 X 卡片")
        sys.exit(1)
    img = page.query_selector(".item__x img")
    ib = img.bounding_box()
    natural = page.evaluate("() => { const i = document.querySelector('.item__x img');"
                            " return {w: i.naturalWidth, h: i.naturalHeight, done: i.complete}; }")
    print("  卡片显示尺寸:", int(ib["width"]), "x", int(ib["height"]))
    print("  原图尺寸:", natural["w"], "x", natural["h"], " 已解码:", natural["done"])
    item = page.evaluate_handle("document.querySelector('.item__x').closest('li')").as_element()
    item.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    item.screenshot(path=str(out))
    browser.close()
print("已截图:", out)
