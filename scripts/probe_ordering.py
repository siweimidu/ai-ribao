"""Probe how the reference sites ORDER their content.

Not what they look like -- how they decide what comes first. That is the question the
current ranking gets wrong, and it cannot be answered from a screenshot: the ordering rule
lives in the DOM (section order, item order, numbers attached to each item) and in what each
item displays (is there a rank? a score? a heat number? a source count?).

Three references, each with a different editorial stance:

* `daily.juya.uk`  — a hand-edited Chinese morning briefing. The user points at it as the
  standard: a frontier model launch leads the issue.
* `ainewslog.com`  — an aggregator with a `/zh` front end.
* `hex2077.dev`    — a dated docs site, so its ordering is presumably chronological.

For each one this captures, per section and per item: the heading, the item title, and any
numeric badge rendered next to it -- plus the raw text of the first few items so the shape of
the ranking is visible even when it is not numeric.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "data" / "state" / "reference"

SITES = [
    ("juya-order", "https://daily.juya.uk/issues/2026-10-14/"),
    ("ainewslog-order", "https://www.ainewslog.com/zh/"),
    ("hex2077-order", "https://hex2077.dev/docs/2026-10/2026-10-13/"),
]

#: Extract ordered structure: h1-h4 headings with the items that follow each, plus any
#: number that appears near an item (a rank, a score, a heat value).
PROBE = r"""() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

  // Walk the document in order, recording headings and the links that follow them.
  const blocks = [];
  let current = { heading: '(lead)', level: 0, items: [] };
  const headings = new Set(['H1', 'H2', 'H3', 'H4']);

  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let node = walker.currentNode;
  while (node) {
    const tag = node.tagName;
    if (headings.has(tag)) {
      const text = clean(node.textContent);
      if (text) {
        if (current.items.length || current.heading !== '(lead)') blocks.push(current);
        current = { heading: text.slice(0, 80), level: Number(tag[1]), items: [] };
      }
    } else if (tag === 'A') {
      const text = clean(node.textContent);
      const href = node.getAttribute('href') || '';
      if (text.length > 6 && text.length < 200 && href && !href.startsWith('#')) {
        // Any number rendered inside or immediately beside the link is likely a rank or a
        // heat value, which is the thing this probe is looking for.
        const parent = node.parentElement;
        const parentText = clean(parent ? parent.textContent : '');
        const nums = (text + ' ' + parentText.slice(0, 120)).match(/\d+(\.\d+)?/g) || [];
        current.items.push({
          text: text.slice(0, 110),
          href: href.slice(0, 90),
          numbers: nums.slice(0, 4),
        });
      }
    }
    node = walker.nextNode();
  }
  if (current.items.length || current.heading !== '(lead)') blocks.push(current);

  // Anything that looks like an explicit score or heat badge.
  const badges = [...document.querySelectorAll('[class*="score"],[class*="heat"],[class*="rank"],[class*="hot"],[class*="count"],[class*="views"],[class*="point"]')]
    .slice(0, 60)
    .map(el => ({ cls: (el.className || '').toString().slice(0, 50), text: clean(el.textContent).slice(0, 40) }))
    .filter(b => b.text);

  return {
    title: document.title,
    url: location.href,
    blocks: blocks.filter(b => b.items.length).slice(0, 24),
    badges,
    itemCount: document.querySelectorAll('a').length,
    h1: clean((document.querySelector('h1') || {}).textContent),
  };
}"""


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for name, url in SITES:
            if only and only not in name:
                continue
            print(f"\n{'='*72}\n{name}\n{url}\n{'='*72}")
            page = await browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                # `networkidle` never fires on these sites: they keep a connection open, so
                # the expectation times out even though the page is fully rendered. Wait for
                # the DOM and then settle, and block nothing -- the ordering lives in the
                # markup, not in a late request.
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(5000)
                data = await page.evaluate(PROBE)
                if not data.get("blocks"):
                    await page.wait_for_timeout(5000)
                    data = await page.evaluate(PROBE)
            except Exception as exc:  # noqa: BLE001
                print(f"  抓取失败: {type(exc).__name__}: {exc}")
                await page.close()
                continue

            (OUT / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )

            print(f"  标题: {data['title'][:70]}")
            print(f"  h1  : {data['h1'][:70]}")
            print(f"\n  --- 结构（按文档顺序）---")
            for block in data["blocks"]:
                print(f"\n  【{block['heading']}】  {len(block['items'])} 项")
                for item in block["items"][:6]:
                    nums = f"  nums={item['numbers']}" if item["numbers"] else ""
                    print(f"      · {item['text'][:76]}{nums}")

            if data["badges"]:
                print(f"\n  --- 分数/热度类徽标（{len(data['badges'])}）---")
                for b in data["badges"][:14]:
                    print(f"      .{b['cls']:46} {b['text'][:34]}")
            await page.close()
        await browser.close()

    print(f"\n原始数据: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
