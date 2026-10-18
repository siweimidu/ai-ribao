"""Render three UI variants over the real 2026-10-17 page, side by side as screenshots.

The user asked for options before any of them is applied, so each variant is injected into a live
copy of the page rather than committed to the stylesheet. That also means each one is judged on the
*real* content: the same 60 headlines, the same rail, the same calendar.

Three directions, chosen to differ in structure rather than only in colour:

  A 编辑部  Editorial -- a magazine masthead: rules, a wide serif headline block, numbered stories
     set like a printed contents page, generous white space, no cards.
  B 卡片    Cards -- each story in a bordered surface with a lead-in number and a clear meta row;
     the page reads as a stack of objects. Strongest scannability, most "product".
  C 报纸    Broadsheet -- a compact two-column rhythm, hairline rules between stories, small caps
     section marks, tight leading. Highest information density per screen.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playwright.async_api import async_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "data" / "digests" / "site" / "2026-10-17.html"
OUT = ROOT / "data" / "state" / "shots"

COMMON = """
/* Story numbers become a real marker in every variant. */
.item { position: relative; }
"""

VARIANT_A = COMMON + """
/* ── A 编辑部 ───────────────────────────────────────────────────────────── */
body { background: #fbfaf7; }
.content { max-width: 46rem; }
.issue__head { border-top: 3px double var(--fg); padding-top: 1.5rem; }
.issue__date { letter-spacing: .18em; text-transform: uppercase; font-size: .72rem; }
.issue__title { font-weight: 800; letter-spacing: -.035em; line-height: 1.05; }
.stats { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
         padding-block: 1.1rem; margin-block: 2rem; }
.stats b { font-size: 1.1rem; font-weight: 600; }
.stats span { letter-spacing: .1em; text-transform: uppercase; font-size: .68rem; }
.section { margin-top: 3.25rem; }
.section__title { font-family: var(--f-serif); font-size: 1.6rem; letter-spacing: -.02em;
                  border-bottom: 1px solid var(--border); padding-bottom: .5rem; }
.section__count { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; }
.item { padding: 1.15rem 0 1.15rem 3.2rem; border-bottom: 1px solid var(--border); }
.item__title { font-family: var(--f-serif); font-weight: 700; line-height: 1.35; }
.item__meta { margin-top: .45rem; }
.item__no { font-family: var(--f-mono); font-size: .8rem; color: var(--accent);
             align-self: start; padding-top: .2rem; }
"""

VARIANT_B = COMMON + """
/* ── B 卡片 ─────────────────────────────────────────────────────────────── */
body { background: #f6f7f9; }
.issue__head { padding-bottom: 1.5rem; }
.stats { background: var(--surface); border: 1px solid var(--border); border-radius: 1rem;
         padding: 1.25rem 1.5rem; margin-block: 1.85rem; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.section { margin-top: 2.5rem; }
.section__title { font-size: 1.05rem; font-weight: 650; letter-spacing: 0; }
.item { background: var(--surface); border: 1px solid var(--border); border-radius: .9rem;
        padding: 1.15rem 1.35rem 1.2rem 3rem; margin-bottom: .7rem;
        box-shadow: 0 1px 2px rgba(16,24,40,.04); transition: box-shadow .18s, transform .18s; }
.item:hover { box-shadow: 0 6px 20px rgba(16,24,40,.09); transform: translateY(-1px); }
.item__title { font-weight: 650; line-height: 1.4; }
.item__no { width: 1.35rem; height: 1.35rem; border-radius: 50%; background: var(--accent-soft);
             color: var(--accent); display: grid; place-items: center;
             font-family: var(--f-mono); font-size: .68rem; font-weight: 600; flex: none; }
.rail, .toc { background: transparent; }
"""

VARIANT_C = COMMON + """
/* ── C 报纸 ─────────────────────────────────────────────────────────────── */
body { background: #fdfcf9; }
.content { max-width: 52rem; }
.issue__title { font-weight: 800; letter-spacing: -.04em; line-height: 1.02;
                border-bottom: 2px solid var(--fg); padding-bottom: .4rem; }
.stats { gap: 0; margin-block: 1.25rem; padding-block: .8rem;
         border-top: 1px solid var(--fg); border-bottom: 1px solid var(--fg); }
.stats div { border-right: 1px solid var(--border); padding-right: 1.1rem; }
.stats div:last-child { border-right: 0; }
.stats b { font-size: .95rem; }
.section { margin-top: 2.15rem; }
.section__title { font-family: var(--f-sans); font-size: .78rem; font-weight: 700;
                  letter-spacing: .16em; text-transform: uppercase;
                  border-bottom: 1px solid var(--fg); padding-bottom: .35rem; }
.item { padding: .62rem 0 .62rem 2.4rem; border-bottom: 1px dotted var(--border); }
.item__title { font-size: .96rem; line-height: 1.45; }
.item__meta { display: none; }
.item__no { font-family: var(--f-mono); font-size: .72rem; color: var(--muted-fg); }
"""

VARIANTS = [("A-editorial", VARIANT_A), ("B-cards", VARIANT_B), ("C-broadsheet", VARIANT_C)]


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1240, "height": 1000}, device_scale_factor=2)
        for tag, css in VARIANTS:
            await page.goto(PAGE.as_uri(), wait_until="load")
            await page.wait_for_timeout(700)
            await page.add_style_tag(content=css)
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(OUT / f"ui-{tag}-top.png"))
            await page.evaluate("window.scrollTo(0, 1200)")
            await page.wait_for_timeout(400)
            await page.screenshot(path=str(OUT / f"ui-{tag}-body.png"))
            print("  shot:", tag)
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
