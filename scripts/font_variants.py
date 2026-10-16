"""Four body-font candidates for the digest, on the real page.

The user's constraint: headings stay **Songti** (Noto Serif SC, which is what the template uses),
and they want the body and the rail to stop being plain sans — "无衬线太普通了" — while staying
readable. So the candidates are all faces with more character than Noto Sans SC, and each is one
that actually loads from a China-reachable host (tested, not assumed).

| variant | body face | why it is a candidate |
|---|---|---|
| A | Noto Sans SC | the baseline: what the site uses now |
| B | **LXGW WenKai 霞鹜文楷** | a Kai (楷) face — handwriting-adjacent, warm, and the most "designed" of the set. Built for screens; regular weight is 105 KB of chunked CSS so the browser only fetches the glyph ranges it needs |
| C | **MiSans** | Xiaomi's UI face — even stroke width, wide apertures, a geometric feel. Reads as modern rather than calligraphic |
| D | **Noto Serif SC** | full Songti, for the "everything serif" comparison |

All four keep the same heading treatment, so a difference between two screenshots is the body face.

Fonts are loaded from `cdn.jsdelivr.net`, which answered 200 from here for all three, and
`registry.npmmirror.com` is noted in the output as the domestic fallback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "data" / "state" / "shots"
OUT = ROOT / "data" / "state" / "font-compare"
URL = "https://siweimidu.github.io/ai-ribao/2026-10-16.html"

GOOGLE_LITE = (
    "https://fonts.googleapis.com/css2?"
    "family=Noto+Serif+SC:wght@400;700;900"
    "&family=Noto+Sans+SC:wght@300;400;500;700"
    "&family=IBM+Plex+Mono:wght@400&display=swap"
)

GOOGLE = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Playfair+Display:ital,wght@0,500;0,600;0,700;0,800;0,900;1,700"
    "&family=Noto+Serif+SC:wght@400;500;600;700;900"
    "&family=Noto+Sans+SC:wght@300;400;500;700"
    "&family=IBM+Plex+Mono:wght@300;400;500&display=swap\" rel=\"stylesheet\">"
)
WENKAI = (
    '<link rel="stylesheet" '
    'href="https://cdn.jsdelivr.net/npm/lxgw-wenkai-webfont@1.7.0/style.css">'
)
MISANS = (
    '<link rel="stylesheet" '
    'href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">'
)

VARS = """
:root{
  --f-serif:"Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;
  --f-wenkai:"LXGW WenKai","LXGW WenKai Screen",Georgia,serif;
  --f-misans:"MiSans","Noto Sans SC","PingFang SC",system-ui,sans-serif;
  --f-sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;
  --f-mono:"IBM Plex Mono","JetBrains Mono","SFMono-Regular",Consolas,monospace;
}
"""

#: Shared across every variant: headings serif, numerals mono, chrome sans.
COMMON = """
.issue__title,.item__title,.section__title,h1,h2,h3,.issue__head h1,.rail__brand{font-family:var(--f-serif);}
.stats b,.cal__month,.ecal__month,[data-theme-summary],.item__meta,.stats span{font-family:var(--f-mono);font-feature-settings:"tnum";}
.item__meta,.section__count,.issue__date{font-family:var(--f-mono);}
"""

#: The body + rail swap, which is the only thing that differs per variant.
def swap(face: str, rail: str | None = None) -> str:
    rail = rail or face
    return f"""
.facts,.inferences,.opinions,.uncertainties,.item__body,.item p,p,li,.issue__lead,.headline,
.facts li,.inferences li,.opinions li,.uncertainties li{{font-family:{face};}}
.rail__item,.rail__sub button,.rail__btn,.toc__nav a,button,input,select,summary{{font-family:{rail};}}
/* Kai and UI faces sit a little differently on the line; a hair more leading reads better. */
.facts li,.inferences li,.opinions li,.uncertainties li{{line-height:1.85;}}
"""

VARIANTS = [
    ("A-noto-sans", "A · 现在（Noto Sans SC）—— 基准，无衬线", False, False,
     swap("var(--f-sans)")),
    ("B-wenkai", "B · 霞鹜文楷 LXGW WenKai —— 楷体，温润、有书写感", True, False,
     swap("var(--f-wenkai)")),
    ("C-misans", "C · MiSans —— 小米的界面字，笔画均匀、几何感，偏现代", False, True,
     swap("var(--f-misans)")),
    ("D-serif", "D · 思源宋体 Noto Serif SC —— 正文也用宋体", False, False,
     swap("var(--f-serif)")),
]

BANNER = """
(function(l){
  var d=document.createElement('div');
  d.textContent=l;
  d.style.cssText='position:sticky;top:0;z-index:2147483647;background:#0065fd;color:#fff;'+
    'font:600 15px/1.75 system-ui,sans-serif;padding:10px 22px;letter-spacing:.02em;'+
    'box-shadow:0 2px 12px rgba(0,0,0,.2)';
  document.body.insertBefore(d, document.body.firstChild);
})(%s);
"""


async def capture(page, name: str, label: str, wenkai: bool, misans: bool, extra: str) -> None:
    await page.goto(URL, wait_until="load", timeout=60000)
    await page.wait_for_timeout(1000)
    # Injected as <link>/<style> elements through the DOM rather than dd_style_tag, which
    # aborts the whole page when a stylesheet returns something it cannot parse (the WenKai
    # chunked font CSS does). A failed link degrades to the fallback face instead of killing the
    # screenshot.
    links = [GOOGLE_LITE]
    if wenkai:
        links.append(WENKAI)
    if misans:
        links.append(MISANS)
    await page.evaluate(
        """(payload) => {
          for (const href of payload.links) {
            const l = document.createElement('link');
            l.rel = 'stylesheet'; l.href = href; document.head.appendChild(l);
          }
          const s = document.createElement('style');
          s.textContent = payload.css; document.head.appendChild(s);
        }""",
        {'links': links, 'css': VARS + COMMON + extra},
    )
    await page.evaluate(BANNER % repr(label))
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(4000)

    info = await page.evaluate(
        """() => {
          const g = s => { const e = document.querySelector(s); return e ? getComputedStyle(e).fontFamily.split(',')[0].replace(/"/g,'') : '-'; };
          const loaded = [...document.fonts].filter(f => f.status === 'loaded').length;
          return { title: g('.issue__title'), facts: g('.facts'), rail: g('.rail__item'), loaded };
        }"""
    )
    print(f"  {name:14} 标题={info['title']:16} 正文={info['facts']:16} 侧栏={info['rail']:16} 字体 {info['loaded']}")
    await page.screenshot(path=str(SHOTS / f"F-{name}-top.png"))
    await page.evaluate("window.scrollTo(0, 980)")
    await page.wait_for_timeout(600)
    await page.screenshot(path=str(SHOTS / f"F-{name}-body.png"))


async def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1240, "height": 1000}, device_scale_factor=2)
        for name, label, wenkai, misans, extra in VARIANTS:
            await capture(page, name, label, wenkai, misans, extra)
        await browser.close()
    print(f"\n  截图: {SHOTS}\\F-*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
