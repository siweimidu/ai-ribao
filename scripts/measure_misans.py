"""Measure what MiSans actually costs when loaded from its own chunked CSS.

The package has no single TTF to subset — it ships ~110 woff2 chunks plus a stylesheet with
`unicode-range` on every `@font-face`. That is a *better* arrangement than one subset file when the
page only renders a few hundred distinct characters, because the browser fetches only the chunks
whose ranges it needs.

This loads the real page with MiSans as the body face and records every font request, so the cost is
measured rather than guessed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "data" / "state" / "shots"
URL = "https://siweimidu.github.io/ai-ribao/2026-10-16.html"

MISANS_CSS = "https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css"
SERIF_CSS = (
    "https://fonts.googleapis.com/css2?"
    "family=Noto+Serif+SC:wght@400;700;900"
    "&display=swap"
)
MONO_CSS = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500&display=swap"
)

CSS = """
:root{
  --f-serif:"Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  --f-misans:"MiSans","Noto Sans SC","PingFang SC",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono","JetBrains Mono",Consolas,monospace;
}
/* 标题：宋体 */
.issue__title,.item__title,.section__title,h1,h2,h3,.issue__head h1,.rail__brand{font-family:var(--f-serif);}
/* 数字与元信息：等宽 */
.stats b,.cal__month,.ecal__month,[data-theme-summary],.item__meta,.stats span,
.item__meta,.section__count,.issue__date,.source-row .num{font-family:var(--f-mono);font-feature-settings:"tnum";}
/* 正文与侧栏：MiSans */
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline,
.facts li,.inferences li,.opinions li,.uncertainties li,
.rail__item,.rail__sub button,.rail__btn,.toc__nav a,button,input,select,summary{font-family:var(--f-misans);}
"""


async def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    total: dict[str, int] = {}
    kinds: dict[str, int] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1240, "height": 1000}, device_scale_factor=2)

        # An **async** handler: both `request.response()` and `response.body()` are coroutines, so a
        # sync callback cannot read the size at all. The first attempt reported 0 KB for 38 real
        # font files, which would have made the measurement look like a win.
        async def on_finished(req) -> None:
            url = req.url
            if not url.endswith((".woff2", ".woff", ".ttf")):
                return
            try:
                resp = await req.response()
                body = await resp.body()
                size = len(body)
            except Exception:
                size = 0
            host = url.split("/")[2]
            total[host] = total.get(host, 0) + size
            ext = url.rsplit(".", 1)[-1]
            kinds[ext] = kinds.get(ext, 0) + 1

        page.on("requestfinished", on_finished)
        await page.goto(URL, wait_until="load", timeout=60000)
        await page.wait_for_timeout(1200)
        for href in (SERIF_CSS, MONO_CSS, MISANS_CSS):
            await page.evaluate(
                "(h)=>{const l=document.createElement('link');l.rel='stylesheet';l.href=h;document.head.appendChild(l);}",
                href,
            )
        await page.evaluate(
            "(c)=>{const s=document.createElement('style');s.textContent=c;document.head.appendChild(s);}", CSS
        )
        await page.evaluate("document.fonts.ready")
        await page.wait_for_timeout(5000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3000)

        fams = await page.evaluate(
            """() => {
              const g = s => { const e = document.querySelector(s); return e ? getComputedStyle(e).fontFamily.split(',')[0].replace(/"/g,'') : '-'; };
              return { title: g('.issue__title'), facts: g('.facts'), rail: g('.rail__item'), meta: g('.item__meta') };
            }"""
        )
        print(f"  标题={fams['title']}  正文={fams['facts']}  侧栏={fams['rail']}  元信息={fams['meta']}")

        await page.screenshot(path=str(SHOTS / "misans-top.png"))
        await page.evaluate("window.scrollTo(0, 950)")
        await page.wait_for_timeout(600)
        await page.screenshot(path=str(SHOTS / "misans-body.png"))
        await browser.close()

    print()
    print("  字体下载量（按主机）:")
    grand = 0
    for host, size in sorted(total.items(), key=lambda kv: -kv[1]):
        grand += size
        print(f"    {host:34} {size / 1024:8.1f} KB")
    print(f"    {'合计':34} {grand / 1024:8.1f} KB")
    print(f"  文件数: {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
