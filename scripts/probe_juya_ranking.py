"""What actually determines juya's order?

The earlier probe established *that* items carry `#1`, `#2`, … and no visible score. That
answers "how is it presented" but not "what decided it", and the user has now asked twice
for the ranking itself to be studied.

This looks for every signal a per-item DOM node could carry:

* any number rendered inside the item (source count, score, heat, points);
* how many outbound links each item has (an item with five citations is better sourced);
* the domain mix of those links (first-party announcement vs press vs social);
* any timestamp, and the spread of timestamps across items;
* section membership, to see whether the order is global or per-section;
* and the raw text length of each item's description.

It prints the first twenty items with all of it side by side, so a pattern is visible rather
than inferred.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

URL = "https://daily.juya.uk/issues/2026-10-14/"
OUT = Path(__file__).resolve().parent.parent / "data" / "state" / "reference"

PROBE = r"""() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

  // Each ranked item is an element whose text begins with "#<n>".
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5')];
  const ranked = [];
  for (const h of heads) {
    const t = clean(h.textContent);
    const m = t.match(/#\s*(\d+)\s*$/);
    if (m) ranked.push({ rank: Number(m[1]), el: h, title: t });
  }

  const items = ranked.map(({ rank, el, title }) => {
    // The block this heading owns: walk forward until the next ranked heading.
    let container = el.parentElement;
    let node = el;
    while (container && container.querySelectorAll('h1,h2,h3,h4,h5').length < 2) {
      node = container;
      container = container.parentElement;
      if (!container || container.tagName === 'BODY') break;
    }
    const block = container || el.parentElement;

    const links = block
      ? [...block.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(Boolean)
      : [];
    const external = links.filter(h => /^https?:/.test(h));
    const domains = [...new Set(external.map(h => { try { return new URL(h).hostname.replace(/^www\./,''); } catch { return ''; } }).filter(Boolean))];

    const text = clean(block ? block.textContent : '');
    // Any number that is not the rank itself.
    const numbers = (text.match(/\d+(\.\d+)?/g) || []).filter(n => n !== String(rank)).slice(0, 8);

    const time = block ? block.querySelector('time') : null;

    return {
      rank,
      title: title.replace(/#\s*\d+\s*$/, '').trim().slice(0, 90),
      links: external.length,
      domains,
      numbers,
      chars: text.length,
      time: time ? (time.getAttribute('datetime') || clean(time.textContent)) : null,
    };
  });

  return {
    title: document.title,
    bodyText: clean(document.body.textContent).slice(0, 400),
    rankedCount: ranked.length,
    items,
    // Is there any element mentioning a score, heat, or source count?
    scoreish: [...document.querySelectorAll('[class*="score"],[class*="heat"],[class*="rank"],[class*="point"],[class*="vote"]')]
      .slice(0, 40).map(e => ({ cls: String(e.className).slice(0, 44), t: clean(e.textContent).slice(0, 24) })),
  };
}"""


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1200})
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        data = await page.evaluate(PROBE)
        await browser.close()

    (OUT / "juya-ranking.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"页面: {data['title'][:70]}")
    print(f"编号条目: {data['rankedCount']}\n")
    print(f"{'#':>3} {'链接':>4} {'字数':>5}  域名 / 数字  →  标题")
    for it in data["items"][:24]:
        doms = ",".join(it["domains"][:3])
        nums = ",".join(it["numbers"][:4])
        print(f"{it['rank']:>3} {it['links']:>4} {it['chars']:>5}  {doms[:38]:38} {nums[:22]:22} {it['title'][:40]}")

    if data.get("scoreish"):
        print("\n分数/热度类元素:")
        for s in data["scoreish"][:12]:
            print(f"  .{s['cls']:46} {s['t']}")
    else:
        print("\n没有任何 score/heat/rank/point 类元素 —— 排序不含可见算法信号")
    print(f"\n明细: {OUT / 'juya-ranking.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
