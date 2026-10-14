"""Capture the structure of reference sites.

These are the sites the user pointed at, and the point of reading them is to find out what
they actually have rather than guessing from a screenshot: the sidebar's exact contents and
order, whether there is a right-hand TOC, what the calendar does, and which affordances
exist that this digest lacks.

Renders with Playwright because a plain fetch returns an empty shell for all three.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "state" / "reference"

SITES = [
    ("juya", "https://daily.juya.uk/issues/2026-10-14/"),
    ("aihot-codex", "https://aihot.news/codex-reset"),
    ("aihot-repo", "https://github.com/KKKKhazix/AIHOT"),
]

PROBE = """() => {
  const text = (el) => (el?.innerText || '').replace(/\\s+/g, ' ').trim();
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  };

  // Candidate sidebars: narrow columns pinned near an edge, tall enough to be a rail.
  const rails = [...document.querySelectorAll('aside, nav, [class*="sidebar"], [class*="toc"], [class*="toc"], [class*="rail"], [class*="outline"], [class*="menu"]')]
    .filter(el => el.offsetHeight > 120)
    .map(el => ({ tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 90), box: box(el), text: text(el).slice(0, 600) }));

  const links = [...document.querySelectorAll('a')]
    .map(a => ({ href: a.getAttribute('href'), text: text(a).slice(0, 60), cls: (a.className||'').toString().slice(0, 60) }))
    .filter(l => l.text);

  const buttons = [...document.querySelectorAll('button, [role="button"], summary')]
    .map(b => ({ text: text(b).slice(0, 60), cls: (b.className||'').toString().slice(0, 60), aria: b.getAttribute('aria-label') }))
    .filter(b => b.text || b.aria);

  const headings = [...document.querySelectorAll('h1,h2,h3,h4')]
    .map(h => ({ tag: h.tagName.toLowerCase(), text: text(h).slice(0, 90), id: h.id || null }));

  const calendar = [...document.querySelectorAll('[class*="calendar"], [class*="Calendar"], time, [class*="date"]')]
    .slice(0, 40)
    .map(el => ({ tag: el.tagName.toLowerCase(), cls: (el.className||'').toString().slice(0, 70), text: text(el).slice(0, 80), box: box(el) }))
    .filter(c => c.text);

  return {
    title: document.title,
    lang: document.documentElement.lang,
    rails,
    headings,
    buttons,
    links: links.slice(0, 120),
    calendar,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    fontFamily: getComputedStyle(document.body).fontFamily,
    h1Size: document.querySelector('h1') ? getComputedStyle(document.querySelector('h1')).fontSize : null,
    docHeight: document.documentElement.scrollHeight,
    hasTocScrollSpy: !!document.querySelector('[class*="active"][class*="toc"], [aria-current]'),
  };
}"""


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name, url in SITES:
            if only and only != name:
                continue
            print(f"\n{'='*70}\n{name}  {url}\n{'='*70}")
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                # `domcontentloaded` is too early for a client-rendered site: the body is
                # still empty and every probe returns zero elements. `networkidle` plus a
                # settle wait is what actually gets the app's DOM.
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(5000)
                data = await page.evaluate(PROBE)
                if not data.get("headings") and not data.get("buttons"):
                    await page.wait_for_timeout(6000)
                    data = await page.evaluate(PROBE)
            except Exception as exc:  # noqa: BLE001
                print(f"  抓取失败: {type(exc).__name__}: {exc}")
                await page.close()
                continue

            (OUT / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            # Screenshot is best-effort: these sites load web fonts from third parties and
            # Playwright's screenshot waits for fonts, which can time out on a slow CDN.
            # The DOM capture above is what this script is for; a missing PNG is not a
            # reason to lose the structure.
            try:
                await page.screenshot(path=str(OUT / f"{name}.png"), full_page=False, timeout=12000)
            except Exception as exc:  # noqa: BLE001
                print(f"  （截图跳过: {type(exc).__name__}）")

            print(f"  标题: {data['title'][:80]}")
            print(f"  语言: {data['lang']}  正文底色: {data['bodyBg']}  h1: {data['h1Size']}")
            print(f"  页面高: {data['docHeight']}px")
            print(f"\n  --- 侧栏/导航候选（{len(data['rails'])}）---")
            for r in data["rails"][:6]:
                print(f"    <{r['tag']}> {r['box']}  .{r['cls']}")
                print(f"      文字: {r['text'][:220]}")
            print(f"\n  --- 按钮（{len(data['buttons'])}）---")
            for b in data["buttons"][:18]:
                print(f"    {b['text'][:40]:42} aria={b['aria']}  .{b['cls'][:40]}")
            print(f"\n  --- 日历/时间元素（{len(data['calendar'])}）---")
            for c in data["calendar"][:12]:
                print(f"    <{c['tag']}> {c['text'][:40]:42} {c['box']}  .{c['cls'][:40]}")
            await page.close()
        await browser.close()

    print(f"\n原始数据: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
