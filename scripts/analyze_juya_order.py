"""Derive 橘鸦's section priority from the rank ranges it assigns.

The first probe showed sections occupying disjoint contiguous rank ranges, so the ordering is
categorical. This extracts the *order of the sections* from every issue and aggregates it, which
gives the priority list directly -- no fitting, no guessing.

It reports:

* the section sequence per issue;
* a pairwise "A before B" tally over all issues, which is the robust form of the ranking: a
  single issue can omit a section, but a pair that never inverts is a rule;
* what fraction of issues each section appears in at all, so a priority is not inferred from a
  section that showed up once.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aidaily.collect import read_items_jsonl  # noqa: E402

HEADLINE = re.compile(r"^(?P<title>.+?)\s*(?:↗|→|»)?\s*#(?P<n>\d{1,3})\s*$", re.M)
SECTION = re.compile(
    r"^(要闻|概览|模型发布|开发生态|产品应用|技术与洞察|行业动态|研究|政策|其他|"
    r"今日要闻|新闻|资讯|快讯|产品|技术)$"
)


def parse(body: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    section = "(无栏目)"
    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("-*• \t")
        if not line:
            continue
        if SECTION.match(line):
            section = line
            continue
        m = HEADLINE.match(line)
        if m:
            out.append((int(m.group("n")), section, m.group("title").strip()))
    return out


def main() -> int:
    items = read_items_jsonl("data/raw/items.jsonl")
    juya = [i for i in items if i.source_id == "rss:daily-juya-uk"]

    sequences: list[list[str]] = []
    per_section_ranks: dict[str, list[int]] = defaultdict(list)
    appearances: Counter[str] = Counter()

    for item in juya:
        rows = sorted(parse(item.content_text or ""), key=lambda r: r[0])
        if len(rows) < 8:              # a short issue says little about ordering
            continue
        seq: list[str] = []
        for _, section, _ in rows:
            if section not in seq:
                seq.append(section)
        sequences.append(seq)
        for rank, section, _ in rows:
            per_section_ranks[section].append(rank)
        for section in seq:
            appearances[section] += 1

    print(f"可用于分析的期数: {len(sequences)}\n")
    print("各期栏目顺序:")
    for seq in sequences:
        print("    " + " > ".join(seq))

    print("\n栏目出现次数 / 名次中位数 / 名次范围:")
    for section, n in appearances.most_common():
        ranks = sorted(per_section_ranks[section])
        mid = ranks[len(ranks) // 2] if ranks else 0
        print(f"    {section:8} 出现 {n:2}/{len(sequences)}  中位名次 {mid:3}  范围 #{min(ranks)}-{max(ranks)}")

    print("\n两两先后（A 在 B 之前 / 共现次数）—— 从不超过 100% 的就是规则:")
    seen_pairs: Counter[tuple[str, str]] = Counter()
    wins: Counter[tuple[str, str]] = Counter()
    for seq in sequences:
        for i, a in enumerate(seq):
            for b in seq[i + 1:]:
                seen_pairs[(a, b)] += 1
                wins[(a, b)] += 1
                seen_pairs[(b, a)] += 1
    rows = []
    for (a, b), w in wins.items():
        total = seen_pairs[(a, b)]
        rows.append((w / total, w, total, a, b))
    for ratio, w, total, a, b in sorted(rows, key=lambda r: (-r[0], -r[2]))[:24]:
        if ratio < 1.0:
            continue
        print(f"    {a:8} 先于 {b:8}  {w}/{total}  ({ratio:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
