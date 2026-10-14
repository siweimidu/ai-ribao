"""Static-frame design audit, run against the real rendered page.

The motion-web skill's first gate is the still frame: screenshot with all motion off and
judge that alone. Reading a screenshot by eye answers "does it look wrong", not "what are
the numbers", so this measures the values the skill actually specifies:

  * the type-scale ratio (measured median on award winners: ~8x, and under ~4x a page has
    no scale contrast at all)
  * how many distinct text sizes are in use (one 0.3s-ease page reads as a default)
  * the display line-height, which for CJK must be ~1.4-1.6 rather than the Latin 1.0
  * horizontal overflow at mobile widths
  * whether the row grid collapsed, which is what a too-large display size does

Report-only: it prints numbers and flags, it does not fail a build.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent


async def audit(url: str, width: int, height: int, label: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})
        # reduced-motion ON: this is the still frame the skill says to judge first
        await page.emulate_media(reduced_motion="reduce")
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(900)

        data = await page.evaluate(
            """() => {
              const px = (v) => parseFloat(v) || 0;
              const rows = [...document.querySelectorAll('.row')].slice(0, 6).map(r => {
                const idx = r.querySelector('.row-index');
                const title = r.querySelector('.row-title');
                const srcs = r.querySelector('.sources');
                const ir = idx ? idx.getBoundingClientRect() : null;
                const sr = srcs ? srcs.getBoundingClientRect() : null;
                return {
                  titleSize: px(getComputedStyle(title).fontSize),
                  titleLineHeight: px(getComputedStyle(title).lineHeight) / px(getComputedStyle(title).fontSize),
                  titleHeight: Math.round(title.getBoundingClientRect().height),
                  indexVisible: ir ? (ir.width > 0 && getComputedStyle(idx).visibility !== 'hidden') : false,
                  indexX: ir ? Math.round(ir.x) : null,
                  sourcesX: sr ? Math.round(sr.x) : null,
                  sourcesWidth: sr ? Math.round(sr.width) : 0,
                };
              });
              const sizes = new Set();
              document.querySelectorAll('h1,h2,h3,p,li,span,a,b').forEach(el => {
                const s = getComputedStyle(el).fontSize;
                if (el.textContent.trim()) sizes.add(Math.round(px(s)));
              });
              const h1 = document.querySelector('h1');
              const body = document.body;
              return {
                h1Size: px(getComputedStyle(h1).fontSize),
                h1LineHeight: px(getComputedStyle(h1).lineHeight) / px(getComputedStyle(h1).fontSize),
                h1Height: Math.round(h1.getBoundingClientRect().height),
                bodySize: px(getComputedStyle(body).fontSize),
                distinctSizes: [...sizes].sort((a,b)=>a-b),
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                rowCount: document.querySelectorAll('.row').length,
                rows,
              };
            }"""
        )
        data["label"] = label
        data["viewport"] = {"width": width, "height": height}
        await browser.close()
        return data


def report(d: dict) -> None:
    vw = d["viewport"]["width"]
    ratio = d["h1Size"] / d["bodySize"] if d["bodySize"] else 0
    print(f"\n=== {d['label']}  ({vw}px) ===")
    print(f"  展示字 {d['h1Size']:.0f}px  正文 {d['bodySize']:.0f}px  比例 {ratio:.1f}x", end="")
    print("  ✅" if ratio >= 4 else "  ❌ 比值 <4x：没有尺度对比")
    print(f"  h1 行高 {d['h1LineHeight']:.2f}（中文应 1.3-1.6）", end="")
    print("  ✅" if 1.25 <= d["h1LineHeight"] <= 1.7 else "  ❌")
    print(f"  h1 占高 {d['h1Height']}px", end="")
    print("  ❌ 超过一屏的三分之一" if d["h1Height"] > 260 else "  ✅")
    print(f"  字号种类 {len(d['distinctSizes'])}: {d['distinctSizes']}")
    print(f"  横向溢出 {d['scrollWidth']} vs {d['clientWidth']}", end="")
    print("  ✅" if d["scrollWidth"] <= d["clientWidth"] + 1 else "  ❌ 出现横向滚动")
    print(f"  事件行 {d['rowCount']} 条，前 3 行网格：")
    for i, r in enumerate(d["rows"][:3], 1):
        ok_idx = "✅" if r["indexVisible"] else "❌ 序号不可见"
        ok_src = "✅" if r["sourcesWidth"] > 60 else "❌ 来源列塌了"
        print(f"    {i}. 序号 {ok_idx}(x={r['indexX']})  来源 {ok_src}(x={r['sourcesX']}, w={r['sourcesWidth']})"
              f"  标题 {r['titleSize']:.0f}px/行高{r['titleLineHeight']:.2f}/{r['titleHeight']}px")


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "file:///" + str(ROOT / "data" / "digests" / "site" / "2026-10-14.html").replace("\\", "/")
    )
    results = []
    for width, height, label in ((1440, 1000, "桌面"), (1024, 900, "小桌面"), (390, 844, "移动")):
        results.append(await audit(url, width, height, label))
    for d in results:
        report(d)
    out = ROOT / "data" / "state" / "design_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n写入 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
