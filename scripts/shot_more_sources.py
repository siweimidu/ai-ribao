"""截图验证「另有 N 家其他来源」展开后不再溢出卡片。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DAY = "2026-11-10"
target = Path(f"data/digests/site/{DAY}.html").resolve()
out = Path("work/more-sources.png")
out.parent.mkdir(parents=True, exist_ok=True)

MEASURE = (
    "() => { const d = document.querySelector('.item__more');"
    " const u = d.querySelector('ul');"
    " const li = d.closest('li');"
    " const a = li.getBoundingClientRect(); const b = u.getBoundingClientRect();"
    " return {itemBottom: Math.round(a.bottom), listBottom: Math.round(b.bottom)}; }"
)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(target.as_uri())
    page.wait_for_timeout(1000)
    if page.query_selector(".item__more") is None:
        print("没有「另有来源」控件:", DAY)
        sys.exit(1)
    page.evaluate("document.querySelectorAll('.item__more').forEach(d => { d.open = true; })")
    page.wait_for_timeout(400)
    box = page.evaluate(MEASURE)
    print("  条目底部:", box["itemBottom"], " 来源列表底部:", box["listBottom"])
    print("  溢出卡片:", box["listBottom"] > box["itemBottom"] + 1)
    item = page.evaluate_handle("document.querySelector('.item__more').closest('li')").as_element()
    item.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    item.screenshot(path=str(out))
    browser.close()
print("已截图:", out)
