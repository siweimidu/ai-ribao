"""Interaction tests for the generated site, run in a real browser.

Written as a file rather than an inline `python -c` because the assertions need both
Python and JavaScript quoting, and the escaping became the bug instead of the test.

What this covers, and why each one is here:

* **theme actually changes colours.** The first version set `data-theme` on the root while
  the CSS only listened to `prefers-color-scheme`, so the control looked functional and did
  nothing.
* **Esc closes the search dialog.** `<dialog>` only self-closes on Esc when the focused
  control does not consume it, and the search input focuses itself on open — so Esc did
  nothing and the modal blocked the whole page.
* **the TOC highlight follows the reading position** and is never empty at the top, which
  reads as broken.
* **no JavaScript error at all.** A leftover TypeScript annotation killed the entire script
  and every interaction above with it, while the Python suite stayed green.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE = "file:///" + str(ROOT / "data" / "digests" / "site" / "2026-10-14.html").replace("\\", "/")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        await page.goto(PAGE, wait_until="load")
        await page.wait_for_timeout(1300)

        # --- structure ---------------------------------------------------------
        print("结构")
        rail_items = await page.evaluate(
            "[...document.querySelectorAll('.rail__item')].map(e=>e.textContent.trim().replace(/\\s+/g,' '))"
        )
        # The expected labels are read from the site as it is, not from memory. Two of these
        # used to be wrong in the guard rather than in the page: 微信公众号 was removed on
        # request (so the guard demanded a link that must not exist), and the download label
        # is "下载 Markdown" with a capital M. Both failed every run while the site was right,
        # which trains people to ignore the guard.
        for want in ("搜索往期内容", "首页", "Tibo 重置监控",
                     "订阅 RSS", "主题", "下载 Markdown"):
            check(f"侧栏有「{want}」", any(want in t for t in rail_items), str(rail_items)[:80])
        check("侧栏不再有「微信公众号」",
              not any("微信公众号" in t for t in rail_items), str(rail_items)[:80])
        check("右侧目录可见", await page.evaluate(
            "(() => { const t = document.querySelector('.toc'); return t && getComputedStyle(t).display !== 'none'; })()"
        ))
        check("无横向溢出", await page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        ))

        # --- calendar ----------------------------------------------------------
        print("日历")
        check("显示月份", "2026" in (await page.evaluate("document.querySelector('.cal__month').textContent")))
        today_style = await page.evaluate(
            """(() => { const d = document.querySelector('.cal__day[data-today="true"]');
                       if (!d) return null; const s = getComputedStyle(d);
                       return { radius: s.borderRadius, bg: s.backgroundColor, shadow: s.boxShadow }; })()"""
        )
        check("当日标记为圆形", bool(today_style) and today_style["radius"].startswith("50%"),
              str(today_style["radius"]) if today_style else "缺失")
        # **Compare against the theme, not against a literal colour.**
        #
        # This asserted `rgb(0, 101, 253)`, the accent of the old default theme. When the
        # default became Claude light the calendar still filled with the right colour and the
        # check failed anyway -- a guard that reports a correct page as broken.
        accent_rgb = await page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
        )
        expected = accent_rgb.lstrip("#")
        expected = "%d, %d, %d" % tuple(int(expected[i:i + 2], 16) for i in (0, 2, 4))
        check("当日用强调色填充",
              bool(today_style) and expected in today_style["bg"].replace("rgb(", ""),
              "%s（期望 %s）" % (today_style["bg"] if today_style else "", expected))
        check("当日有圆形光晕",
              bool(today_style) and "3px" in today_style["shadow"],
              today_style["shadow"][:44] if today_style else "")

        # --- theme -------------------------------------------------------------
        print("主题")
        await page.click(".rail__fold:has([data-theme-summary]) summary")
        await page.wait_for_timeout(250)
        # 自动/默认 were removed from the site on purpose, so `auto` is not a choice any
        # more. This loop used to click it and waited 30 s for a button that does not exist --
        # the guard failed on every run while the site was correct.
        choices = await page.evaluate(
            "[...document.querySelectorAll('[data-theme-choice]')].map(b=>b.dataset.themeChoice)"
        )
        check("提供了多个主题且不含 auto", len(choices) >= 2 and "auto" not in choices, str(choices))

        seen = {}
        for choice in ("dark", "light"):
            await page.click(f'[data-theme-choice="{choice}"]')
            await page.wait_for_timeout(380)
            seen[choice] = {
                "bg": await page.evaluate("getComputedStyle(document.body).backgroundColor"),
                "attr": await page.evaluate("document.documentElement.dataset.theme || ''"),
                "label": (await page.evaluate(
                    "document.querySelector('[data-theme-summary]').textContent")).strip(),
                # The choice must reach storage, or a reader's pick is forgotten on the next
                # page. Read the key the site actually writes (`THEME_KEY` in motion.js is
                # 'aidaily-theme'); guessing 'ai-daily-theme' made this check fail on a site
                # that was working.
                "stored": await page.evaluate(
                    "localStorage.getItem('aidaily-theme') || ''"
                ),
            }
        check("暗色改变背景", seen["dark"]["bg"] != seen["light"]["bg"],
              f"dark={seen['dark']['bg']} light={seen['light']['bg']}")
        check("暗色设置 data-theme", seen["dark"]["attr"] == "dark")
        check("亮色设置 data-theme", seen["light"]["attr"] == "light")
        check("主题选择被记住", seen["dark"]["stored"] != "" and seen["light"]["stored"] != "",
              f"dark={seen['dark']['stored']!r} light={seen['light']['stored']!r}")
        check("标签跟随选择", seen["dark"]["label"] == "标准暗色" and seen["light"]["label"] == "标准亮色",
              f"{seen['dark']['label']}/{seen['light']['label']}")

        await page.click('[data-theme-choice="dark"]')
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(ROOT / "data" / "state" / "shots" / "neo-dark.png"))
        # Restore the light theme for the remaining checks. The panel is still open (clicking
        # a choice does not close it) — clicking the summary again would *close* it and the
        # next click would then time out on an invisible button.
        await page.click('[data-theme-choice="light"]')
        await page.wait_for_timeout(300)

        # --- table of contents --------------------------------------------------
        print("目录滚动高亮")
        highlights = {}
        for y in (0, 1200, 4000, 10000, 20000):
            await page.evaluate(f"window.scrollTo(0,{y})")
            await page.wait_for_timeout(650)
            highlights[y] = await page.evaluate(
                "[...document.querySelectorAll('.toc__nav a[aria-current]')].map(a=>a.textContent.trim())"
            )
        check("顶部有高亮（空高亮读作坏掉）", bool(highlights[0]), str(highlights[0]))
        for y in (0, 4000, 20000):
            check(f"{y}px 处有高亮", len(highlights[y]) == 1, str(highlights[y]))
        check("不同位置高亮会变",
              len({tuple(highlights[y]) for y in (0, 4000, 20000)}) > 1,
              f"0px={highlights[0]} 20000px={highlights[20000]}")
        await page.evaluate("window.scrollTo(0,0)")
        await page.wait_for_timeout(500)

        # --- search -------------------------------------------------------------
        print("搜索")
        await page.keyboard.press("Control+k")
        await page.wait_for_timeout(400)
        check("Ctrl+K 打开", await page.evaluate("document.getElementById('search-dialog').open"))
        await page.fill("#search-dialog input", "Anthropic")
        await page.wait_for_timeout(380)
        hits = await page.evaluate("document.querySelectorAll('.search__results li a').length")
        check("有搜索结果", hits > 0, f"{hits} 条")
        await page.fill("#search-dialog input", "zzzznotfound")
        await page.wait_for_timeout(380)
        check("无结果时有提示", await page.evaluate("!!document.querySelector('.search__empty')"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(320)
        check("Esc 关闭（初版关不掉，挡住整页）",
              not await page.evaluate("document.getElementById('search-dialog').open"))

        # --- mobile -------------------------------------------------------------
        print("移动端")
        mobile = await browser.new_page(viewport={"width": 390, "height": 860})
        await mobile.goto(PAGE, wait_until="load")
        await mobile.wait_for_timeout(900)
        check("移动端抽屉默认收起", await mobile.evaluate(
            "getComputedStyle(document.querySelector('.rail__body')).display === 'none'"))
        await mobile.click(".rail__toggle")
        await mobile.wait_for_timeout(350)
        check("点击后展开", await mobile.evaluate(
            "getComputedStyle(document.querySelector('.rail__body')).display !== 'none'"))
        check("移动端无横向溢出", await mobile.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"))

        # --- errors -------------------------------------------------------------
        print("运行时")
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
    raise SystemExit(asyncio.run(main()))
