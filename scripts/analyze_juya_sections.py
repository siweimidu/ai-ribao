"""Print each section's stories so the taxonomy can be defined from examples, not adjectives.

The section analysis showed the ordering is categorical and deterministic, and that within a
section no title feature predicts position. So reproducing 橘鸦's order reduces to classifying
correctly, and the classifier has to be written against what 橘鸦 actually puts in each section.

This dumps them, most recent issue first, so the boundary cases are visible: where does
`Claude Code 桌面版更新` belong (开发生态) versus `豆包工作上线数据导入` (产品应用)?
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
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
    juya = sorted(
        (i for i in items if i.source_id == "rss:daily-juya-uk"),
        key=lambda i: i.title, reverse=True,
    )
    by_section: dict[str, list[str]] = defaultdict(list)
    for item in juya:
        rows = sorted(parse(item.content_text or ""), key=lambda r: r[0])
        if len(rows) < 8:
            continue
        for _, section, title in rows:
            by_section[section].append(title)

    for section in ("要闻", "模型发布", "开发生态", "产品应用", "技术与洞察", "行业动态", "其他"):
        titles = by_section.get(section) or []
        if not titles:
            continue
        print(f"\n{'=' * 74}\n{section}  共 {len(titles)} 条\n{'=' * 74}")
        for t in titles[:26]:
            print(f"  · {t[:76]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
