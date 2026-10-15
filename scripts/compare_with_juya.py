"""Compare my ranking against juya's, for the same day, on the same stories.

The user asked twice for the ranking to be studied against `daily.juya.uk`. Reading the page
tells you it is hand-ordered and shows no score -- useful, but it does not tell you *where my
order differs*, which is the only thing that can improve a formula.

So this matches the two lists by story and reports:

* stories juya ran that I did not publish at all (a coverage gap);
* stories we both ran, with each side's position, and the size of the disagreement;
* stories I led with that juya did not rank near the top.

A large systematic gap in one direction is evidence about the formula; a scattered one is
evidence that the two editors simply differ, which is also worth knowing and is not something
to "fix".
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "state" / "reference"
DATE = "2026-10-14"
JUYA_URL = f"https://daily.juya.uk/issues/{DATE}/"

#: Words too common to distinguish one AI headline from another when matching the two lists.
_STOP = re.compile(
    r"(发布|推出|上线|开放|宣布|新增|支持|接入|官宣|正式|全新|首个|最新|"
    r"the|a|an|and|of|to|for|with|new|launches|releases|announces|introduces)",
    re.IGNORECASE,
)


def tokens(title: str) -> set[str]:
    latin = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9.\-]{1,}", title)}
    cjk = set(re.findall(r"[\u4e00-\u9fff]{2,}", title))
    return {t for t in (latin | cjk) if not _STOP.fullmatch(t)}


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def fetch_juya() -> list[dict]:
    probe = r"""() => {
      const clean = s => (s||'').replace(/\s+/g,' ').trim();
      const out = [];
      for (const h of document.querySelectorAll('h1,h2,h3,h4,h5')) {
        const t = clean(h.textContent);
        const m = t.match(/#\s*(\d+)\s*$/);
        if (!m) continue;
        // Scope to the heading's own container: the nearest ancestor that holds exactly
        // this one heading. Walking further up merged every item into one block, which made
        // every row report identical numbers.
        let el = h, scope = h.parentElement;
        while (scope && scope.querySelectorAll('h1,h2,h3,h4,h5').length > 1
               && scope.parentElement && scope.parentElement.tagName !== 'BODY') {
          scope = scope.parentElement;
        }
        const links = scope ? [...scope.querySelectorAll('a[href]')]
          .map(a => a.getAttribute('href'))
          .filter(h => /^https?:/.test(h)) : [];
        const domains = [...new Set(links.map(h => { try { return new URL(h).hostname.replace(/^www\./,''); } catch { return ''; } }).filter(Boolean))];
        out.push({
          rank: Number(m[1]),
          title: t.replace(/#\s*\d+\s*$/,'').trim(),
          links: links.length,
          domains,
          chars: scope ? clean(scope.textContent).length : 0,
        });
      }
      return out;
    }"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1200})
        await page.goto(JUYA_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        items = await page.evaluate(probe)
        await browser.close()
    return items


def load_mine() -> list[dict]:
    path = ROOT / "data" / "digests" / f"{DATE}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    events = doc["digest"]["top_events"]
    insights = doc.get("insights") or {}
    out = []
    for i, e in enumerate(events, start=1):
        ins = insights.get(e["event_id"]) or {}
        out.append({
            "rank": i,
            "title": ins.get("title") or e["title"],
            "event_title": e["title"],
            "heat": (e.get("rank_components") or {}).get("heat"),
        })
    return out


def main() -> int:
    juya = asyncio.run(fetch_juya())
    mine = load_mine()
    print(f"juya {len(juya)} 条 / 本项目 {len(mine)} 条\n")

    if not juya:
        print("juya 抓取为空；可能是网络问题")
        return 1

    # Match each juya story to its best counterpart in mine.
    matched: list[tuple[dict, dict, float]] = []
    unmatched_juya: list[dict] = []
    for j in juya:
        best, score = None, 0.0
        for m in mine:
            s = max(similarity(j["title"], m["title"]), similarity(j["title"], m["event_title"]))
            if s > score:
                best, score = m, s
        if best is not None and score >= 0.28:
            matched.append((j, best, score))
        else:
            unmatched_juya.append(j)

    used = {id(m) for _, m, _ in matched}
    unmatched_mine = [m for m in mine if id(m) not in used]

    print("=== 两边都报道的（按名次差排序）===")
    print(f"{'juya':>5} {'我':>4} {'差':>4}  {'热':>5}  标题")
    rows = sorted(matched, key=lambda t: -(t[1]["rank"] - t[0]["rank"]))
    for j, m, _ in rows[:18]:
        delta = m["rank"] - j["rank"]
        heat = m.get("heat")
        print(f"{j['rank']:>5} {m['rank']:>4} {delta:>+4}  {heat if heat is None else round(heat,3):>5}  {j['title'][:44]}")

    print(f"\n=== juya 报了、我没有的（{len(unmatched_juya)} 条）—— 覆盖缺口 ===")
    for j in unmatched_juya[:12]:
        print(f"  #{j['rank']:<3} [{j['links']:>2}链接] {j['title'][:60]}")

    print(f"\n=== 我报了、juya 没报的（{len(unmatched_mine)} 条）===")
    for m in unmatched_mine[:12]:
        print(f"  {m['rank']:>3} [{m.get('heat')}] {m['title'][:60]}")

    if matched:
        deltas = [m["rank"] - j["rank"] for j, m, _ in matched]
        ranked_higher = sum(1 for d in deltas if d < -3)
        ranked_lower = sum(1 for d in deltas if d > 3)
        agree = sum(1 for d in deltas if abs(d) <= 3)
        print(f"\n=== 汇总 ===")
        print(f"  名次接近（±3）: {agree}/{len(matched)}")
        print(f"  我明显更高  : {ranked_higher}")
        print(f"  我明显更低  : {ranked_lower}")

    (OUT / "juya-comparison.json").write_text(
        json.dumps({"date": DATE, "juya": juya, "mine": mine,
                    "unmatched_juya": unmatched_juya, "unmatched_mine": unmatched_mine},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n明细: {OUT / 'juya-comparison.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
