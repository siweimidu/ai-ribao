"""把 X 精选区块截出来，判断卡片缩放后的实际观感。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_path = Path("data/digests/site/2026-11-08.html").resolve()
out = Path("work/x-section.png")
out.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    page.goto(page_path.as_uri())
    page.wait_for_timeout(1200)
    section = page.query_selector("#x-highlights")
    if section is None:
        print("找不到 X 精选区块")
        sys.exit(1)
    box = section.bounding_box()
    print("区块尺寸:", int(box["width"]), "x", int(box["height"]))
    card = page.query_selector(".xcard img")
    if card is not None:
        cb = card.bounding_box()
        print("单张卡片显示尺寸:", int(cb["width"]), "x", int(cb["height"]))
    section.scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    section.screenshot(path=str(out))
    browser.close()
print("已截图:", out)
