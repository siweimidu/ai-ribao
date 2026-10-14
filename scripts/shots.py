"""Screenshots via Playwright, which waits for layout and fonts.

`chrome --headless=new --screenshot` fired before the webfonts settled and before the
paint completed, which produced two artefacts that looked like page bugs: a blank band
where the first three rows should be, and missing index numbers. The DOM inspection in
`_diag_page.py` showed every one of those elements present, opaque and positioned. The
screenshots were lying, so the tool changed rather than the page.

Also captures the reduced-motion still frame, which is the one the design gate is about:
if the page does not read as designed with all motion off, the motion is carrying an
undesigned layout.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "state" / "shots"


async def shoot(page, path: Path, *, full: bool = False) -> None:
    await page.screenshot(path=str(path), full_page=full)
    print(f"  {path.name}  {path.stat().st_size:,} bytes")


async def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-10-14"
    url = "file:///" + str(ROOT / "data" / "digests" / "site" / f"{date}.html").replace("\\", "/")
    OUT.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # --- 桌面：动效开，看首屏 -------------------------------------------------
        page = await browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        await page.goto(url, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.wait_for_timeout(1400)
        print("桌面 1440×1000（动效开）：")
        await shoot(page, OUT / "desktop-fold.png")

        # --- 静止帧：reduced-motion，技能要求先看这一张 ---------------------------
        still = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await still.emulate_media(reduced_motion="reduce")
        await still.goto(url, wait_until="networkidle")
        await still.evaluate("document.fonts.ready")
        await still.wait_for_timeout(600)
        print("桌面静止帧（reduced-motion）——设计闸门看这张：")
        await shoot(still, OUT / "still-desktop.png")
        await shoot(still, OUT / "still-desktop-full.png", full=True)

        # --- 移动 ---------------------------------------------------------------
        mobile = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await mobile.goto(url, wait_until="networkidle")
        await mobile.evaluate("document.fonts.ready")
        await mobile.wait_for_timeout(1000)
        print("移动 390×844：")
        await shoot(mobile, OUT / "mobile-fold.png")
        await shoot(mobile, OUT / "mobile-full.png", full=True)

        # --- 深色 ---------------------------------------------------------------
        dark = await browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="dark")
        await dark.goto(url, wait_until="networkidle")
        await dark.evaluate("document.fonts.ready")
        await dark.wait_for_timeout(600)
        print("深色模式：")
        await shoot(dark, OUT / "dark-fold.png")

        # --- 索引页 -------------------------------------------------------------
        idx = await browser.new_page(viewport={"width": 1440, "height": 900})
        await idx.goto(url.replace(f"{date}.html", "index.html"), wait_until="networkidle")
        await idx.wait_for_timeout(400)
        print("往期索引：")
        await shoot(idx, OUT / "index.png")

        await browser.close()

    print(f"\n输出目录：{OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
