"""Compare the two font variants on the **live** page, injecting the fonts at runtime.

The previous attempt copied the HTML locally and rewrote relative asset paths; the layout came out
broken because enough of the CSS did not resolve, which makes the comparison useless -- the user
asked to compare *fonts on that page*, not a degraded copy of it.

Loading the deployed URL and calling `addStyleTag` keeps every real stylesheet in place, so the only
difference between the two screenshots is the font.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "data" / "state" / "shots"
URL = "https://siweimidu.github.io/ai-ribao/2026-10-16.html"

FONT_HREF = (
    "https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:ital,wght@0,500;0,600;0,700;0,800;0,900;1,700"
    "&family=Noto+Serif+SC:wght@400;500;600;700;900"
    "&family=Noto+Sans+SC:wght@300;400;500;700"
    "&family=IBM+Plex+Mono:wght@300;400;500&display=swap"
)

VARS = """
:root{
  --f-serif:"Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  --f-display:"Playfair Display","Noto Serif SC",Georgia,serif;
  --f-sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono","JetBrains Mono","SFMono-Regular",Consolas,monospace;
}
/* UI chrome stays sans: small serif is hard to scan in a 240px rail. */
.rail__item,.rail__sub button,.rail__btn,.toc__nav a,button,input,select,summary,
.rail__brand,.issue__date,.item__meta span,.section__count{
  font-family:var(--f-sans);
}
/* Headings are serif in both variants -- the template does this. */
.issue__title,.item__title,.section__title,h1,h2,h3,.rail__brand{font-family:var(--f-serif);}
/* Numbers and timestamps take the mono face in both variants. */
.stats b,.cal__month,.ecal__month,[data-theme-summary],.item__meta{font-family:var(--f-mono);font-feature-settings:"tnum";}
"""

BODY_SANS = """
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline{font-family:var(--f-sans);}
"""

BODY_SERIF = """
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline{font-family:var(--f-serif);}
"""

BANNER = """
(function(l){
  var d=document.createElement('div');
  d.textContent=l;
  d.style.cssText='position:fixed;left:0;right:0;top:0;z-index:2147483647;background:#0065fd;color:#fff;'+
    'font:600 15px/1.7 system-ui,sans-serif;padding:9px 20px;letter-spacing:.02em;box-shadow:0 2px 10px rgba(0,0,0,.18)';
  document.body.appendChild(d);
})(%s);
"""


async def shot(page, label: str, extra: str, tag: str) -> None:
    await page.goto(URL, wait_until="load", timeout=60000)
    await page.wait_for_timeout(1200)
    await page.add_style_tag(url=FONT_HREF)
    await page.add_style_tag(content=VARS + extra)
    await page.evaluate(BANNER % repr(label))
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(3500)

    fams = await page.evaluate(
        """() => {
          const g = (s) => { const e = document.querySelector(s); return e ? getComputedStyle(e).fontFamily.split(',')[0] : '-'; };
          return { title: g('.issue__title'), item: g('.item__title'), facts: g('.facts'), meta: g('.item__meta') };
        }"""
    )
    print(f"  {tag}: 页标题={fams['title']}  条目标题={fams['item']}  正文={fams['facts']}")

    await page.screenshot(path=str(SHOTS / f"cmp-{tag}-top.png"))
    await page.evaluate("window.scrollTo(0, 900)")
    await page.wait_for_timeout(600)
    await page.screenshot(path=str(SHOTS / f"cmp-{tag}-item.png"))


async def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1240, "height": 1000}, device_scale_factor=2)
        await shot(page, "方案 A · 模板的做法 —— 标题宋体 / 正文无衬线 / 数字等宽", BODY_SANS, "A")
        await shot(page, "方案 B · 全部宋体 —— 标题与正文都用 Noto Serif SC", BODY_SERIF, "B")
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
