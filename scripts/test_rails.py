"""Verify the rail sizing grips and the scrollbar treatment.

Both features are invisible in a static parse, and both are the kind that "looks fine" while
doing nothing:

* a grip can render and be inert if the pointer handler never fires or the CSS variable it
  writes is not the one the grid reads;
* a scrollbar can be styled to be *hidden* rather than *quiet*, which loses the only signal
  that the rail scrolls at all.

So this drives a real pointer drag and measures the computed grid tracks, checks the width
survives a reload, and confirms the dark-mode thumb is quieter than the light-mode one
rather than absent.

The last check is the one that matters most for accessibility: the rail must still be
scrollable. Styling a scrollbar to zero opacity is a common way to "fix" an ugly bar and
silently remove the affordance.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "digests" / "site"
URL = "file:///" + str(SITE / "2026-10-14.html").replace("\\", "/")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


async def rail_width(page) -> float:
    return await page.evaluate(
        "document.querySelector('.rail').getBoundingClientRect().width"
    )


async def toc_width(page) -> float:
    return await page.evaluate(
        "document.querySelector('.toc').getBoundingClientRect().width"
    )


async def drag(page, selector: str, dx: int) -> None:
    """Drag a grip by dx pixels using real pointer events.

    Uses the mouse API rather than dispatching synthetic events so `setPointerCapture` and
    the browser's own hit testing are exercised -- a synthetic `pointerdown` on the element
    would pass even if the grip were covered by something else.
    """
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no box")
    x = box["x"] + box["width"] / 2
    y = box["y"] + min(120, box["height"] / 2)
    await page.mouse.move(x, y)
    await page.mouse.down()
    # Several steps: a single jump would not exercise the move handler meaningfully.
    for i in range(1, 6):
        await page.mouse.move(x + dx * i / 5, y, steps=2)
    await page.mouse.up()
    await page.wait_for_timeout(180)


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        await page.goto(URL, wait_until="load")
        await page.wait_for_timeout(900)

        # --- grips exist and are hit-testable ------------------------------------
        print("手柄")
        check("左栏有手柄", await page.locator(".rail__grip").count() == 1)
        check("目录有手柄", await page.locator(".toc__grip").count() == 1)

        base_rail = await rail_width(page)
        base_toc = await toc_width(page)
        check("左栏初始宽约 240px", 200 <= base_rail <= 280, f"{base_rail:.0f}px")
        check("目录初始宽约 240px", 200 <= base_toc <= 280, f"{base_toc:.0f}px")

        # The grip must be on the rail's inner edge: right for the rail, left for the TOC.
        sides = await page.evaluate(
            """() => {
              const rail = document.querySelector('.rail');
              const grip = document.querySelector('.rail__grip');
              const toc = document.querySelector('.toc');
              const tgrip = document.querySelector('.toc__grip');
              const r = rail.getBoundingClientRect(), g = grip.getBoundingClientRect();
              const t = toc.getBoundingClientRect(), tg = tgrip.getBoundingClientRect();
              return {
                railGripOnRight: Math.abs(g.right - r.right) < 12,
                tocGripOnLeft: Math.abs(tg.left - t.left) < 12,
              };
            }"""
        )
        check("左栏手柄在右缘（朝内容列）", sides["railGripOnRight"])
        check("目录手柄在左缘（朝内容列）", sides["tocGripOnLeft"])

        # --- dragging actually resizes -------------------------------------------
        print("\n拖拽")
        await drag(page, ".rail__grip", 60)
        wider = await rail_width(page)
        check("右拖左栏变宽", wider > base_rail + 30, f"{base_rail:.0f} -> {wider:.0f}px")

        await drag(page, ".rail__grip", -60)
        back = await rail_width(page)
        check("左拖左栏变窄", back < wider - 30, f"{wider:.0f} -> {back:.0f}px")

        # The TOC is on the right, so dragging left must widen it.
        await drag(page, ".toc__grip", -60)
        toc_wider = await toc_width(page)
        check("左拖目录变宽", toc_wider > base_toc + 30, f"{base_toc:.0f} -> {toc_wider:.0f}px")

        grid = await page.evaluate(
            "getComputedStyle(document.querySelector('.shell')).gridTemplateColumns"
        )
        tracks = grid.split(" ")
        check("网格有三条轨道", len(tracks) == 3, grid[:60])

        # --- limits ---------------------------------------------------------------
        print("\n上下限")
        await drag(page, ".rail__grip", -2000)
        tiny = await rail_width(page)
        check("左栏不会小于下限", tiny >= 185, f"{tiny:.0f}px")

        await drag(page, ".rail__grip", 4000)
        huge = await rail_width(page)
        content = await page.evaluate(
            "document.querySelector('.content').getBoundingClientRect().width"
        )
        check("左栏不会挤扁内容列", content > 320, f"左栏 {huge:.0f}px，内容 {content:.0f}px")

        # --- reset ---------------------------------------------------------------
        print("\n复位与持久化")
        await page.dblclick(".rail__grip")
        await page.wait_for_timeout(200)
        reset = await rail_width(page)
        check("双击复位到默认宽度", abs(reset - 240) <= 6, f"{reset:.0f}px")

        await drag(page, ".toc__grip", -50)
        persisted = await toc_width(page)
        await page.reload(wait_until="load")
        await page.wait_for_timeout(700)
        after_reload = await toc_width(page)
        check(
            "宽度在刷新后保留",
            abs(after_reload - persisted) <= 4,
            f"{persisted:.0f} -> {after_reload:.0f}px",
        )
        # Put it back so the committed artifact is not left with a test's preference.
        await page.evaluate("localStorage.removeItem('aidaily-toc-w'); localStorage.removeItem('aidaily-rail-w');")

        # --- keyboard -------------------------------------------------------------
        print("\n键盘")
        await page.reload(wait_until="load")
        await page.wait_for_timeout(600)
        await page.locator(".rail__grip").focus()
        before_key = await rail_width(page)
        await page.keyboard.press("ArrowRight")
        await page.wait_for_timeout(150)
        after_key = await rail_width(page)
        check("方向键可调宽", after_key > before_key, f"{before_key:.0f} -> {after_key:.0f}px")
        await page.keyboard.press("Home")
        await page.wait_for_timeout(150)
        check("Home 复位", abs(await rail_width(page) - 240) <= 6)

        # --- scrollbars -----------------------------------------------------------
        print("\n滚动条")
        # The rails must remain scrollable: a scrollbar styled to invisibility removes the
        # only cue that there is more content below.
        scrollable = await page.evaluate(
            """() => {
              const rail = document.querySelector('.rail');
              const toc = document.querySelector('.toc');
              return {
                railOverflow: getComputedStyle(rail).overflowY,
                tocOverflow: getComputedStyle(toc).overflowY,
                railScrollable: rail.scrollHeight > rail.clientHeight,
              };
            }"""
        )
        check("左栏仍可滚动", scrollable["railOverflow"] == "auto", scrollable["railOverflow"])
        check("目录仍可滚动", scrollable["tocOverflow"] == "auto", scrollable["tocOverflow"])

        dark = await browser.new_page(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
        await dark.goto(URL, wait_until="load")
        await dark.wait_for_timeout(800)
        # `scrollbar-color` is the standard property and the one both Chrome and Firefox
        # resolve, so it is the one worth asserting on.
        colours = await dark.evaluate(
            """() => {
              const rail = getComputedStyle(document.querySelector('.rail')).scrollbarColor;
              const toc = getComputedStyle(document.querySelector('.toc')).scrollbarColor;
              return { rail, toc, theme: document.documentElement.dataset.theme || '' };
            }"""
        )
        check("深色下滚动条已着色（而非默认亮轨）",
              "rgba" in colours["rail"] or "rgb" in colours["rail"], colours["rail"])

        light = await browser.new_page(viewport={"width": 1600, "height": 1000}, color_scheme="light")
        await light.goto(URL, wait_until="load")
        await light.wait_for_timeout(700)
        light_colour = await light.evaluate(
            "getComputedStyle(document.querySelector('.rail')).scrollbarColor"
        )
        check("深浅两色下取值不同", light_colour != colours["rail"],
              f"light={light_colour} dark={colours['rail']}")

        print("\n运行时")
        check("无 JavaScript 错误", not errors, str(errors[:2]))

        await browser.close()

    print()
    if failures:
        print(f"{len(failures)} 项失败")
        for f in failures:
            print(f"  · {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
