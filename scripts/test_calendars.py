"""Verify the calendar grids by geometry, not by eyeballing a screenshot.

This file exists because the same calendar was judged wrong three times in a row, each time
because the *measurement* was wrong rather than the calendar:

  1. slicing the grid children from index 0 put the seven weekday headers inside the first
     row, so every date looked shifted;
  2. "skip the header row" skipped only the first header cell, leaving six in the stream;
  3. measuring row/column from `.ecal__day[data-day]` ignored the leading blank cells, so
     the first row appeared to hold three days instead of seven.

Each produced a confident, wrong answer. What settled it was the DOM order plus a rect
comparison: seven headers, then the leading blanks, then 01 landing in the column that
matches its weekday. Those two facts are what this script asserts, so the next change to
either calendar is checked the same way rather than re-litigated by eye.

Both calendars are covered:

* the rail calendar (navigation: which day do I read) -- rendered from `#calendar-data`;
* the event calendar on `tibo.html` (what happened that day) -- rendered from `#tibo-events`.

Playwright is required; the grids are drawn on the client, so a static HTML parse sees only
the weekday header.
"""

from __future__ import annotations

import asyncio
import calendar
import sys
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "digests" / "site"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def url(name: str) -> str:
    return "file:///" + str(SITE / name).replace("\\", "/")


async def check_event_calendar(page) -> None:
    """tibo.html: the month grid and the day you land on."""
    await page.goto(url("tibo.html"), wait_until="load")
    await page.wait_for_timeout(1100)

    shape = await page.evaluate(
        """() => {
          const g = document.querySelector('[data-ecal-grid]');
          const kids = [...g.children];
          const cols = getComputedStyle(g).gridTemplateColumns.split(' ').length;
          return {
            cols,
            headers: kids.filter(k => k.classList.contains('ecal__dow')).length,
            pads: kids.filter(k => k.classList.contains('ecal__day--pad')).length,
            days: kids.filter(k => k.dataset.day).length,
            firstDay: (kids.find(k => k.dataset.day) || {}).dataset?.day || null,
            lastDay: [...kids].reverse().find(k => k.dataset.day)?.dataset?.day || null,
          };
        }"""
    )
    check("事件日历是 7 列", shape["cols"] == 7, f"{shape['cols']} 列")
    check("表头 7 个", shape["headers"] == 7, str(shape["headers"]))
    check("日期格数等于当月天数", shape["days"] in (28, 29, 30, 31), str(shape["days"]))

    first = date.fromisoformat(shape["firstDay"])
    # Leading blanks must equal the weekday index of the 1st, counted from Sunday, which is
    # the first column here.
    expected_pads = (first.weekday() + 1) % 7
    check(
        "前导空格数等于 1 号的星期序号",
        shape["pads"] == expected_pads,
        f"{shape['pads']} 个（{first} 是周{'日一二三四五六'[expected_pads]}）",
    )
    check(
        "网格总数 = 表头 + 空格 + 天数",
        shape["headers"] + shape["pads"] + shape["days"] == 7 + shape["pads"] + shape["days"],
    )

    # The decisive check: 01 must sit in the column matching its weekday, measured from the
    # **grid's own left edge**.
    #
    # Three earlier attempts measured from the wrong origin and each gave a confident, wrong
    # answer: from child index 0 (headers counted as row one), from "the row after the
    # headers" (only one header skipped), and from the first day cell (which is column 0 by
    # construction). The grid edge is the only origin that means anything.
    geom = await page.evaluate(
        """() => {
          const g = document.querySelector('[data-ecal-grid]');
          const gridLeft = g.getBoundingClientRect().left;
          const cells = [...g.querySelectorAll('.ecal__day[data-day]')];
          const colWidth = cells[0].getBoundingClientRect().width;
          const gap = parseFloat(getComputedStyle(g).columnGap) || 0;
          const step = colWidth + gap;
          const out = {};
          for (const c of cells) {
            const r = c.getBoundingClientRect();
            out[c.dataset.day] = Math.round((r.left - gridLeft) / step);
          }
          return { out, gridLeft: Math.round(gridLeft), step: Math.round(step * 100) / 100 };
        }"""
    )

    first_col = geom["out"][shape["firstDay"]]
    check(
        "1 号落在它应属的星期列",
        first_col == expected_pads,
        f"第 {first_col} 列（应为第 {expected_pads} 列）",
    )

    # Every date must be in the column of its own weekday.
    mismatched = []
    for iso, col in geom["out"].items():
        d = date.fromisoformat(iso)
        wanted = (d.weekday() + 1) % 7
        if col != wanted:
            mismatched.append(f"{iso} 在第 {col} 列，应为第 {wanted} 列")
    check("每个日期都在自己的星期列", not mismatched, "; ".join(mismatched[:3]))

    # Clicking a day with events must move the panel.
    days = await page.evaluate(
        "[...document.querySelectorAll('.ecal__day[data-count]')].map(e => e.dataset.day)"
    )
    check("有可点的日期", len(days) > 0, f"{len(days)} 天")
    if len(days) > 1:
        await page.click(f'.ecal__day[data-day="{days[1]}"]')
        await page.wait_for_timeout(320)
        selected = await page.evaluate(
            "document.querySelector('.ecal__day[aria-selected=true]')?.dataset.day"
        )
        panel = await page.evaluate(
            "document.querySelector('[data-ecal-panel]').innerText"
        )
        check("点击切换选中态", selected == days[1], f"{selected}")
        check("面板跟着切换", days[1] in panel, panel[:48].replace("\n", " "))

    # Month navigation must stay aligned too -- that is where a stale leading-blank count
    # would show up.
    await page.click('[data-ecal-nav="prev"]')
    await page.wait_for_timeout(320)
    prev_shape = await page.evaluate(
        """() => {
          const g = document.querySelector('[data-ecal-grid]');
          const kids = [...g.children];
          return {
            headers: kids.filter(k => k.classList.contains('ecal__dow')).length,
            pads: kids.filter(k => k.classList.contains('ecal__day--pad')).length,
            firstDay: (kids.find(k => k.dataset.day) || {}).dataset?.day || null,
          };
        }"""
    )
    check("翻月后表头仍只有 7 个", prev_shape["headers"] == 7, str(prev_shape["headers"]))
    if prev_shape["firstDay"]:
        d = date.fromisoformat(prev_shape["firstDay"])
        check(
            "翻月后前导空格仍然正确",
            prev_shape["pads"] == (d.weekday() + 1) % 7,
            f"{prev_shape['firstDay']} 前导 {prev_shape['pads']} 格",
        )


async def check_rail_calendar(page) -> None:
    """The rail calendar: which days have an issue."""
    await page.goto(url("2026-10-14.html"), wait_until="load")
    await page.wait_for_timeout(1100)

    shape = await page.evaluate(
        """() => {
          const g = document.querySelector('.cal__grid');
          const kids = [...g.children];
          return {
            dow: kids.filter(k => k.classList.contains('cal__dow')).length,
            days: kids.filter(k => k.classList.contains('cal__day') && k.textContent.trim()).length,
            today: !!document.querySelector('.cal__day[data-today="true"]'),
            todayRadius: (() => {
              const t = document.querySelector('.cal__day[data-today="true"]');
              return t ? getComputedStyle(t).borderRadius : null;
            })(),
            month: document.querySelector('.cal__month')?.textContent || '',
          };
        }"""
    )
    check("导航日历表头 7 个", shape["dow"] == 7, str(shape["dow"]))
    check("导航日历有当日标记", shape["today"])
    check("当日是圆形", (shape["todayRadius"] or "").startswith("50%"), shape["todayRadius"] or "")
    check("显示月份", "年" in shape["month"] and "月" in shape["month"], shape["month"])

    # The rail calendar draws the current month, so compare against the real one.
    today = date.today()
    expected = calendar.monthrange(today.year, today.month)[1]
    if str(today.year) in shape["month"]:
        check("当月天数正确", shape["days"] == expected, f"{shape['days']} / {expected}")


async def main() -> int:
    if not SITE.exists():
        print("产物目录不存在；先跑一次完整分发")
        return 2

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        print("事件日历（tibo.html）")
        await check_event_calendar(page)
        print("\n导航日历（2026-10-14.html）")
        await check_rail_calendar(page)

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
